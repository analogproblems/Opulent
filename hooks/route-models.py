#!/usr/bin/env python3
"""PreToolUse hook: guard the control plane, log what the main loop does,
and keep delegation pointed at real lanes. Subagent calls (payload contains
agent_id) are always allowed. Fail-open: any parse error or unexpected
payload shape allows the call. This is a seatbelt with an audit trail, not a
security boundary — see the README's "What enforcement is — and isn't".

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
Telemetry: main-loop edits, test runs, delegations and denials each append one
JSON line to ~/.claude/opulent-log.jsonl (override path with OPULENT_LOG)."""
import datetime
import json
import os
import re
import shlex
import sys
import tempfile

HOME = os.path.expanduser("~")
LOG_PATH = os.environ.get("OPULENT_LOG") or os.path.join(HOME, ".claude", "opulent-log.jsonl")


def _log(event, detail):
    try:
        with open(LOG_PATH, "a") as f:
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            f.write(json.dumps({"t": ts, "event": event, "detail": str(detail)[:120]}) + "\n")
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
TEST_RE = re.compile(
    r"(?:^|[;&|(]\s*|\bthen\s+|\bdo\s+)"          # command position
    r"(?:\w+=\S*\s+)*"                             # env-var prefixes: CI=1 ...
    r"(?:sudo\s+|command\s+|time\s+|npx\s+|bunx\s+|uv\s+run\s+|python3?\s+-m\s+)*"
    r"(?:[\w@./-]*/)?"                             # path prefixes: ./gradlew
    r"(?:pytest|vitest|jest|playwright\s+test|cargo\s+(?:test|nextest)|go\s+test|"
    r"bun\s+test|phpunit|rspec|tox|ctest|dotnet\s+test|mvn\s+(?:test|verify)|"
    r"gradlew?\s+test|(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|lint|typecheck|build)(?![\w-])|"
    r"make\s+(?:test|check)(?![\w-])|tsc|eslint|ruff|mypy)\b",
    re.M)

# `tsc --version` is a lookup, not a build — not worth an audit line.
VERSION_RE = re.compile(r"\s--(?:version|help)\b")

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

_OPERATORS = {";", "|", "||", "&&", "&", "(", ")"}
_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}
# `<` feeds a file INTO a command and is never a write target — putting it in
# _REDIRECTS would make `sort < settings.json` look like a rewrite of it. It
# is recognised here only because `patch -p1 < f.patch` names its patch file
# no other way, and because it ends a command's argument list.
_INPUT_REDIRECT = "<"
_CMD_PREFIXES = {"sudo", "command", "time", "env", "xargs", "nice"}

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

# Unified-diff header pair. A patch names its targets inside the file, so
# without this the only thing `git apply` and `patch` could be judged on is a
# sentinel, and a sentinel matches no rule at all. Matching the `---`/`+++`
# lines as a *pair* is what keeps a removed line of the form `-- foo` — which
# renders as `--- foo` inside a hunk — from being read as a header.
_PATCH_PAIR_RE = re.compile(r"^--- ([^\t\r\n]+)[^\r\n]*\r?\n\+\+\+ ([^\t\r\n]+)", re.M)

# The `diff --git a/x b/y` line, which is the ONLY place some patches name
# their targets: a pure rename, a mode-only change and a binary diff all carry
# no `---`/`+++` pair at all, because there is no content hunk to head. Without
# this, `git diff -M` output that moves an existing file into .claude/hooks/
# parses to zero targets and sails through unlogged. Anchored at column 0 so a
# hunk line (which always begins with ' ', '+' or '-') can never pose as one.
# The rest of the line is captured whole because the two names are not always
# separable on whitespace — see _diff_git_paths.
_PATCH_DIFF_RE = re.compile(r"^diff --git (.+?)[ \t]*\r?$", re.M)

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


def _beneath(path, prefix):
    return path.startswith(prefix + os.sep) or path.startswith(prefix + "/")


def _under(path, prefix):
    return path == prefix or _beneath(path, prefix)


def _resolve(target, cwd=None):
    """Absolute, normalized path for a write target. No filesystem access:
    normpath rather than realpath, so a backslash cwd and a forward-slash
    target still reconcile on Windows."""
    t = str(target).strip("\"'")
    if t.startswith("~"):
        t = os.path.expanduser(t)
    if "$HOME" in t:
        t = t.replace("$HOME", HOME)
    # POSIX-literal conventions before normalization: Bash commands write
    # /tmp and /dev/null as strings on every platform (Git Bash included),
    # and Windows normpath would mangle them into \tmp.
    if t.startswith(("/tmp/", "/dev/")) or t in ("/tmp", "/dev/null"):
        return t
    if not os.path.isabs(t):
        t = os.path.join(os.path.normpath(cwd or os.getcwd()), t)
    return os.path.normpath(t)


def is_control_plane(target, cwd=None):
    """True for files that govern THIS session: anything directly under a
    `.claude` directory's hooks/, agents/, commands/ or plugins/, a
    settings*.json beside them, or any .env file. Everything else — including
    a plugin's source repo, which changes nothing until it is installed — is
    ordinary code."""
    p = _resolve(target, cwd)
    if os.path.basename(p).startswith(".env"):
        return True
    parts = p.replace("\\", "/").split("/")
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
    parts = [p for p in path.replace("\\", "/").split("/") if p and p != "."]
    if level == 0:
        return ["/".join(parts)] if parts else []
    if level == 1:
        return ["/".join(parts[1:])] if len(parts) > 1 else []
    return ["/".join(parts[i:]) for i in range(len(parts))]


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
    if positional:
        return positional if every_positional else positional[-1:]
    return [stdin_file] if stdin_file else []


def _patch_targets(sources, level, cwd):
    """The files the given patches say they write, read out of the patches
    themselves. Every source is read: git applies all of them, so a check that
    stopped at one would leave the rest unseen.

    Empty when a patch cannot be found, read or parsed: a hook that cannot
    read a patch must not block the session. Nothing here is a barrier —
    a patch piped in (`cat p | git apply`), a context diff, or one written by
    the same command that applies it all sail through. It closes the accident
    of a control-plane rewrite arriving as a patch, not the attack."""
    targets = []
    for source in sources:
        if not source:
            continue
        try:
            with open(_resolve(source, cwd), errors="replace") as fh:
                text = fh.read(_PATCH_READ_LIMIT)
        except OSError:
            continue  # unreadable patch: fail open on this one, judge the rest
        headers = list(_PATCH_PAIR_RE.findall(text))
        headers += [_diff_git_paths(rest) for rest in _PATCH_DIFF_RE.findall(text)]
        for pair in headers:
            for path in pair:
                # /dev/null is a file being created or deleted; the other side
                # of the pair is the one that names it.
                if path == "/dev/null":
                    continue
                for candidate in _strip_candidates(path, level):
                    if candidate not in targets:
                        targets.append(candidate)
        # A rename names both its ends outright, with no a/ or b/ to strip —
        # so these are judged at level 0, and they are the only headers a
        # spaced-name rename leaves that can be read at all.
        for path in _PATCH_RENAME_RE.findall(text):
            for candidate in _strip_candidates(_unquote(path), 0):
                if candidate not in targets:
                    targets.append(candidate)
    return targets


def _segment_args(tokens, i):
    """Arguments of the command starting at tokens[i], up to the next
    operator or redirect."""
    args = []
    j = i + 1
    while j < len(tokens) and tokens[j] not in _OPERATORS \
            and tokens[j] not in _REDIRECTS and tokens[j] != _INPUT_REDIRECT:
        args.append(tokens[j])
        j += 1
    return args


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


def bash_write_targets(cmd, cwd=None):
    """Every file-write a Bash command performs (redirects, tee, sed/perl
    in-place, cp/mv/touch, patch, git apply), as a list of targets. Token-based
    via shlex so quoted strings ('a > b' in a commit message) never
    false-positive. Fails open — an unparseable command yields nothing.

    `patch` and `git apply` name no target on the command line, so cwd is
    needed to find the patch file and read the targets out of it.

    All targets, not just the first: a compound that writes /dev/null and then
    settings.json must not be judged on the harmless half."""
    try:
        lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        return []
    found = []
    cmdpos = True
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _OPERATORS:
            cmdpos = True
            i += 1
            continue
        if tok == _INPUT_REDIRECT:
            i += 2  # its operand is an input, never a target
            continue
        if tok in _REDIRECTS:
            if i + 1 < len(tokens):
                target = tokens[i + 1]
                if not target.startswith("&"):
                    found.append(target)
            i += 2
            continue
        if cmdpos:
            base = tok.rsplit("/", 1)[-1]
            if base in _CMD_PREFIXES or ("=" in tok and not tok.startswith("-")):
                i += 1
                continue  # still at command position
            args = _segment_args(tokens, i)
            paths = [a for a in args if not a.startswith("-")]
            if base == "tee":
                found.extend(paths[:1])
            elif base in ("sed", "perl"):
                # The edited files are the arguments — naming them, rather than
                # a sentinel, is what lets an in-place edit of a settings file
                # be judged as one.
                if any(re.match(r"^-\w*i", a) for a in args):
                    found.extend(paths or ["(in-place edit)"])
            elif base in ("cp", "mv"):
                if len(paths) >= 2:
                    found.append(paths[-1])
            elif base == "touch":
                found.extend(paths[:1])
            elif base == "patch":
                found.extend(_patch_targets(
                    _patch_sources(args, _redirected_input(tokens, i)),
                    _patch_strip(args), cwd))
            elif base == "git":
                sub = next((a for a in args
                            if not a.startswith("-") and "=" not in a), "")
                if sub == "apply":
                    tail = args[args.index(sub) + 1:]
                    # every_positional: `git apply a.patch b.patch` applies both.
                    found.extend(_patch_targets(
                        _patch_sources(tail, _redirected_input(tokens, i),
                                       every_positional=True),
                        _patch_strip(tail), cwd))
        cmdpos = False
        i += 1
    return found


CONTROL_PLANE_DENIAL = (
    "Routing policy: %s is the control plane — settings, hooks, agent and "
    "command definitions, the installed plugin tree, or a .env. Changing what "
    "governs this session stays delegated, so every rules change leaves a "
    "record: hand it to 'opulent:coder' or 'opulent:mechanic'. A plugin's "
    "source repo is not the control plane and needs no delegation.")


def main():
    payload = json.load(sys.stdin)

    if os.environ.get("OPULENT_OFF"):
        allow()

    if payload.get("agent_id"):  # inside a subagent: everything allowed
        allow()

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
        if os.environ.get("OPULENT_ECO") and st == ECO_LANE:
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
        if is_control_plane(path, cwd):
            deny(CONTROL_PLANE_DENIAL % path, "control:" + str(path))
        if is_scratch(path, cwd):
            allow()
        allow("edit", str(path))

    if tool == "Bash":
        cmd = tin.get("command", "")
        targets = bash_write_targets(cmd, cwd)
        for t in targets:
            if os.path.basename(str(t)) == CANARY:
                deny("Routing policy: the /opulent:doctor canary (%s), denied on "
                     "purpose — enforcement is live and nothing was written."
                     % CANARY, "canary:" + str(t), event="probe")
            if is_control_plane(t, cwd):
                deny(CONTROL_PLANE_DENIAL % t, "control:" + str(t))
        written = [t for t in targets if not is_scratch(t, cwd)]
        if written:
            allow("edit", ", ".join(str(t) for t in written)[:120])
        if TEST_RE.search(cmd) and not VERSION_RE.search(cmd):
            allow("test", cmd[:80])

    allow()


try:
    main()
except SystemExit:
    raise
except Exception:
    allow()
