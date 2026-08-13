#!/usr/bin/env python3
"""PreToolUse hook: guard the control plane, log what the main loop does,
and keep delegation pointed at real lanes. Subagent calls (payload contains
agent_id) are always allowed. Fail-open: any parse error or unexpected
payload shape allows the call. This is a seatbelt with an audit trail, not a
security boundary — see the README's "Enforcement & Honesty" section.

Until 0.9.0 this hook denied every main-loop file write and test run, to
force delegation. That was the wrong instrument for the cost: a one-line
comment or a status stamp bought a whole subagent round trip, and the thing
being protected — knowing what the main loop touched — is a log line, not a
denial. So writes and test runs are now ALLOWED and RECORDED, and only the
control plane is refused.

The control plane is what governs the session that is running right now:
settings, hooks, agent and command definitions, and the installed plugin
tree, plus any .env. A plugin's *source* repo is ordinary code — it changes
nothing until it is installed — and treating it as sacred is what made
plugin development expensive.

Escape hatch: set OPULENT_OFF=1 in the environment to disable enforcement.
Eco mode: set OPULENT_ECO=1 and complex implementation runs one effort rung
down — this hook then denies `opulent:coder` with a redirect to the
`opulent:coder-eco` twin (same model and charter, effort xhigh). Both dials are
read from the environment, so both are session-granular.
Telemetry: main-loop edits, test runs, removals, delegations and denials each
append one JSON line to ~/.claude/opulent-log.jsonl (override path with
OPULENT_LOG). Lines carry the payload's session id (first 8 chars) when one
was sent, and every path in a detail is recorded resolved and absolute."""
import datetime
import json
import os
import posixpath
import re
import shlex
import sys
import tempfile

HOME = os.path.expanduser("~")
LOG_PATH = os.environ.get("OPULENT_LOG") or os.path.join(HOME, ".claude", "opulent-log.jsonl")
# `~` and relative spellings are honored and anchored to HOME, not to the
# hook process's cwd: `OPULENT_LOG=~/logs/op.jsonl` used to write nothing,
# silently — open() does not expand `~` — while the self-guard below compared
# against the unexpanded string.
LOG_PATH = os.path.expanduser(LOG_PATH)
if not os.path.isabs(LOG_PATH):
    LOG_PATH = os.path.join(HOME, LOG_PATH)
# The log guards itself below — except when it is os.devnull, which means
# "no log": guarding that would deny every harmless `> /dev/null`.
_LOG_NORM = os.path.normpath(LOG_PATH)
_LOG_GUARDED = _LOG_NORM not in (os.devnull, "/dev/null")

# Session attribution for log lines: set once in main() from the payload.
# Empty (and omitted from the line) when the payload names no session, so
# concurrent sessions stay distinguishable without inventing an id.
_SID = ""


def _log(event, detail):
    try:
        with open(LOG_PATH, "a") as f:
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            entry = {"t": ts, "event": event, "detail": str(detail)[:120]}
            if _SID:
                entry["sid"] = _SID
            # One write() per line, kept well under PIPE_BUF, so concurrent
            # sessions appending to one log cannot tear each other's lines.
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def allow(event=None, detail=None):
    if event:
        _log(event, detail)
    sys.exit(0)


def deny(reason, detail=None, event="deny"):
    _log(event, detail or reason[:80])
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


# Match test/build/lint tools only at command position so commands that merely
# *mention* a tool name are not recorded as runs. These are no longer denied —
# the pattern now decides what gets an audit line, not what gets refused.
# Searched against a copy of the command with quoted spans blanked and heredoc
# bodies stripped (see main), so `git commit -m "…; npm test"` fabricates
# nothing; the raw command is searched only when it cannot be parsed at all.
TEST_RE = re.compile(
    r"(?:^\s*|[;&|({`]\s*|\bthen\s+|\bdo\s+)"      # command position
    r"(?:\w+=\S*\s+)*"                             # env-var prefixes: CI=1 ...
    r"(?:sudo\s+|command\s+|time\s+|npx\s+|bunx\s+|uv\s+run\s+|python3?\s+-m\s+|"
    # timeout takes options before its duration (`timeout -k 5 30 pytest`);
    # both repetitions are bounded so the engine cannot spin on them.
    r"(?:poetry|pipenv|pdm|hatch)\s+run\s+|pnpm\s+exec\s+|"
    r"timeout\s+(?:--?[\w-]+(?:=\S+)?\s+){0,4}(?:[\w.]+\s+){1,3}|"
    r"nohup\s+|stdbuf\s+\S+\s+)*"
    r"(?:[\w@./-]*/)?"                             # path prefixes: ./gradlew
    r"(?:pytest|vitest|jest|playwright\s+test|cargo\s+(?:test|nextest)|go\s+test|"
    r"bun\s+test|phpunit|rspec|tox|ctest|dotnet\s+test|mvn\s+(?:test|verify)|"
    # (?!\w), not (?![\w-]): `npm run test-e2e` is a test script and must
    # match, while the bare tools below refuse a hyphen so `tsc-watch` and
    # `eslint-config-x` are not read as runs of the tool they resemble.
    r"gradlew?\s+test|(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|lint|typecheck|build)(?!\w)|"
    r"make\s+(?:test|check)(?![\w-])|(?:tsc|eslint|ruff|mypy)(?![\w-]))\b",
    re.M)

# Quoted spans, blanked before TEST_RE runs: a tool name inside a commit
# message or a grep pattern is a mention, not a run. Known limit: this also
# blanks `bash -c '…'` payloads, so a test run quoted inside one goes
# unrecorded — the fabrication this kills costs more than that miss.
_QUOTED_RE = re.compile(r"'[^']*'|\"[^\"]*\"")

# Comment spans, blanked after the quotes: `# if it fails then npm test` is
# advice, not a run. Quotes go first, so a quoted `#` never opens one.
_COMMENT_RE = re.compile(r"(?m)(?:^|\s)#[^\n]*")

# Catch-all agents have full tools and inherit the session model; delegating
# to them satisfies "delegation" while defeating "routing".
CATCHALL_AGENTS = {"general-purpose", "claude"}

# Eco mode's one swap. Coder only: the routing log shows the judgment lanes
# barely fire, so a twin for them would save nothing, while coder is the
# high-volume Opus spend. Matched on the plugin-qualified name because that is
# what the harness actually sends — every delegate line in the log names
# "opulent:coder", none a bare "coder". Exact equality, so the twin's own name
# never matches the lane it replaces.
ECO_LANE = "opulent:coder"
ECO_TWIN = "opulent:coder-eco"

_OPERATORS = {";", "|", "||", "&&", "&", "(", ")", ";;", ";&", ";;&"}
_REDIRECTS = {">", ">>", ">|", "&>", "&>>", ">&"}
# `<` feeds a file INTO a command and is never a write target — putting it in
# _REDIRECTS would make `sort < settings.json` look like a rewrite of it. It
# is recognised here only because `patch -p1 < f.patch` names its patch file
# no other way, and because it ends a command's argument list.
_INPUT_REDIRECT = "<"
_CMD_PREFIXES = {"sudo", "command", "time", "env", "xargs", "nice",
                 "timeout", "nohup", "setsid", "stdbuf"}

# Shell reserved words are not commands: `do cp …` runs cp. They are skipped
# WITHOUT leaving command position, which is what lets the writer inside a
# `for`/`if`/`{ }` compound be judged instead of hiding behind the keyword.
_RESERVED = {"if", "then", "elif", "else", "fi", "for", "while", "until",
             "do", "done", "case", "esac", "!", "{", "}"}

# Which of a prefix's own options carry a separate value. Per prefix, because
# the same letter means different things: `nice -n 10` consumes its operand
# and `sudo -n` does not, so one shared table would either swallow the wrapped
# command or leave a stray operand sitting at command position.
_PREFIX_VALUE_OPTS = {
    "sudo": {"-u", "-g", "-p", "-C", "-h", "-r", "-t", "-U", "-R", "-D",
             "--user", "--group", "--chroot", "--chdir", "--prompt",
             "--role", "--type", "--host", "--close-from"},
    "nice": {"-n", "--adjustment"},
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "xargs": {"-I", "-i", "-n", "-P", "-d", "-E", "-L", "-s", "-a",
              "--replace", "--max-args", "--max-procs", "--delimiter",
              "--arg-file"},
    "timeout": {"-k", "-s", "--kill-after", "--signal"},
    "stdbuf": {"-i", "-o", "-e"},
    # /usr/bin/time's options; the bash keyword `time` takes only -p and so
    # never reaches a value option, but the binary spelling does — without
    # this, `-o`'s operand sat at command position and ate the real command.
    "time": {"-o", "-f", "--output", "--format"},
}

# Prefixes that consume a positional operand of their own before the wrapped
# command: `timeout 30 cp …` — the duration is not the command.
_PREFIX_POSITIONALS = {"timeout": 1}

# `cp`/`mv -t DIR src...` — the destination comes FIRST, which makes the usual
# "last operand is the destination" precisely backwards. This is the spelling
# `find -exec` and `xargs` generate, so it arrives by accident.
_TARGET_DIR_OPTS = {"-t", "--target-directory"}

# Options whose value is a separate token and never a source or destination:
# `install -m 755 tool.sh bin/tool.sh` was recording 755 as a source and the
# real destination as a directory to land it in.
_CPMV_VALUE_OPTS = {"-S", "--suffix"}
_INSTALL_VALUE_OPTS = {"-m", "-o", "-g", "-S", "--mode", "--owner", "--group",
                       "--suffix", "--strip-program"}

# touch options whose value is read, never created: `touch -r REF stamp`
# stamps `stamp` with REF's times and writes nothing to REF.
_TOUCH_VALUE_OPTS = {"-r", "--reference", "-d", "--date", "-t"}

# sed options that carry the script; with none present the FIRST bare
# argument IS the script, so `sed -i 's/x/y/' file` edits file alone.
_SED_SCRIPT_OPTS = {"-e", "--expression", "-f", "--file"}

# sed/perl in-place, including GNU's documented long form. The old test was
# `^-\w*i`, which requires `i` to follow word characters after a single dash —
# so `--in-place` (and `--in-place=bak`) failed it and edited settings files
# with no denial and no audit line.
_INPLACE_RE = re.compile(r"^(?:-\w*i|--in-place(?:=|$))")

# A heredoc marker and its delimiter. Guarded on BOTH sides against `<<<`
# so a here-string never matches at any offset, and the delimiter must be
# word-like — `cout <<`, `$((1 << 3))` and `<< "$var"` are shifts, streams
# and strings, not documents, and treating them as openers ate the rest of
# the command.
_HEREDOC_RE = re.compile(
    r"(?<!<)<<(?!<)-?\s*(?:'([A-Za-z_]\w*)'|\"([A-Za-z_]\w*)\"|\\?([A-Za-z_]\w*))")

# Scratch: allowed and NOT logged, because an audit trail of temp files is
# noise that buries the project edits it exists to surface.
_CLAUDE_DIR = os.path.normpath(os.path.join(HOME, ".claude"))
_SCRATCH_DIRS = [
    os.path.normpath(tempfile.gettempdir()),
    os.path.join(_CLAUDE_DIR, "plans"),
    os.path.join(_CLAUDE_DIR, "projects"),
    os.path.join(_CLAUDE_DIR, "todos"),
]

# The control plane, relative to any `.claude` directory — the user's or the
# project's, since both are loaded for the session that is running.
_CONTROL_SUBDIRS = {"hooks", "agents", "commands", "plugins"}
_SETTINGS_RE = re.compile(r"^settings(\.[\w-]+)*\.json$")
# .env templates are committed documentation of shape, not secrets. `.envrc`
# is NOT exempt: direnv executes it as shell.
_ENV_TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")

# Unified-diff header pair. A patch names its targets inside the file, so
# without this the only thing `git apply` and `patch` could be judged on is a
# sentinel, and a sentinel matches no rule at all. Matching the `---`/`+++`
# lines as a *pair* is what keeps a removed line of the form `-- foo` — which
# renders as `--- foo` inside a hunk — from being read as a header.
# One character class per position, and every quantifier bounded. The earlier
# spelling put `([^\t\r\n]+)` directly in front of `[^\r\n]*`: both classes
# accept the same characters, so a long `---` line with no `+++` after it made
# the engine re-split it every possible way. Measured quadratic, projecting to
# HOURS at the read cap below — and reachable by accident, since a removed line
# of the form `-- foo` renders as `--- foo` inside a hunk, so one deleted
# minified line is enough. The tab-suffix that the second class used to eat is
# now cut in _header_path, where it costs nothing.
_PATCH_PAIR_RE = re.compile(
    r"^--- ([^\r\n]{1,4096})\r?\n\+\+\+ ([^\r\n]{1,4096})", re.M)

# The `diff --git a/x b/y` line, which is the ONLY place some patches name
# their targets: a pure rename, a mode-only change and a binary diff all carry
# no `---`/`+++` pair at all, because there is no content hunk to head. Without
# this, `git diff -M` output that moves an existing file into .claude/hooks/
# parses to zero targets and sails through unlogged. Anchored at column 0 so a
# hunk line (which always begins with ' ', '+' or '-') can never pose as one.
# The rest of the line is captured whole because the two names are not always
# separable on whitespace — see _diff_git_paths.
# Bounded and unambiguous for the same reason as the pair above: `(.+?)`
# followed by `[ \t]*` let a run of spaces be divided between the two, and a
# `diff --git` line carrying one blew up identically. Trailing whitespace is
# stripped in code instead.
_PATCH_DIFF_RE = re.compile(r"^diff --git ([^\r\n]{1,4096})$", re.M)

# The two names on that line, when neither of them hides a space. Each side is
# independently either C-quoted — git quotes a name with non-ASCII bytes, and
# quotes each side on its own, so one quoted and one bare is a real shape — or
# a bare run of non-space. Matching only bare runs (`\S+ \S+`) made
# `diff --git "a/my file.py" "b/.claude/hooks/my file.py"` parse to nothing,
# which put a rename into the control plane back out of reach behind nothing
# more than a space in the filename.
_DIFF_GIT_PAIR_RE = re.compile(r'^("(?:\\.|[^"\\])*"|\S+) ("(?:\\.|[^"\\])*"|\S+)$')

# `rename from`/`rename to` and the `-C` copy pair. These name their path
# outright — no a/ or b/ prefix, so no strip level applies to them — and they
# are how git itself reads a rename whose `diff --git` line it cannot split,
# which is any rename of a file whose bare name holds a space. Without them
# `git diff -M` output moving "my file.py" into .claude/hooks/ names its
# destination nowhere this hook can see. Anchored at column 0, where a hunk
# line (always ' ', '+', '-' or '\') can never reach.
_PATCH_RENAME_RE = re.compile(r"^(?:rename|copy) (?:from|to) (.+?)\r?$", re.M)

# The -p strip level, in the spellings that carry it on one token: -p1, the
# clustered -up1, and --strip=1. Without it every header path would be judged
# with its leading a/ or b/ still attached, and the record would name a file
# that does not exist.
_STRIP_RE = re.compile(r"^(?:-[a-zA-Z]*p|--strip=)(\d+)$")

# A patch large enough to blow past this would stall the hook it is meant to
# inform; past the cap the read simply stops and the tail goes unjudged.
_PATCH_READ_LIMIT = 2 * 1024 * 1024

# The doctor's liveness marker: a write it expects to be refused. It has to
# stay refused now that ordinary writes are not, or the probe would report
# enforcement dead the moment this hook started allowing things.
CANARY = "opulent-doctor-canary"


# A dial is read the way a person means it. `os.environ.get(name)` alone is
# truthiness on a string, so OPULENT_OFF=0 and OPULENT_OFF=false — the two
# spellings someone reaches for to mean "leave enforcement ON" — silently
# disabled every denial for the whole session, and OPULENT_ECO=0 turned eco on.
# A dial whose off position is indistinguishable from its on position is not a
# dial.
_OFF_VALUES = {"", "0", "false", "no", "off"}


def dial(name):
    """True when the named session dial is set to something meaning yes."""
    return os.environ.get(name, "").strip().lower() not in _OFF_VALUES


def _beneath(path, prefix):
    return path.startswith(prefix + os.sep) or path.startswith(prefix + "/")


def _under(path, prefix):
    return path == prefix or _beneath(path, prefix)


def _resolve(target, cwd=None):
    """Absolute, normalized path for a write target. No filesystem access:
    normpath rather than realpath, so a backslash cwd and a forward-slash
    target still reconcile on Windows. Surrounding whitespace is stripped
    BEFORE the quotes, so `settings.json ` cannot slide past the basename
    rules on a stray space."""
    t = str(target).strip().strip("\"'")
    if t.startswith("~"):
        t = os.path.expanduser(t)
    if "$HOME" in t:
        t = t.replace("$HOME", HOME)
    # POSIX-literal conventions before normalization: Bash commands write
    # /tmp and /dev/null as strings on every platform (Git Bash included),
    # and Windows normpath would mangle them into \tmp. posixpath.normpath,
    # not a raw return: a `/tmp/x/../guard` spelling must still equal the
    # path it names, or the log's self-guard has a `..`-shaped hole.
    if t.startswith(("/tmp/", "/dev/")) or t in ("/tmp", "/dev/null"):
        return posixpath.normpath(t)
    if not os.path.isabs(t):
        t = os.path.join(os.path.normpath(cwd or os.getcwd()), t)
    return os.path.normpath(t)


def is_control_plane(target, cwd=None):
    """True for files that govern THIS session: anything directly under a
    `.claude` directory's hooks/, agents/, commands/ or plugins/, a
    settings*.json beside them, or any .env file (committed templates like
    .env.example excepted). Everything else — including a plugin's source
    repo, which changes nothing until it is installed — is ordinary code."""
    p = _resolve(target, cwd)
    # Compared case-folded, because the guard has to hold on the platforms the
    # README says it holds on. APFS (the macOS default) and Windows are
    # case-insensitive, so `~/.CLAUDE/hooks/x.py` and `~/.claude/Settings.json`
    # name the very files this protects, and a case-sensitive comparison
    # allowed both. Folding cannot introduce a miss anywhere: the canonical
    # spelling is already lowercase, so every path that matched before still
    # matches. On a case-sensitive filesystem it can over-deny a genuinely
    # different `.CLAUDE` directory — the safe direction, and the denial says
    # which path it objected to.
    base = os.path.basename(p).lower()
    if base.startswith(".env") and not base.endswith(_ENV_TEMPLATE_SUFFIXES):
        return True
    parts = [q.lower() for q in p.replace("\\", "/").split("/")]
    for i, part in enumerate(parts):
        if part != ".claude" or i + 1 >= len(parts):
            continue
        nxt = parts[i + 1]
        if nxt in _CONTROL_SUBDIRS or _SETTINGS_RE.match(nxt):
            return True
    return False


def is_scratch(target, cwd=None):
    p = _resolve(target, cwd)
    if p.startswith(("/tmp/", "/dev/")) or p in ("/tmp", "/dev/null"):
        return True
    return any(_under(p, d) for d in _SCRATCH_DIRS)


def _patch_strip(args):
    """The -p strip level of an invocation, or None when it names none."""
    for a in args:
        m = _STRIP_RE.match(a)
        if m:
            return int(m.group(1))
    return None


def _strip_candidates(path, level):
    """The path(s) a patch header can mean once the strip level is applied.
    -p0 keeps it whole and -p1 drops the leading a/ or b/, which is every
    patch anyone writes. For any other or absent level the tools disagree —
    git apply assumes 1, GNU patch strips to the basename — so rather than
    guess we judge every suffix. Over-reading costs a delegation; under-
    reading costs the guarantee."""
    # `.` components are dropped AFTER the level is applied, never before.
    # Both git and patch count `./` as a component and consume it as the
    # stripped one, so removing it first made -p1 eat the component after it:
    # a `./`-prefixed header naming a control-plane file was judged on the
    # remainder and allowed, and a `./`-prefixed creation produced no
    # candidate at all and went unlogged.
    parts = [p for p in path.replace("\\", "/").split("/") if p]

    def clean(seq):
        return "/".join([p for p in seq if p != "."])

    if level in (0, 1):
        out = clean(parts[level:])
        return [out] if out else []
    # A crafted 2 MiB patch of 2048-component headers measured 14 s in the
    # full suffix fan-out — a stalled hook has failed as surely as a wrong
    # one — so a path deep enough to cost that is judged at the two levels
    # real tools actually use. is_control_plane scans every component, so a
    # `.claude` buried mid-path is still caught at level 0.
    if len(parts) > 64:
        return [c for c in (clean(parts[i:]) for i in (0, 1)) if c]
    return [c for c in (clean(parts[i:]) for i in range(len(parts))) if c]


def _header_path(raw):
    """A `---`/`+++` header's path: everything before the tab a context diff
    uses to carry a timestamp. The regex captures the whole line now — one
    unambiguous class, so it cannot backtrack — and the cut happens here,
    where it is a string operation rather than a second overlapping class."""
    return raw.split("\t", 1)[0]


def _unquote(path):
    """A C-quoted header path with its surrounding quotes taken off. The \\ooo
    escapes inside are left as written: every component is_control_plane reads
    (`.claude`, `hooks`, `settings.json`, a leading `.env`) is ASCII and is
    never escaped, so decoding them would only change how the record prints."""
    if len(path) > 1 and path[0] == '"' and path[-1] == '"':
        return path[1:-1]
    return path


def _diff_git_paths(rest):
    """The two paths on a `diff --git` line, given everything after the marker.

    Whitespace separates them while at most one name hides a space, since a
    spaced name is either C-quoted or the only place a space can be. When both
    are bare and spaced — `diff --git a/my file.py b/.claude/hooks/my file.py`,
    which is verbatim what `git diff -M` emits for that rename — the line
    cannot be split on whitespace at all, and we read it exactly the way the
    tool that will apply it does: git accepts a split only where the two halves
    are the same path, which covers every mode-only and binary change, and for
    anything else falls through to the `rename from`/`rename to` lines
    (_PATCH_RENAME_RE). Guessing a split instead would either invent a target
    or miss one; git's own reading can do neither."""
    m = _DIFF_GIT_PAIR_RE.match(rest)
    if m:
        return [_unquote(m.group(1)), _unquote(m.group(2))]
    # Same path on both sides means halves of the same length under prefixes
    # of the same width, so the only split worth testing is the middle one.
    # Testing it alone is also what keeps a line with a hundred thousand
    # spaces from costing a hundred thousand copies of itself: a hook that
    # stalls the session has failed as surely as one that misreads it.
    k = (len(rest) - 1) // 2
    if len(rest) % 2 and rest[k] == " ":
        left, right = rest[:k], rest[k + 1:]
        if left.split("/", 1)[-1] == right.split("/", 1)[-1]:
            return [left, right]
    return []


def _patch_sources(args, stdin_file, every_positional=False):
    """The patch file(s) an invocation reads, as a list.

    An explicit -i/--input comes first, since it makes the positional beside
    it the file being patched rather than the patch. Otherwise `patch
    [origfile [patchfile]]` names at most one patch and puts it last, and a
    lone positional is the patch in the spelling people actually type — but
    `git apply` is documented `git apply [<patch>...]` and applies EVERY
    positional in order, so for it the whole list is patches. Judging only the
    last would make `git apply evil.patch benign.patch` allowed and the same
    two files in the other order denied: an ordering trick, not a check.

    Over-reading is the safe direction, so a `git apply --directory foo p.patch`
    whose option value looks positional simply gets read as a patch, finds no
    headers, and contributes nothing. Falls back to the `< file` redirect, and
    to nothing at all when the patch arrives on a pipe, which nothing here
    can see."""
    for k, a in enumerate(args):
        if a in ("-i", "--input"):
            return [args[k + 1]] if k + 1 < len(args) else []
        if a.startswith("--input="):
            return [a.split("=", 1)[1]]
    positional = [a for a in args if not a.startswith("-")]
    # The redirect is ALWAYS a candidate, never a fallback. GNU patch is
    # documented `patch [options] [origfile [patchfile]]` and reads the patch
    # from stdin when given one positional — so with `patch -p1 x.py < p.patch`
    # the positional is the file being patched and the redirect is the patch.
    # Consulting the redirect only when no positional existed meant that exact
    # spelling was allowed while the bare `patch -p1 < p.patch` was denied.
    #
    # Over-reading is the safe direction and the docstring above says so: a
    # candidate that is not a patch yields no headers and contributes nothing.
    # So every positional is offered too, for `patch` as much as for git apply,
    # rather than betting on which one is the patch.
    sources = ([stdin_file] if stdin_file else []) + (
        positional if (every_positional or stdin_file) else positional[-1:])
    return [s for i, s in enumerate(sources) if s and s not in sources[:i]]


def _patch_targets(sources, level, cwd, prefix=""):
    """The files the given patches say they write, read out of the patches
    themselves. Every source is read: git applies all of them, so a check that
    stopped at one would leave the rest unseen.

    `prefix` is the directory the tool will apply INTO — `git apply
    --directory=x`, `patch -d x`. Without it the header path was judged on its
    own while the tool wrote somewhere else entirely, so a control-plane
    rewrite was both allowed and recorded under the innocent name the header
    happened to carry.

    Empty when a patch cannot be found, read or parsed: a hook that cannot
    read a patch must not block the session. Nothing here is a barrier —
    a patch piped in (`cat p | git apply`), a context diff, or one written by
    the same command that applies it all sail through. It closes the accident
    of a control-plane rewrite arriving as a patch, not the attack."""
    targets, seen = [], set()

    def add(candidate):
        # Set-backed dedup: the list scan this replaced was O(n) per candidate,
        # and _strip_candidates yields one per path component, so a patch whose
        # header held a deep path cost time quadratic in its own depth.
        if candidate and candidate not in seen:
            seen.add(candidate)
            targets.append(os.path.join(prefix, candidate) if prefix
                           else candidate)

    for source in sources:
        if not source:
            continue
        resolved = _resolve(source, cwd)
        # isfile() before open(): a named pipe blocks in open() until someone
        # writes to it, with no timeout and nothing the size cap can do about
        # it — the hook simply never returns a verdict. One check rejects
        # FIFOs, directories, and device nodes together.
        if not os.path.isfile(resolved):
            continue
        try:
            with open(resolved, errors="replace") as fh:
                text = fh.read(_PATCH_READ_LIMIT)
                if len(text) == _PATCH_READ_LIMIT:
                    # A ---/+++ pair straddling the cap is completed rather
                    # than dropped: two bounded line reads finish the cut
                    # line and its partner, and nothing more is read.
                    text += fh.readline(8192) + fh.readline(8192)
        except OSError:
            continue  # unreadable patch: fail open on this one, judge the rest
        headers = [(_unquote(_header_path(a)), _unquote(_header_path(b)))
                   for a, b in _PATCH_PAIR_RE.findall(text)]
        headers += [_diff_git_paths(rest.rstrip(" \t"))
                    for rest in _PATCH_DIFF_RE.findall(text)]
        for pair in headers:
            for path in pair:
                # /dev/null is a file being created or deleted; the other side
                # of the pair is the one that names it.
                if path == "/dev/null":
                    continue
                for candidate in _strip_candidates(path, level):
                    add(candidate)
        # A rename names both its ends outright, with no a/ or b/ to strip —
        # so these are judged at level 0, and they are the only headers a
        # spaced-name rename leaves that can be read at all.
        for path in _PATCH_RENAME_RE.findall(text):
            for candidate in _strip_candidates(_unquote(path), 0):
                add(candidate)
    return targets


# git's global options that carry their value as a SEPARATE token. Skipping
# the option without its operand is what let `git -C <dir> apply` through: the
# subcommand search took the first token that was neither option-like nor had
# an `=`, which is the directory, decided it was not "apply", and left the
# patch unread — no denial, and no log line either. The `=` spellings never
# had the problem, which is why the bug survived: `--git-dir=x apply` works.
_GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                   "--exec-path", "--config-env", "--super-prefix"}


def _git_subcommand(args):
    """(subcommand, its arguments) for a git invocation, or ("", [])."""
    i = 0
    while i < len(args):
        a = args[i]
        if a in _GIT_VALUE_OPTS:
            i += 2          # the option AND the value it consumes
            continue
        if a.startswith("-"):
            i += 1          # a flag, or an `--opt=value` that eats no token
            continue
        return a, args[i + 1:]
    return "", []


# Where a patch tool will apply INTO, when it is told to apply somewhere other
# than the working directory. `git apply --directory=x`, `patch -d x`.
_DIR_OPTS = {"--directory", "-d"}
# `patch -o FILE` writes its result to FILE rather than to the patched file,
# which makes FILE a write target the headers never mention.
_OUT_OPTS = {"-o", "--output"}


def _opt_value(args, names):
    """The value of the first of `names` present, in either spelling."""
    for k, a in enumerate(args):
        if a in names and k + 1 < len(args):
            return args[k + 1]
        for n in names:
            if a.startswith(n + "="):
                return a.split("=", 1)[1]
    return ""


def _segment_args(tokens, i):
    """Arguments of the command starting at tokens[i], up to the next
    operator or redirect. A `<<`/`<<<` marker and its operand are the
    shell's, not the command's — without the skip, `tee out.txt <<EOF`
    grew phantom `<<`/`EOF` targets, and a path-shaped delimiter that the
    heredoc regex rightly refused to strip became a false deny."""
    args = []
    j = i + 1
    while j < len(tokens) and tokens[j] not in _OPERATORS \
            and tokens[j] not in _REDIRECTS and tokens[j] != _INPUT_REDIRECT:
        if tokens[j] in ("<<", "<<<"):
            j += 2
            continue
        args.append(tokens[j])
        j += 1
    return args


def _drop_opt_values(args, value_opts):
    """args with each value option AND its consumed operand removed, so the
    operand is never mistaken for a source or destination."""
    out, k = [], 0
    while k < len(args):
        if args[k] in value_opts and k + 1 < len(args):
            k += 2
            continue
        out.append(args[k])
        k += 1
    return out


def _redirected_input(tokens, i):
    """The file a `< file` redirect feeds to the command starting at
    tokens[i], or None. The LAST such redirect on the segment, because that is
    the one the shell honours: `patch -p1 < decoy.patch < evil.patch` reads
    evil.patch, and returning the first would judge the decoy and miss the
    content that is actually applied."""
    found = None
    j = i + 1
    while j < len(tokens) and tokens[j] not in _OPERATORS:
        if tokens[j] == _INPUT_REDIRECT and j + 1 < len(tokens):
            found = tokens[j + 1]
            j += 2
            continue
        j += 1
    return found


def _strip_heredocs(cmd):
    """The command with every heredoc BODY (and its terminator line) removed.
    Words inside a document are content, not commands: without this, a
    doc-writing command whose heredoc mentions `> ~/.claude/settings.json`
    was denied, and the log recorded a control-plane denial that never
    happened. The marker line itself is kept, so redirects beside the marker
    — `cat > file <<EOF` and `cat <<EOF > file` alike — are still judged.

    A body is stripped ONLY when its terminator line actually exists. With
    no terminator, nothing is stripped: a false-positive on heredoc-shaped
    prose is the lesser evil against silently unjudging every line after a
    stray `<<` — which is what strip-to-EOF did."""
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\n")
    out = []
    k = 0
    while k < len(lines):
        line = lines[k]
        out.append(line)
        k += 1
        for m in _HEREDOC_RE.finditer(line):
            delim = next((g for g in m.groups() if g is not None), "")
            if not delim:
                continue
            dashed = m.group(0)[2:3] == "-"   # <<- allows tab-indented ends
            end = None
            for j in range(k, len(lines)):
                cand = lines[j].lstrip("\t") if dashed else lines[j]
                if cand == delim:
                    end = j
                    break
            if end is None:
                continue    # unterminated: strip NOTHING
            k = end + 1     # the terminator line is not a command either
    return "\n".join(out)


def bash_write_targets(cmd, cwd=None):
    """What a Bash command does to the filesystem, as a tuple
    (targets, moves, removed, git_destructive, patch_derived, effective_cwd)
    — or None when the command cannot be tokenized at all, so the caller can
    say so instead of silently recording nothing.

    `targets` are file-writes (redirects, tee, sed/perl in-place, cp/mv/
    install/ln/dd/curl -o/wget -O, touch, patch, git apply/am). `moves` are
    (src, dst) pairs so an mv can be recorded as the move it is. `removed`
    are rm's operands; `git_destructive` is true when a git subcommand that
    discards work ran; `patch_derived` holds the targets that came out of a
    patch's headers, so the record can drop their a/-b/ fan-out phantoms
    without touching a real directory named `a/`. Token-based via shlex so
    quoted strings ('a > b' in a commit message) never false-positive.

    A LEADING `cd dir &&`/`;`/newline prefix (repeated, `cd` alone meaning
    HOME) moves `effective_cwd`, which all judgment, patch reading and
    resolution use. Mid-command cd stays unhandled on purpose, and so do
    `set -e; cd …`, `(cd …)` subshells and `cd … || exit`: the bare
    first-segment cd is the accident that actually happens, and tracking
    full shell state is not this hook's job.

    All targets, not just the first: a compound that writes /dev/null and then
    settings.json must not be judged on the harmless half."""
    text = _strip_heredocs(cmd)
    # Newlines separate commands the way `;` does, and are the commonest
    # separator in real Bash tool calls. Substituted as "\n;\n" — keeping
    # the newline — so shlex's own #-comment handling still ends at the
    # line, while the `;` restores command position for the next line.
    # Inside a quoted span this inserts a `;` line into the TOKEN CONTENT
    # (quoted tokens are never parsed further, so nothing downstream reads
    # it); a backslash-continuation is left alone.
    text = re.sub(r"(?<!\\)\n", "\n;\n", text)
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return None
    eff_cwd = cwd
    j = 0
    while j < len(tokens) and tokens[j] == "cd":
        if j + 1 >= len(tokens):
            break                     # trailing bare cd: nothing follows
        nxt = tokens[j + 1]
        if nxt in ("&&", ";"):
            eff_cwd = HOME            # bare `cd` goes home
            j += 2
            continue
        if nxt.startswith("-"):
            break                     # `cd -` or an option: shell state we
                                      # do not model — stop peeling
        if j + 2 < len(tokens) and tokens[j + 2] in ("&&", ";"):
            eff_cwd = _resolve(nxt, eff_cwd)
            j += 3
            continue
        break
    tokens = tokens[j:]
    found, moves, removed, git_rm = [], [], [], []
    patch_derived = set()

    def judge(base, args):
        """Write targets of one simple command, shared with the embedded
        command a `find -exec` generates."""
        paths = [a for a in args if not a.startswith("-")]
        if base == "tee":
            found.extend(paths)          # tee writes EVERY operand
        elif base == "sed":
            # The edited files are the arguments — naming them, rather than
            # a sentinel, is what lets an in-place edit of a settings file
            # be judged as one. The script is a program, not a file.
            if any(_INPLACE_RE.match(a) for a in args):
                consumed, k = set(), 0
                while k < len(args):
                    if args[k] in _SED_SCRIPT_OPTS and k + 1 < len(args):
                        consumed.update((k, k + 1))
                        k += 2
                        continue
                    k += 1
                rest = [a for k2, a in enumerate(args)
                        if k2 not in consumed and not a.startswith("-")]
                if not any(a in _SED_SCRIPT_OPTS or
                           a.startswith(("--expression=", "--file="))
                           for a in args):
                    rest = rest[1:]      # the first bare arg IS the script
                found.extend(rest or ["(in-place edit)"])
        elif base == "perl":
            if any(_INPLACE_RE.match(a) for a in args):
                found.extend(paths or ["(in-place edit)"])
        elif base in ("cp", "mv", "install"):
            # install shares cp's accident shape: -t, and a positional
            # destination that is a directory. Option values (-S suffix,
            # install's -m/-o/-g/…) are dropped first so a mode or owner is
            # never read as a source.
            opts = _INSTALL_VALUE_OPTS if base == "install" else _CPMV_VALUE_OPTS
            paths = [a for a in _drop_opt_values(args, opts)
                     if not a.startswith("-")]
            if base == "install" and ("-d" in args or "--directory" in args):
                found.extend(paths)      # install -d CREATES its operands
                return
            tdir = _opt_value(args, _TARGET_DIR_OPTS)
            if tdir:
                srcs = [p for p in paths if p != tdir]
                if not srcs:
                    # xargs/find feed the sources on stdin, so the -t
                    # directory itself is the visible half of the write.
                    found.append(tdir)
                for p in srcs:
                    dest = os.path.join(tdir, os.path.basename(p))
                    found.append(dest)
                    if base == "mv":
                        moves.append((p, dest))
            elif len(paths) >= 2:
                dest, srcs = paths[-1], paths[:-1]
                # A destination that is a directory lands dir/basename(src):
                # by trailing slash, by what the filesystem says, or by
                # arity (three or more operands can only mean a directory).
                if (dest.endswith(("/", os.sep)) or len(paths) >= 3
                        or os.path.isdir(_resolve(dest, eff_cwd))):
                    for p in srcs:
                        d = os.path.join(dest, os.path.basename(p))
                        found.append(d)
                        if base == "mv":
                            moves.append((p, d))
                else:
                    found.append(dest)
                    if base == "mv":
                        moves.append((srcs[-1], dest))
        elif base == "ln":
            # `.`/empty operands are dropped: `ln -s ../x.py .` was
            # recording the whole cwd as an edit.
            tdir = _opt_value(args, _TARGET_DIR_OPTS)
            ops = [p for p in paths if p not in (".", "") and p != tdir]
            if tdir:
                if ops:
                    found.extend(os.path.join(tdir, os.path.basename(p))
                                 for p in ops)
                else:
                    found.append(tdir)
            elif len(ops) >= 2:
                found.append(ops[-1])    # the link name being created
        elif base == "dd":
            found.extend(a[3:] for a in args
                         if a.startswith("of=") and a[3:])
        elif base == "curl":
            # -o FILE only. Known limit: `curl -O` derives its filename
            # from the URL, which nothing here can name.
            out = _opt_value(args, {"-o", "--output"})
            if out:
                found.append(out)
        elif base == "wget":
            out = _opt_value(args, {"-O", "--output-document"})
            if out:
                found.append(out)
        elif base == "touch":
            # -r/-d/-t values are read, never created.
            skip, k = set(), 0
            while k < len(args):
                if args[k] in _TOUCH_VALUE_OPTS and k + 1 < len(args):
                    skip.add(k + 1)
                    k += 2
                    continue
                k += 1
            found.extend(a for k2, a in enumerate(args)
                         if k2 not in skip and not a.startswith("-"))
        elif base == "rm":
            removed.extend(paths)
        elif base == "find":
            # find generates the very command shapes the -t comment names.
            # patch/git are skipped in embedded position: they name their
            # input via redirects, which cannot appear inside -exec.
            # tar/unzip/rsync stay out everywhere: archive and remote
            # semantics name no plain target worth a guess.
            for k, a in enumerate(args):
                if a in ("-exec", "-execdir", "-ok", "-okdir"):
                    emb = [x for x in args[k + 1:] if x != "+"]
                    if emb:
                        judge(emb[0].rsplit("/", 1)[-1], emb[1:])
                    break

    cmdpos = True
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _OPERATORS:
            cmdpos = True
            i += 1
            continue
        if tok == "<<":
            i += 2  # the body is already stripped; skip the delimiter word
            continue
        if tok == _INPUT_REDIRECT:
            i += 2  # its operand is an input, never a target
            continue
        if tok in _REDIRECTS:
            if i + 1 < len(tokens):
                target = tokens[i + 1]
                # fd duplication (2>&1, >&2, >&-) names no file.
                if not target.startswith("&") and not (
                        tok == ">&" and (target.isdigit() or target == "-")):
                    found.append(target)
            i += 2
            continue
        if cmdpos:
            if tok in _RESERVED:
                i += 1
                continue    # still at command position: `do cp …` runs cp
            base = tok.rsplit("/", 1)[-1]
            if base in _CMD_PREFIXES or ("=" in tok and not tok.startswith("-")):
                i += 1
                # A prefix's own flags belong to the prefix, not to the command
                # it wraps. Without this, `sudo cp ...` was denied while
                # `sudo -u root cp ...` was allowed and unlogged: `-u` fell
                # through, cmdpos went false, and the `cp` behind it was never
                # examined. Not an exotic utility — the same utility, with an
                # option.
                vals = _PREFIX_VALUE_OPTS.get(base, set())
                while i < len(tokens) and tokens[i].startswith("-"):
                    i += 2 if (tokens[i] in vals and i + 1 < len(tokens)) else 1
                # timeout's duration is a positional of the prefix, not the
                # wrapped command.
                extra = _PREFIX_POSITIONALS.get(base, 0)
                while extra > 0 and i < len(tokens) \
                        and tokens[i] not in _OPERATORS \
                        and tokens[i] not in _REDIRECTS \
                        and tokens[i] != _INPUT_REDIRECT:
                    i += 1
                    extra -= 1
                continue  # still at command position
            args = _segment_args(tokens, i)
            if base == "patch":
                pt = _patch_targets(
                    _patch_sources(args, _redirected_input(tokens, i)),
                    _patch_strip(args), eff_cwd,
                    prefix=_opt_value(args, _DIR_OPTS))
                found.extend(pt)
                patch_derived.update(pt)
                # -o redirects the result to a file the headers never name.
                out = _opt_value(args, _OUT_OPTS)
                if out:
                    found.append(out)
            elif base == "git":
                sub, tail = _git_subcommand(args)
                if sub in ("apply", "am"):
                    # every_positional: `git apply a.patch b.patch` applies
                    # both. `am` is apply for format-patch output — the
                    # mailbox framing changes nothing about the ---/+++
                    # headers this reads. git documents -p1 as the default
                    # for both, so an absent level is 1, not a fan-out.
                    lvl = _patch_strip(tail)
                    pt = _patch_targets(
                        _patch_sources(tail, _redirected_input(tokens, i),
                                       every_positional=True),
                        1 if lvl is None else lvl, eff_cwd,
                        prefix=_opt_value(tail, _DIR_OPTS))
                    found.extend(pt)
                    patch_derived.update(pt)
                elif ((sub == "clean"
                        and not {"-n", "--dry-run"} & set(tail))
                        or (sub == "restore"
                            and not ("--staged" in tail
                                     and "--worktree" not in tail))
                        or (sub == "reset" and "--hard" in tail)
                        or (sub == "checkout" and "--" in tail)
                        or (sub == "stash" and tail[:1] == ["drop"])):
                    # The subcommands that discard work. Recorded, not
                    # denied: the record was silent on precisely the
                    # hardest-to-undo operations. A clean dry-run and a
                    # --staged-only restore discard nothing.
                    git_rm.append(sub)
            else:
                judge(base, args)
        cmdpos = False
        i += 1
    return found, moves, removed, bool(git_rm), patch_derived, eff_cwd


CONTROL_PLANE_DENIAL = (
    "Routing policy: %s is the control plane — a .claude directory's "
    "settings, hooks, agents, commands or plugins (the user's or the "
    "project's), or a .env. Changing what governs sessions stays delegated, "
    "so every rules change leaves a record: hand it to 'opulent:coder' or "
    "'opulent:mechanic'. A plugin's source repo is not the control plane "
    "and needs no delegation.")

LOG_DENIAL = (
    "Routing policy: %s is this session's routing log — the audit record "
    "itself. The main loop never rewrites or deletes it; resetting it is "
    "the user's call, and safe for the user to do between sessions.")


def main():
    global _SID
    payload = json.load(sys.stdin)

    if dial("OPULENT_OFF"):
        allow()

    if payload.get("agent_id"):  # inside a subagent: everything allowed
        allow()

    _SID = str(payload.get("session_id") or "")[:8]

    tool = payload.get("tool_name", "")
    tin = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()

    if tool in ("Task", "Agent"):
        st = tin.get("subagent_type") or ""
        if st == "Explore":
            # Plugin agents can't shadow built-ins, so redirect instead
            deny("Routing policy: for exploration use the 'opulent:scout' agent "
                 "(Haiku) instead of the built-in Explore agent.",
                 "redirect:Explore")
        if st in CATCHALL_AGENTS:
            deny("Routing policy: catch-all agents inherit the session model and "
                 "bypass lane routing. Delegate to an opulent lane "
                 "(opulent:coder, opulent:mechanic, opulent:test-runner, "
                 "opulent:scribe, opulent:scout, ...) or another purpose-defined "
                 "agent instead.", "catchall:" + st)
        if dial("OPULENT_ECO") and st == ECO_LANE:
            # One-way: the twin is spawnable whether or not eco is set, because
            # voluntarily spending less is never a routing violation.
            # Logged as its own event, not as "deny": an eco redirect is the
            # dial working as asked, and counting it as a denial would inflate
            # the number the doctor reports — the same reason `probe` exists.
            deny("Routing policy: eco mode is on for this session (OPULENT_ECO), "
                 "so complex implementation runs one effort rung down — spawn "
                 "the '%s' agent instead of '%s'. Same model and same charter; "
                 "effort xhigh rather than max." % (ECO_TWIN, ECO_LANE),
                 "eco:coder", event="eco")
        _log("delegate", st)
        allow()

    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        path = tin.get("file_path") or tin.get("notebook_path") or ""
        if not path:
            allow()  # no path: nothing to judge, and nothing worth a line
        p = _resolve(path, cwd)
        if is_control_plane(p, cwd):
            deny(CONTROL_PLANE_DENIAL % p, "control:" + p)
        if _LOG_GUARDED and p == _LOG_NORM:
            deny(LOG_DENIAL % p, "log:" + p)
        if is_scratch(p, cwd):
            allow()
        allow("edit", p)

    if tool == "Bash":
        cmd = tin.get("command", "")
        parsed = bash_write_targets(cmd, cwd)
        if parsed is None:
            # An unbalanced quote must not silently blind the record: one
            # line says the parser saw nothing, and the test check still
            # runs against the raw text.
            _log("unparsed", cmd[:80])
            if TEST_RE.search(cmd):
                _log("test", cmd[:80])
            allow()
        targets, moves, removed, git_rm, patch_derived, eff_cwd = parsed
        # The sed sentinel is a marker, not a path — resolving it painted it
        # under the cwd in the record.
        pairs = [(t, t if t == "(in-place edit)" else _resolve(t, eff_cwd))
                 for t in targets]
        for t, rp in pairs:
            if os.path.basename(rp) == CANARY:
                deny("Routing policy: the /opulent:doctor canary (%s), denied on "
                     "purpose — enforcement is live and nothing was written."
                     % CANARY, "canary:" + rp, event="probe")
            if _LOG_GUARDED and rp == _LOG_NORM:
                deny(LOG_DENIAL % rp, "log:" + rp)
            if is_control_plane(rp, eff_cwd):
                deny(CONTROL_PLANE_DENIAL % rp, "control:" + rp)
        rm_pairs = [(p, _resolve(p, eff_cwd)) for p in removed]
        for p, rp in rm_pairs:
            if _LOG_GUARDED and rp == _LOG_NORM:
                deny(LOG_DENIAL % rp, "log:" + rp)
        # The record, after judgment: scratch stays out, an mv is shown as
        # the move it is, `{}` operands are find's placeholder rather than a
        # path, and a patch fan-out's a/- and b/-prefixed spellings are
        # dropped once their stripped sibling is present — phantoms in the
        # detail were crowding out the real names. Patch-derived only: a
        # real directory named a/ is not a phantom.
        tset = set(targets)
        # Known limit: keyed by destination string, so an earlier cp that
        # shares an mv's destination would borrow its arrow.
        mv_src = dict((d, s) for s, d in moves)
        shown = []
        for t, rp in pairs:
            s = str(t).replace("\\", "/")
            if t in patch_derived and s[:2] in ("a/", "b/") and s[2:] in tset:
                continue
            if "{}" in s:
                continue
            if is_scratch(rp, eff_cwd):
                continue
            if t in mv_src:
                shown.append("%s -> %s" % (_resolve(mv_src[t], eff_cwd), rp))
            else:
                shown.append(rp)
        if shown:
            _log("edit", ", ".join(shown))
        kept_rm = [rp for p, rp in rm_pairs
                   if "{}" not in str(p) and not is_scratch(rp, eff_cwd)]
        if kept_rm:
            _log("remove", ", ".join(kept_rm))
        if git_rm:
            _log("remove", cmd[:80])
        probe = _COMMENT_RE.sub(" ", _QUOTED_RE.sub(" ", _strip_heredocs(cmd)))
        if TEST_RE.search(probe):
            _log("test", cmd[:80])
        allow()

    allow()


try:
    main()
except SystemExit:
    raise
except Exception:
    allow()
