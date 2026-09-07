#!/usr/bin/env python3
"""Self-test for hooks/route-models.py — feeds payloads via stdin,
checks allow (exit 0, no output) vs deny (JSON with permissionDecision=deny).

The hook does a different job on each of its two events: PreToolUse DECIDES
and PostToolUse RECORDS. The two tables below are split the same way. CASES,
the decision table, sends payloads carrying NO hook_event_name at all — which
is deliberate, and pins the hook's fail-toward-the-safer-branch rule: an event
name it does not recognise is judged, never recorded. TELEMETRY, the record
table, wraps every payload in post() or pre() so each row says out loud which
half of the call it is about.

Fixtures are built with os.path.join / tempfile so this suite tests the
platform it runs on (the old fixtures hardcoded forward slashes and could
not disagree with the code on Windows), and every path concatenated into a
Bash command goes through q() — see its docstring for the 86 Windows failures
that came of spelling one bare.

Since 0.24.0 this suite runs on Linux, Windows and macOS in CI. Before that it
ran on ubuntu-latest alone and scored 239/328 the first time anyone tried it
on Windows, so a green run here used to say nothing about two of the three
platforms Claude Code runs on.

Telemetry cases assert the log's event list by EQUALITY, not membership: a
hook that fabricates an extra event on every allow, or renames one event to
another, must fail here — membership checks were proven blind to both."""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# These scripts print em dashes, arrows and the odd accented fixture, and the
# console they print to is not always UTF-8: a Windows terminal defaults to
# cp1252, where an unencodable character raises UnicodeEncodeError and takes
# the whole run with it — a suite that dies over a dash has told you nothing
# about the code. errors="replace" so a console that truly cannot render a
# character prints a placeholder instead of failing. Guarded, because
# reconfigure() arrived in 3.7 and a wrapped stdout may not have it at all.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# Overridable so the suite can be pointed at an OLD copy of the hook and
# watched to fail. A guard case that has never failed is a guard case nobody
# has checked — and 71 of the 120 cases this suite had in 2026-08 were
# satisfied by a hook that did nothing at all.
HOOK = os.environ.get("ROUTE_HOOK_PATH") or str(
    Path(__file__).resolve().parent.parent / "hooks" / "route-models.py")
HOME = os.path.expanduser("~")
TMP = tempfile.gettempdir()

# Patch fixtures are written to disk because the hook opens and reads them;
# a string mock of a patch would exercise none of that.
PATCH_DIR = tempfile.mkdtemp(prefix="opulent-selftest-")
atexit.register(shutil.rmtree, PATCH_DIR, True)


def q(path):
    """A path as a Bash command would have to spell it, in double quotes.

    The fixtures used to concatenate paths bare, which on Windows asked the
    hook to see a path Bash itself would never hand it: under POSIX rules an
    unquoted backslash escapes the next character, so
    `C:\\Users\\x\\.claude\\settings.json` arrives at the command as
    `C:Usersx.claudesettings.json` — a relative path naming nothing. 86 of
    this suite's 328 cases were green on Linux and failed here for that one
    reason, and the hook was right every time: Bash strips those backslashes
    too, so such a command cannot reach the control plane. The fixtures are
    what had to change. A path that ENDS in a backslash gets that one doubled,
    because inside double quotes `\\\\` is a literal backslash while a lone
    trailing `\\` would escape the closing quote and swallow the rest of the
    command."""
    trailing = len(path) - len(path.rstrip("\\"))
    return '"' + path + "\\" * trailing + '"'


def patch_file(name, body):
    p = os.path.join(PATCH_DIR, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)
    return p


def run(payload, env_extra=None, field="permissionDecision"):
    """The hook's verdict for one payload. `field` picks which part of a
    denial comes back — the decision by default, or the reason text, which is
    the only way to check that a redirect names the lane it redirects to."""
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    env = dict(os.environ, OPULENT_LOG=os.devnull)
    # The dials retired in 0.15.0 are cleared anyway, so a shell that still
    # exports one cannot make this suite pass for a reason the rows do not
    # state. The retirement itself is asserted in the rows below.
    for _retired in ("OPULENT_OFF", "OPULENT_ECO", "OPULENT_CODEX"):
        env.pop(_retired, None)
    # And CLAUDE_PROJECT_DIR, which is not retired but inherited: since 0.25.0
    # the hook looks for `<project>/.claude/pr-lane.json` there, so a suite run
    # from inside a project that HAS opted in would append this suite's
    # fixtures to that project's real ledger. The pr-lane rows below set it
    # explicitly, to a throwaway directory.
    env.pop("CLAUDE_PROJECT_DIR", None)
    if env_extra:
        env.update(env_extra)
    try:
        # A hook that hangs has failed: pointed at the 0.11.1 hook, a suite
        # with no timeout spun forever on the FIFO case (its ERROR() could
        # never fire). TIMEOUT matches no expectation, so it always fails.
        # encoding pinned so the verdict does not depend on the console's
        # code page: a HOME with a non-ASCII character otherwise comes back
        # from the hook decoded one way here and compared against a path
        # spelled another, and the row fails for a reason that is not the
        # hook's. The payload itself is ASCII (json.dumps escapes), so the
        # bytes on stdin are identical either way.
        p = subprocess.run([sys.executable, HOOK], input=raw,
                           capture_output=True, text=True, encoding="utf-8",
                           env=env, timeout=20)
    except subprocess.TimeoutExpired:
        return "TIMEOUT(hook hung past 20s)"
    if p.returncode != 0:
        return f"ERROR(exit={p.returncode}, stderr={p.stderr.strip()})"
    out = p.stdout.strip()
    if not out:
        return "allow"
    try:
        d = json.loads(out)["hookSpecificOutput"]
    except Exception:
        return f"ERROR(bad output: {out!r})"
    # The discriminator, asserted on every case that produces output. Without
    # this the suite read `permissionDecision` and never the key that tells the
    # consumer which event the decision is even about: corrupting or deleting
    # `hookEventName` left all 120 cases green while turning every denial in
    # the plugin into output nothing has a reason to apply. Two lines, and they
    # cover all deny cases at once.
    if d.get("hookEventName") != "PreToolUse":
        return f"ERROR(hookEventName={d.get('hookEventName')!r})"
    if field not in d:
        # Deliberately quotes nothing of the payload: an error string that
        # embedded the output would carry the reason text inside it, and a
        # `want_text in reason` check would pass on a hook whose output key
        # was misspelled — an assertion satisfied by its own failure message.
        return f"ERROR(missing {field})"
    return d[field]


def bash(cmd, agent=None, cwd=None, sid=None):
    d = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    if agent:
        d["agent_id"] = agent
    if cwd:
        d["cwd"] = cwd
    if sid:
        d["session_id"] = sid
    return d


def edit(tool, path, agent=None, cwd=None, sid=None):
    d = {"tool_name": tool, "tool_input": {"file_path": path}}
    if agent:
        d["agent_id"] = agent
    if cwd:
        d["cwd"] = cwd
    if sid:
        d["session_id"] = sid
    return d


def powershell(cmd, agent=None, cwd=None, sid=None):
    """A PowerShell tool call — the shape the harness sends on Windows, where
    PowerShell is the primary shell. Until 0.24.0 hooks.json did not match the
    tool and the hook did not dispatch it, so every write it performed was
    neither decided on nor recorded."""
    d = {"tool_name": "PowerShell", "tool_input": {"command": cmd}}
    if agent:
        d["agent_id"] = agent
    if cwd:
        d["cwd"] = cwd
    if sid:
        d["session_id"] = sid
    return d


def task(subagent, agent=None, sid=None):
    d = {"tool_name": "Task", "tool_input": {"subagent_type": subagent}}
    if agent:
        d["agent_id"] = agent
    if sid:
        d["session_id"] = sid
    return d


def post(payload):
    """The same call delivered on the event that RECORDS it. PostToolUse fires
    only once the tool has succeeded, which is the whole reason the log lives
    there: a line written at PreToolUse records an ATTEMPT, and any other
    plugin's hook on that same event is still free to deny the call, leaving a
    phantom behind. Every row asserting a log line therefore arrives here."""
    d = dict(payload)
    d["hook_event_name"] = "PostToolUse"
    # The real payload carries the tool's own result on this event. Nothing in
    # the hook reads it; it is here so the fixture is the shape the harness
    # actually sends, rather than a PreToolUse payload wearing a new name.
    d.setdefault("tool_response", {"success": True})
    return d


def pre(payload):
    """The same call on the event that DECIDES it. Spelled out rather than left
    implicit, so pre and post sit side by side in the record table and neither
    reads as the default the other is an exception to."""
    d = dict(payload)
    d["hook_event_name"] = "PreToolUse"
    return d


PROJ = os.path.join(HOME, "project", "x.py")
# Session cwd, supplied the way the real payload does it (top-level "cwd").
CWD = os.path.join(HOME, "project")
# A plugin's source repo — ordinary code that changes nothing until it is
# installed. Deliberately NOT the control plane; see route-models.py.
SRC = os.path.join(HOME, "Claude", "Fabeulous")
HOOKS_DIR = os.path.join(HOME, ".claude", "hooks")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
# CLAUDE_PLUGIN_DATA: a plugin's own persistent state, written BY hooks rather
# than read by them as rules. It lives inside plugins/, which is otherwise all
# control plane, so it is the one carve-out in there.
PLUGIN_DATA = os.path.join(HOME, ".claude", "plugins", "data", "hookkit", "state.json")
# A sibling plugin's hook config, sitting directly under .claude the way
# settings.json does and deciding as surely as it does whether a gate runs.
HOOKKIT = os.path.join(HOME, ".claude", "hookkit.json")
# The pr-lane pair, and the asymmetry is the point: the config is control
# plane, the ledger beside it is a record the main loop appends to.
PRLANE_CONFIG = os.path.join(HOME, ".claude", "pr-lane.json")
PRLANE_LEDGER = os.path.join(HOME, ".claude", "pr-lane", "ledger.jsonl")

# Windows path spellings, written as literals rather than built with
# os.path.join, because the point of each is the SPELLING and not the platform
# this suite happens to run on. All three rows below run everywhere:
# is_control_plane reads path segments, so a `.claude/hooks` component is
# judged the same on Linux, macOS and Windows.
WIN_UNQUOTED = r"C:\Users\x\.claude\settings.json"
WIN_HOOK = r"C:\Users\x\.claude\hooks\y.py"
WIN_AGENT = r"C:\Users\x\.claude\agents\y.md"
# MSYS's drive spelling: in Git Bash on Windows `/c/Users/x` IS `C:\Users\x`,
# and it is the spelling that shell hands out by default.
MSYS_AGENT = "/c/Users/x/.claude/agents/y.md"
MSYS_NOTES = "/c/Users/x/notes.txt"

# Real directories, so the cp/mv "destination is a directory" branch can be
# tested by what the filesystem says rather than by a trailing slash.
DEST_PROJ = os.path.join(PATCH_DIR, "proj")
os.makedirs(os.path.join(DEST_PROJ, ".claude"))
os.makedirs(os.path.join(DEST_PROJ, "src"))
# A cwd that sits inside a control-plane directory: a RELATIVE write there
# must be judged against the payload's cwd, not the hook process's.
FAKE_HOOKS_CWD = os.path.join(PATCH_DIR, "fake", ".claude", "hooks")
# Its two neighbours, for the PowerShell rows below: the `.claude` directory a
# session can sit directly in, and an ordinary project beside it. Never
# created on disk, like FAKE_HOOKS_CWD — nothing in the judged path touches
# the filesystem.
FAKE_CLAUDE_CWD = os.path.dirname(FAKE_HOOKS_CWD)
# The same hooks/ cwd with one extra dot. On Windows that IS the hooks
# directory — Win32 strips trailing dots off every path component — and it is
# not creatable through any normal API, which is exactly why it is only ever
# a string here. On POSIX it is a genuinely different directory and the rows
# using it are skipped out loud.
FAKE_DOTHOOKS_CWD = FAKE_HOOKS_CWD + "."
FAKE_PROJ_CWD = os.path.join(PATCH_DIR, "fake", "project")

# Patches name their targets inside the file, so these are the only place the
# hook can learn what `patch` and `git apply` are about to write.
SETTINGS_PATCH = patch_file("settings.patch", (
    "diff --git a/.claude/settings.json b/.claude/settings.json\n"
    "--- a/.claude/settings.json\n"
    "+++ b/.claude/settings.json\n"
    "@@ -1 +1 @@\n"
    "-{}\n"
    '+{"hooks": {}}\n'))
HOOK_PATCH = patch_file("hook.patch", (
    "--- a/.claude/hooks/x.py\n"
    "+++ b/.claude/hooks/x.py\n"
    "@@ -1 +1 @@\n"
    "-pass\n"
    "+import os\n"))
SRC_PATCH = patch_file("src.patch", (
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1 +1,2 @@\n"
    " x = 1\n"
    "+y = 2\n"))
# A created file has /dev/null on the other side of the pair.
ENV_PATCH = patch_file("env.patch", (
    "--- /dev/null\n"
    "+++ b/.env\n"
    "@@ -0,0 +1 @@\n"
    "+TOKEN=hunter2\n"))
# A deleted file has it on the near side.
DELETE_PATCH = patch_file("delete.patch", (
    "--- a/src/old.py\n"
    "+++ /dev/null\n"
    "@@ -1 +0,0 @@\n"
    "-gone = True\n"))
# Plain `diff -u` output: no a/ or b/ prefix, so it is applied with -p0.
BARE_PATCH = patch_file("bare.patch", (
    "--- src/app.py\n"
    "+++ src/app.py\n"
    "@@ -1 +1,2 @@\n"
    " x = 1\n"
    "+y = 2\n"))
SRC2_PATCH = patch_file("src2.patch", (
    "diff --git a/src/other.py b/src/other.py\n"
    "--- a/src/other.py\n"
    "+++ b/src/other.py\n"
    "@@ -1 +1,2 @@\n"
    " a = 1\n"
    "+b = 2\n"))
# A pure rename carries NO ---/+++ pair at all — git omits them when the
# content is unchanged — so the `diff --git` line is the only header naming
# the file it lands on. Verified against real `git diff -M` output.
RENAME_PATCH = patch_file("rename.patch", (
    "diff --git a/src/tmp.py b/.claude/hooks/evil.py\n"
    "similarity index 100%\n"
    "rename from src/tmp.py\n"
    "rename to .claude/hooks/evil.py\n"))
SRC_RENAME_PATCH = patch_file("src-rename.patch", (
    "diff --git a/src/old.py b/src/new.py\n"
    "similarity index 100%\n"
    "rename from src/old.py\n"
    "rename to src/new.py\n"))
# A space in the filename is all it took to put a rename back out of reach:
# the `diff --git` line then holds four space-separated words and no two of
# them are the two paths. This is verbatim `git diff -M` output — git does not
# quote a space — and `git apply --check` accepts it.
SPACED_RENAME_PATCH = patch_file("spaced-rename.patch", (
    "diff --git a/src/my file.py b/.claude/hooks/my file.py\n"
    "similarity index 100%\n"
    "rename from src/my file.py\n"
    "rename to .claude/hooks/my file.py\n"))
# The same rename with both names C-quoted, which is what git emits once a
# name carries non-ASCII bytes — and which `git apply --check` also accepts.
QUOTED_RENAME_PATCH = patch_file("quoted-rename.patch", (
    'diff --git "a/src/my file.py" "b/.claude/hooks/my file.py"\n'
    "similarity index 100%\n"
    "rename from src/my file.py\n"
    "rename to .claude/hooks/my file.py\n"))
# A mode-only change has no ---/+++ pair and no rename lines either, so the
# `diff --git` line is all there is — and both its names are the same, which
# is the one split git will make on a line it cannot otherwise separate.
SPACED_MODE_PATCH = patch_file("spaced-mode.patch", (
    "diff --git a/.claude/hooks/my hook.py b/.claude/hooks/my hook.py\n"
    "old mode 100644\n"
    "new mode 100755\n"))
# Ordinary code with a space in its name: still allowed, still logged.
SPACED_SRC_RENAME_PATCH = patch_file("spaced-src-rename.patch", (
    "diff --git a/src/my file.py b/src/your file.py\n"
    "similarity index 100%\n"
    "rename from src/my file.py\n"
    "rename to src/your file.py\n"))
# C-quoted ---/+++ headers: the quotes are git's, not part of the name.
QUOTED_PAIR_PATCH = patch_file("quoted-pair.patch", (
    '--- "a/sp file.py"\n'
    '+++ "b/sp file.py"\n'
    "@@ -1 +1 @@\n"
    "-x\n"
    "+y\n"))
QUOTED_SETTINGS_PATCH = patch_file("quoted-settings.patch", (
    '--- "a/.claude/settings.json"\n'
    '+++ "b/.claude/settings.json"\n'
    "@@ -1 +1 @@\n"
    "-{}\n"
    "+{}\n"))
MISSING_PATCH = os.path.join(PATCH_DIR, "absent.patch")
NOT_A_PATCH = patch_file("notes.txt", (
    "shopping list\n"
    "--- groceries ---\n"
    "- milk\n"
    "+ eggs\n"))
# A header naming its target through `./`. Both git and patch consume that as
# the component -p1 strips, so stripping it before applying the level took one
# component too many and the control-plane path stopped being one.
DOT_PATCH = patch_file("dot.patch", (
    "--- ./.claude/settings.json\n"
    "+++ ./.claude/settings.json\n"
    "@@ -1 +1 @@\n"
    "-{}\n"
    '+{"hooks": {}}\n'))
# A ---/+++ pair straddling the 2 MiB read cap: the cap cuts one character
# into the `+++` line, so a read that stops dead at the cap sees no pair at
# all and a control-plane patch sails through. The hook is expected to finish
# the straddling pair with bounded readline() calls.
_READ_CAP = 2 * 1024 * 1024  # route-models._PATCH_READ_LIMIT
_head = "--- a/.claude/settings.json\n"
_fill = ("x" * 63 + "\n") * 32767 + "y" * 34 + "\n"
if len(_fill) + len(_head) != _READ_CAP - 1:
    raise SystemExit("straddle fixture arithmetic is off")
STRADDLE_PATCH = patch_file("straddle.patch", (
    _fill + _head + "+++ b/.claude/settings.json\n@@ -1 +1 @@\n-{}\n+{}\n"))
# A deep header with no -p level: the suffix fan-out is capped, and the a/-
# prefixed spelling is dropped from the RECORD when its stripped sibling is
# present (judgment still sees every candidate).
_DEEP_PARTS = ["d%d" % k for k in range(100)]
_DEEP_REL = "/".join(_DEEP_PARTS) + "/f.py"
DEEP_PATCH = patch_file("deep.patch", (
    "--- a/" + _DEEP_REL + "\n"
    "+++ b/" + _DEEP_REL + "\n"
    "@@ -1 +1 @@\n"
    "-x\n"
    "+y\n"))
# A named pipe, which blocks in open() until something writes to it. Not a
# patch at all — the point is that reading it must not cost the session its
# verdict. Created here rather than by patch_file() because it is the one
# fixture whose whole nature is that it is not a regular file.
FIFO_PATCH = os.path.join(PATCH_DIR, "pipe.patch")
try:
    os.mkfifo(FIFO_PATCH)
except (AttributeError, OSError):
    # No mkfifo (Windows), or no permission: fall back to a plain file so the
    # case still runs and simply proves the ordinary path, rather than
    # vanishing silently and taking its coverage with it.
    FIFO_PATCH = patch_file("pipe.patch", "not a patch\n")

# A heredoc whose BODY merely mentions a control-plane redirect: written
# documentation, not a write to the control plane.
HEREDOC_MENTION = ("cat > guide.md <<'EOF'\n"
                   "persist it with: echo '{}' > ~/.claude/settings.json\n"
                   "EOF")

CASES = [
    # --- Edit/Write: the main loop writes, and the write is logged ---
    ("main Edit source file",        edit("Edit", PROJ),                                "allow"),
    ("main Write source file",       edit("Write", os.path.join(HOME, "project", "y.ts")), "allow"),
    ("subagent Edit source file",    edit("Edit", PROJ, "a1"),                          "allow"),
    ("main Write plans dir",         edit("Write", os.path.join(HOME, ".claude", "plans", "x.md")),    "allow"),
    ("main Write project memory",    edit("Write", os.path.join(HOME, ".claude", "projects", "p", "memory", "m.md")), "allow"),
    ("main Write todos",             edit("Write", os.path.join(HOME, ".claude", "todos", "t.json")),  "allow"),
    ("main Write system tempdir",    edit("Write", os.path.join(TMP, "scratch.txt")),   "allow"),
    ("main Write literal /tmp",      edit("Write", "/tmp/claude-1000/s/x.txt"),         "allow"),
    ("main Edit relative source",    edit("Edit", os.path.join("src", "app.py"), cwd=CWD),             "allow"),
    ("main Edit CLAUDE.md in proj",  edit("Edit", "CLAUDE.md", cwd=CWD),                "allow"),
    ("main Edit CLAUDE.md outside",  edit("Edit", os.path.join(HOME, "elsewhere", "CLAUDE.md"), cwd=CWD), "allow"),
    ("main Edit parent CLAUDE.md",   edit("Edit", os.path.join("..", "CLAUDE.md"), cwd=CWD),           "allow"),
    ("main Write user CLAUDE.md",    edit("Write", os.path.join(HOME, ".claude", "CLAUDE.md"), cwd=CWD), "allow"),
    ("main Write docs/plans file",   edit("Write", os.path.join(CWD, "docs", "plans", "v2.md"), cwd=CWD), "allow"),
    # --- a plugin's SOURCE tree is code, not the control plane ---
    ("main Edit plugin src hook",    edit("Edit", os.path.join(SRC, "hooks", "route-models.py")),      "allow"),
    ("main Edit plugin src agent",   edit("Edit", os.path.join(SRC, "agents", "coder.md")),            "allow"),
    ("main Edit plugin src command", edit("Edit", os.path.join(SRC, "commands", "doctor.md")),         "allow"),
    ("main Bash tee plugin src",     bash("ls | tee " + q(os.path.join(SRC, "hooks", "x.py"))),           "allow"),
    # --- the control plane: what governs the session that is running now ---
    ("main Write installed plugin",  edit("Write", os.path.join(HOME, ".claude", "plugins", "opulent", "hooks", "route-models.py")), "deny"),
    ("main Write plugins cache",     edit("Write", os.path.join(HOME, ".claude", "plugins", "cache", "x.json")), "deny"),
    ("main Write plugins marketplaces", edit("Write", os.path.join(HOME, ".claude", "plugins", "marketplaces", "m.json")), "deny"),
    ("main Write installed_plugins", edit("Write", os.path.join(HOME, ".claude", "plugins", "installed_plugins.json")), "deny"),
    # ... but plugins/data/ is CLAUDE_PLUGIN_DATA: state a plugin's hooks
    # WRITE, not configuration they read. Denying it left every plugin that
    # remembers anything unreadable and unfixable from the main loop, and
    # bought no governance at all.
    ("main Write plugin data file",  edit("Write", PLUGIN_DATA),                        "allow"),
    ("main Bash redirect plugin data", bash("echo {} > " + q(PLUGIN_DATA)),                "allow"),
    ("main Bash rm plugin data",     bash("rm " + q(PLUGIN_DATA)),                         "allow"),
    ("main Write project plugin data", edit("Write", os.path.join(".claude", "plugins", "data", "p", "s.json"), cwd=CWD), "allow"),
    # `data` has to sit immediately after `plugins` to be the carve-out: an
    # installed plugin's own data/ directory is part of that plugin's tree.
    ("main Write installed plugin's data", edit("Write", os.path.join(HOME, ".claude", "plugins", "opulent", "data", "x.json")), "deny"),
    # --- a sibling plugin's hook config governs this session too ---
    ("main Write user hookkit.json", edit("Write", HOOKKIT),                            "deny"),
    ("main Write project hookkit",   edit("Write", os.path.join(".claude", "hookkit.json"), cwd=CWD), "deny"),
    ("main Bash redirect hookkit",   bash("echo {} > .claude/hookkit.json", cwd=CWD),   "deny"),
    # --- and so does this plugin's own pr-lane config: it names the base
    # branch, the commands a lane is told to run and the identity it commits
    # under, so rewriting it rewrites every brief built from it.
    ("main Write user pr-lane.json", edit("Write", PRLANE_CONFIG),                      "deny"),
    ("main Write project pr-lane.json", edit("Write", os.path.join(".claude", "pr-lane.json"), cwd=CWD), "deny"),
    ("main Bash redirect pr-lane.json", bash("echo {} > .claude/pr-lane.json", cwd=CWD), "deny"),
    ("main PowerShell literal-built pr-lane.json",
     powershell('Set-Content -Path (Join-Path $HOME ".claude" "pr-lane.json") -Value x', cwd=CWD), "deny"),
    # ... and the non-deny twin, which is the whole shape of the design: the
    # LEDGER is a record the main loop is expected to append to. `pr-lane.json`
    # is configuration and `pr-lane/` is not, and one character between them
    # decides it — so both spellings are pinned here rather than one.
    ("main Write pr-lane ledger",    edit("Write", PRLANE_LEDGER),                      "allow"),
    ("main Bash append pr-lane ledger", bash("echo {} >> " + q(PRLANE_LEDGER)),         "allow"),
    ("main Write project pr-lane ledger", edit("Write", os.path.join(".claude", "pr-lane", "ledger.jsonl"), cwd=CWD), "allow"),
    ("main Write inside pr-lane dir", edit("Write", os.path.join(HOME, ".claude", "pr-lane", "notes.md")), "allow"),
    # ... and that set stays ENUMERATED. Claude writes .claude/launch.json
    # itself in ordinary preview use, so the tempting generalization — every
    # *.json beside settings.json — would have the hook fighting the harness
    # over the harness's own file.
    ("main Write launch.json",       edit("Write", os.path.join(".claude", "launch.json"), cwd=CWD), "allow"),
    ("main Write skill-rules.json",  edit("Write", os.path.join(".claude", "skill-rules.json"), cwd=CWD), "allow"),
    ("main Write user settings",     edit("Write", SETTINGS),                           "deny"),
    ("main Write settings.local",    edit("Write", os.path.join(HOME, ".claude", "settings.local.json")), "deny"),
    ("main Write user hook",         edit("Write", os.path.join(HOOKS_DIR, "x.py")),    "deny"),
    ("main Write user agent def",    edit("Write", os.path.join(HOME, ".claude", "agents", "x.md")),   "deny"),
    ("main Write user command def",  edit("Write", os.path.join(HOME, ".claude", "commands", "x.md")), "deny"),
    ("main Edit project settings",   edit("Edit", os.path.join(CWD, ".claude", "settings.json"), cwd=CWD), "deny"),
    ("main Edit project agent def",  edit("Edit", os.path.join(".claude", "agents", "x.md"), cwd=CWD), "deny"),
    ("main Edit project hook def",   edit("Edit", os.path.join(".claude", "hooks", "h.py"), cwd=CWD),  "deny"),
    ("main Write .env",              edit("Write", os.path.join(CWD, ".env"), cwd=CWD), "deny"),
    ("main Write .env.local",        edit("Write", ".env.local", cwd=CWD),              "deny"),
    # A trailing space must not defeat the basename rules.
    ("main Write settings + space",  edit("Write", SETTINGS + " "),                     "deny"),
    ("subagent Write settings",      edit("Write", SETTINGS, "a1"),                     "allow"),
    ("main Bash redirect settings",  bash("echo x > " + q(SETTINGS)),                      "deny"),
    ("main Bash cp into plugins",    bash("cp x.py " + q(os.path.join(HOME, ".claude", "plugins", "p", "h.py"))), "deny"),
    ("main Bash tee project .env",   bash("echo K=v | tee .env", cwd=CWD),              "deny"),
    # --- Windows path spellings, judged the way Bash hands them over ---
    # An UNQUOTED backslash path is not a control-plane path, because Bash
    # never delivers one: under POSIX rules a backslash escapes the character
    # behind it, so this command's target arrives as
    # `C:Usersx.claudesettings.json` — a relative name under the cwd, matching
    # nothing. The hook says what Bash does, and this is allow. (The record's
    # half of the claim — that no `edit` line names the settings file — is
    # asserted after the telemetry table, where a NOT-contains check fits.)
    ("unquoted backslash path is not a control-plane path",
     bash("echo x > " + WIN_UNQUOTED, cwd=CWD),                                         "allow"),
    # ... but a QUOTED one is delivered intact, in either quote, and that is
    # the spelling a person on Windows actually types.
    ("double-quoted backslash path into hooks is denied",
     bash('cp x "' + WIN_HOOK + '"', cwd=CWD),                                          "deny"),
    ("single-quoted backslash path into agents is denied",
     bash("cp x '" + WIN_AGENT + "'", cwd=CWD),                                         "deny"),
    # Git Bash's own default spelling reaches the same files.
    ("MSYS-spelled control-plane path is denied",
     bash("cp x " + MSYS_AGENT, cwd=CWD),                                               "deny"),
    # --- a patch writes the files named inside it, not the ones on the argv ---
    ("main git apply settings patch", bash("git apply " + q(SETTINGS_PATCH), cwd=CWD),     "deny"),
    ("main patch stdin settings",     bash("patch -p1 < " + q(SETTINGS_PATCH), cwd=CWD),   "deny"),
    ("main patch arg user hook",      bash("patch -p1 " + q(HOOK_PATCH), cwd=HOME),        "deny"),
    # -i names the patch; the positional beside it is the file being patched.
    ("main patch -i user hook",       bash("patch -i " + q(HOOK_PATCH) + " x.py", cwd=HOME), "deny"),
    ("main patch creates .env",       bash("git apply -p1 " + q(ENV_PATCH), cwd=CWD),      "deny"),
    # `git apply [<patch>...]` applies every patch it is given, so the verdict
    # must not depend on which one happens to be last on the line.
    ("main git apply evil then ok",   bash("git apply " + q(SETTINGS_PATCH) + " " + q(SRC_PATCH), cwd=CWD), "deny"),
    ("main git apply ok then evil",   bash("git apply " + q(SRC_PATCH) + " " + q(SETTINGS_PATCH), cwd=CWD), "deny"),
    ("main git apply two ok patches", bash("git apply -p1 " + q(SRC_PATCH) + " " + q(SRC2_PATCH), cwd=CWD), "allow"),
    # A rename has no ---/+++ pair; the `diff --git` line is the only header.
    ("main git apply rename to hook", bash("git apply " + q(RENAME_PATCH), cwd=CWD),       "deny"),
    ("main patch rename to hook",     bash("patch -p1 " + q(RENAME_PATCH), cwd=CWD),       "deny"),
    ("main git apply plain rename",   bash("git apply -p1 " + q(SRC_RENAME_PATCH), cwd=CWD), "allow"),
    # A space in the renamed file's name must not be a way out of the check,
    # quoted by git or not.
    ("main git apply spaced rename",  bash("git apply -p1 " + q(SPACED_RENAME_PATCH), cwd=CWD), "deny"),
    ("main git apply spaced no -p",   bash("git apply " + q(SPACED_RENAME_PATCH), cwd=CWD),  "deny"),
    ("main patch spaced rename",      bash("patch -p1 < " + q(SPACED_RENAME_PATCH), cwd=CWD), "deny"),
    ("main git apply quoted rename",  bash("git apply -p1 " + q(QUOTED_RENAME_PATCH), cwd=CWD), "deny"),
    ("main git apply spaced chmod",   bash("git apply -p1 " + q(SPACED_MODE_PATCH), cwd=CWD), "deny"),
    ("main git apply spaced src rename", bash("git apply -p1 " + q(SPACED_SRC_RENAME_PATCH), cwd=CWD), "allow"),
    # Quoted ---/+++ headers: the name inside the quotes is the one judged.
    ("main git apply quoted settings", bash("git apply -p1 " + q(QUOTED_SETTINGS_PATCH), cwd=CWD), "deny"),
    # The shell honours the LAST `<`, so that is the file actually applied.
    ("main patch double redirect",    bash("patch -p1 < " + q(SRC_PATCH) + " < " + q(SETTINGS_PATCH), cwd=CWD), "deny"),
    ("main git apply double redirect", bash("git apply < " + q(SRC_PATCH) + " < " + q(SETTINGS_PATCH), cwd=CWD), "deny"),
    # A pair straddling the read cap is completed, not dropped.
    ("main patch straddles read cap", bash("patch -p1 < " + q(STRADDLE_PATCH), cwd=CWD),   "deny"),
    # `git am` is `git apply` for format-patch output — same machinery.
    ("main git am settings patch",    bash("git am " + q(SETTINGS_PATCH), cwd=CWD),        "deny"),
    # --- 2026-08-13 review: each of these was ALLOWED, most of them silently.
    # Every case below was traced against the real tool before being written,
    # and every one of them fails against the hook as it stood.
    #
    # A git global option that takes a separate value used to swallow the
    # subcommand search, so the whole apply branch never ran: no denial, and no
    # log line either. The `=` spellings never had the problem, which is why
    # the bug survived: `--git-dir=x apply` works.
    ("main git -C apply settings",    bash("git -C . apply " + q(SETTINGS_PATCH), cwd=CWD), "deny"),
    ("main git --git-dir apply",      bash("git --git-dir .git apply " + q(SETTINGS_PATCH), cwd=CWD), "deny"),
    # The tool applies INTO a directory the headers never mention, so an
    # innocent header was judged while a control-plane file was rewritten —
    # and the audit line named the innocent one.
    ("main git apply --directory",    bash("git apply --directory=.claude/hooks " + q(SRC_PATCH), cwd=CWD), "deny"),
    ("main patch -d control dir",     bash("patch -d .claude/hooks -p1 < " + q(SRC_PATCH), cwd=CWD), "deny"),
    ("main patch -o control file",    bash("patch -p1 -o .claude/hooks/x.py < " + q(SRC_PATCH), cwd=CWD), "deny"),
    # GNU patch reads the patch from stdin when given one positional, so the
    # positional is the file being patched — consulting the redirect only when
    # no positional existed made this exact spelling allowed.
    ("main patch positional + stdin", bash("patch -p1 x.py < " + q(SETTINGS_PATCH), cwd=CWD), "deny"),
    # Both tools consume `./` as the component -p1 strips.
    ("main patch ./ header -p1",      bash("patch -p1 < " + q(DOT_PATCH), cwd=CWD),        "deny"),
    # tee and touch write EVERY operand; a decoy first argument hid the rest.
    ("main tee decoy then settings",  bash("ls | tee decoy.txt " + q(SETTINGS)),           "deny"),
    ("main touch decoy then hook",    bash("touch decoy.txt " + q(os.path.join(HOOKS_DIR, "x.py"))), "deny"),
    # -t puts the destination FIRST, so "last operand is the destination" was
    # exactly backwards — and the log named the source file instead.
    ("main cp -t into hooks",         bash("cp -t " + q(HOOKS_DIR) + " evil.py"),          "deny"),
    ("main mv -t into agents",        bash("mv -t " + q(os.path.join(HOME, ".claude", "agents")) + " a.md"), "deny"),
    # A prefix's own flag used to blank the detection of the command behind it.
    ("main sudo -u root cp hook",     bash("sudo -u root cp x.py " + q(os.path.join(HOOKS_DIR, "h.py"))), "deny"),
    ("main nice -n 10 cp hook",       bash("nice -n 10 cp x.py " + q(os.path.join(HOOKS_DIR, "h.py"))), "deny"),
    # ... but a prefix flag that takes NO value must not swallow the command.
    ("main sudo -n cp ordinary",      bash("sudo -n cp a.txt b.txt", cwd=CWD),          "allow"),
    # GNU sed's documented long form.
    ("main sed --in-place settings",  bash("sed --in-place s/a/b/ " + q(SETTINGS)),        "deny"),
    ("main sed --in-place= settings", bash("sed --in-place=bak s/a/b/ " + q(SETTINGS)),    "deny"),
    # Case-insensitive filesystems name the same files the guard protects, on
    # the two platforms the README claims this holds for.
    ("main Write .CLAUDE hooks",      edit("Write", os.path.join(HOME, ".CLAUDE", "hooks", "x.py")), "deny"),
    ("main Write .claude Hooks",      edit("Write", os.path.join(HOME, ".claude", "Hooks", "x.py")), "deny"),
    ("main Write Settings.json",      edit("Write", os.path.join(HOME, ".claude", "Settings.json")), "deny"),
    # OPULENT_OFF was removed in 0.15.0. The row that matters is the last one:
    # the spelling that used to disable every denial for a whole session now
    # enforces like any other, and a reintroduced kill switch fails here.
    ("OPULENT_OFF=0 still enforces",  edit("Write", SETTINGS), "deny", {"OPULENT_OFF": "0"}),
    ("OPULENT_OFF=false enforces",    edit("Write", SETTINGS), "deny", {"OPULENT_OFF": "false"}),
    ("OPULENT_OFF=1 no longer disables", edit("Write", SETTINGS), "deny", {"OPULENT_OFF": "1"}),
    ("OPULENT_ECO no longer caps",    task("opulent:coder"),   "allow", {"OPULENT_ECO": "1"}),
    ("OPULENT_CODEX no longer closes", task("opulent:coder"),     "allow", {"OPULENT_CODEX": "1"}),
    # A named pipe blocks open() forever; the size cap bounds how much is read,
    # not whether the read returns. isfile() rejects it, and the ERROR() a hang
    # would produce is what this case is really watching for.
    ("main git apply a FIFO",         bash("git apply " + q(FIFO_PATCH), cwd=CWD),         "allow"),
    # Fail open: an unreadable or unparseable patch must never block a session.
    ("main patch file is missing",    bash("git apply " + q(MISSING_PATCH), cwd=CWD),      "allow"),
    ("main patch file is not a patch", bash("patch -p1 < " + q(NOT_A_PATCH), cwd=CWD),     "allow"),
    # Inside a subagent the patch is nobody's business — the blanket allow wins.
    ("subagent git apply settings",   bash("git apply " + q(SETTINGS_PATCH), "a1", cwd=CWD), "allow"),
    ("subagent patch stdin settings", bash("patch -p1 < " + q(SETTINGS_PATCH), "a1", cwd=CWD), "allow"),
    ("subagent patch arg user hook",  bash("patch -p1 " + q(HOOK_PATCH), "a1", cwd=HOME),  "allow"),
    ("subagent patch -i user hook",   bash("patch -i " + q(HOOK_PATCH) + " x.py", "a1", cwd=HOME), "allow"),
    ("subagent patch creates .env",   bash("git apply -p1 " + q(ENV_PATCH), "a1", cwd=CWD), "allow"),
    ("subagent git apply two patches", bash("git apply " + q(SETTINGS_PATCH) + " " + q(SRC_PATCH), "a1", cwd=CWD), "allow"),
    ("subagent git apply rename",     bash("git apply " + q(RENAME_PATCH), "a1", cwd=CWD), "allow"),
    ("subagent spaced rename",        bash("git apply -p1 " + q(SPACED_RENAME_PATCH), "a1", cwd=CWD), "allow"),
    ("subagent quoted rename",        bash("git apply -p1 " + q(QUOTED_RENAME_PATCH), "a1", cwd=CWD), "allow"),
    ("subagent patch double redirect", bash("patch -p1 < " + q(SRC_PATCH) + " < " + q(SETTINGS_PATCH), "a1", cwd=CWD), "allow"),
    ("subagent git am settings",      bash("git am " + q(SETTINGS_PATCH), "a1", cwd=CWD),  "allow"),
    # --- writers inside shell compounds: reserved words are not commands ---
    ("main for-loop cp into hooks",   bash("for f in a.py b.py; do cp $f " + q(HOOKS_DIR) + "/; done"), "deny"),
    ("main if/then cp into hooks",    bash("if true; then cp x.py " + q(os.path.join(HOOKS_DIR, "x.py")) + "; fi"), "deny"),
    ("main brace group touch hook",   bash("{ touch " + q(os.path.join(HOOKS_DIR, "t.py")) + "; }"), "deny"),
    ("main while/do tee settings",    bash("while read l; do echo $l | tee " + q(SETTINGS) + "; done"), "deny"),
    ("main case arm cp into hooks",   bash("case $1 in x) echo ok ;; y) cp f.py " + q(os.path.join(HOOKS_DIR, "h.py")) + " ;; esac"), "deny"),
    # ... while words that merely LOOK like reserved words stay data.
    ("main echo do-mention (no FP)",  bash("echo do a barrel roll > /tmp/x"),           "allow"),
    # --- cp/mv with a directory destination classify the landed file ---
    ("main cp settings into ~/.claude/", bash("cp settings.json " + q(os.path.join(HOME, ".claude") + os.sep)), "deny"),
    ("main cp settings into real dir",   bash("cp settings.json .claude", cwd=DEST_PROJ), "deny"),
    ("main xargs cp -t into hooks",      bash("ls *.py | xargs cp -t " + q(HOOKS_DIR)),    "deny"),
    # --- find -exec runs the command it generates ---
    ("main find -exec cp into hooks",    bash("find . -name '*.py' -exec cp {} " + q(HOOKS_DIR) + "/ \\;"), "deny"),
    # --- csh-form redirect ---
    ("main >& into settings",            bash("make build >& " + q(SETTINGS)),             "deny"),
    ("main >&2 is not a file",           bash("echo x >&2"),                            "allow"),
    # --- prefix gaps: the wrapped command is still the command ---
    ("main timeout cp into hooks",       bash("timeout 30 cp x.py " + q(os.path.join(HOOKS_DIR, "h.py"))), "deny"),
    ("main nohup tee settings",          bash("nohup tee " + q(SETTINGS)),                 "deny"),
    ("main setsid cp into hooks",        bash("setsid cp x.py " + q(os.path.join(HOOKS_DIR, "h.py"))), "deny"),
    ("main stdbuf tee settings",         bash("stdbuf -o0 tee " + q(SETTINGS)),            "deny"),
    ("main sudo --user cp hook",         bash("sudo --user root cp x.py " + q(os.path.join(HOOKS_DIR, "h.py"))), "deny"),
    ("main xargs -a cp -t hooks",        bash("xargs -a list.txt cp -t " + q(HOOKS_DIR)),  "deny"),
    # --- touch value options are not targets ---
    ("main touch -r ref is not target",  bash("touch -r " + q(SETTINGS) + " stamp", cwd=CWD), "allow"),
    # --- heredoc bodies are content, not commands ---
    ("main heredoc mentions settings",   bash(HEREDOC_MENTION, cwd=CWD),                "allow"),
    ("main redirect then heredoc",       bash("cat > " + q(SETTINGS) + " <<EOF\nx\nEOF"),  "deny"),
    ("main heredoc then redirect",       bash("cat <<EOF > " + q(SETTINGS) + "\nx\nEOF"),  "deny"),
    # ... and a stray `<<` that is NOT a heredoc must not eat what follows.
    ("main here-string then cp",         bash('read -r a b <<< "$line"\ncp x.py ' + q(os.path.join(HOOKS_DIR, "x.py"))), "deny"),
    ("main arithmetic shift then cp",    bash("n=$((1 << 3))\ncp x.py " + q(os.path.join(HOOKS_DIR, "x.py"))), "deny"),
    # --- /usr/bin/time takes value options; the wrapped command is judged ---
    ("main /usr/bin/time -o cp hook",    bash("/usr/bin/time -o times.txt cp evil.py " + q(os.path.join(HOOKS_DIR, "h.py"))), "deny"),
    ("main time keyword cp hook",        bash("time cp x.py " + q(os.path.join(HOOKS_DIR, "h.py"))), "deny"),
    # --- newline is a command separator, like `;` ---
    ("main newline cd then settings",    bash("cd .claude\necho x > settings.json", cwd=CWD), "deny"),
    ("main multi-line for-loop cp",      bash("for f in a.py b.py\ndo\ncp $f " + q(HOOKS_DIR) + "/\ndone"), "deny"),
    ("main comment then cp hook",        bash("# staging the hook\ncp x.py " + q(os.path.join(HOOKS_DIR, "x.py"))), "deny"),
    # --- install writes directories with -d, and via -t ---
    ("main install -d control dir",      bash("install -d " + q(HOOKS_DIR)),               "deny"),
    ("main install -t into hooks",       bash("install -t " + q(HOOKS_DIR) + " x.py"),     "deny"),
    # --- ln -t targets the directory, not the last operand ---
    ("main ln -t into hooks",            bash("ln -t " + q(HOOKS_DIR) + " x.py"),          "deny"),
    # --- accident-shaped neighbor verbs ---
    ("main install into hooks",          bash("install m.py " + q(os.path.join(HOOKS_DIR, "m.py"))), "deny"),
    ("main ln -sf into hooks",           bash("ln -sf x.py " + q(os.path.join(HOOKS_DIR, "link.py"))), "deny"),
    ("main dd of= into hooks",           bash("dd if=/dev/zero of=" + q(os.path.join(HOOKS_DIR, "h.py"))), "deny"),
    ("main curl -o into hooks",          bash("curl -o " + q(os.path.join(HOOKS_DIR, "x.py")) + " https://example.com"), "deny"),
    ("main wget -O into hooks",          bash("wget -O " + q(os.path.join(HOOKS_DIR, "x.py")) + " https://example.com"), "deny"),
    ("main curl without -o (no FP)",     bash("curl https://example.com"),              "allow"),
    ("main ln single operand (no FP)",   bash("ln -s /usr/bin/python3"),                "allow"),
    # --- leading cd moves the judged directory ---
    ("main cd .claude then settings",    bash("cd .claude && echo x > settings.json", cwd=CWD), "deny"),
    ("main bare cd then settings",       bash("cd && echo x > .claude/settings.json", cwd=CWD), "deny"),
    ("main cd /tmp then scratch",        bash("cd /tmp && echo x > scratch.txt", cwd=CWD), "allow"),
    ("main cd - stays unmodeled",        bash("cd - && echo x > notes.txt", cwd=CWD),   "allow"),
    # --- payload cwd is load-bearing for relative targets ---
    ("cwd inside hooks, relative write", {"tool_name": "Bash",
                                          "tool_input": {"command": "echo x > y.py"},
                                          "cwd": FAKE_HOOKS_CWD},                       "deny"),
    # --- .env templates are committed documentation, not secrets ---
    ("main Write .env.example",       edit("Write", ".env.example", cwd=CWD),           "allow"),
    ("main Write .env.sample",        edit("Write", ".env.sample", cwd=CWD),            "allow"),
    ("main Write .env.template",      edit("Write", ".env.template", cwd=CWD),          "allow"),
    ("main Write .env.dist",          edit("Write", ".env.dist", cwd=CWD),              "allow"),
    ("main Write .envrc still denied", edit("Write", ".envrc", cwd=CWD),                "deny"),
    # --- test/build/lint commands: the main loop may run them ---
    ("main Bash pytest",             bash("pytest -x tests/"),                          "allow"),
    ("main Bash cd && pytest",       bash("cd proj && pytest"),                         "allow"),
    ("main Bash npm run build",      bash("npm run build"),                             "allow"),
    ("main Bash ./gradlew test",     bash("./gradlew test"),                            "allow"),
    ("subagent Bash pytest",         bash("pytest -x", "a2"),                           "allow"),
    ("main Bash git status",         bash("git status"),                                "allow"),
    ("main Bash echo mention",       bash("echo pytest is great"),                      "allow"),
    # VERSION_RE is gone: a `--version` probe MAY be recorded as a test run
    # now (over-logging is the safe direction). Only the decision is pinned.
    ("main Bash tsc --version",      bash("tsc --version"),                             "allow"),
    # --- Bash file-writes: allowed, outside the control plane ---
    ("main Bash redirect to file",   bash("echo hi > notes.txt"),                       "allow"),
    ("main Bash append to file",     bash("echo hi >> src/app.py"),                     "allow"),
    ("main Bash heredoc write",      bash("cat > config.yml <<EOF\nkey: v\nEOF"),      "allow"),
    ("main Bash tee",                bash("ls -la | tee listing.txt"),                  "allow"),
    ("main Bash sed in-place",       bash("sed -i s/foo/bar/ src/app.py"),              "allow"),
    ("main Bash cp",                 bash("cp template.py src/app.py"),                 "allow"),
    ("main Bash mv",                 bash("mv old.py new.py"),                          "allow"),
    ("main Bash touch",              bash("touch src/newfile.py"),                      "allow"),
    ("main Bash patch",              bash("patch -p1 fix.patch"),                       "allow"),
    ("main Bash git apply",          bash("git apply fix.patch"),                       "allow"),
    ("main Bash redirect devnull",   bash("git log --oneline > /dev/null"),             "allow"),
    ("main Bash fd duplication",     bash("some_command 2>&1"),                         "allow"),
    ("main Bash quoted gt (no FP)",  bash("git commit -m 'refactor: a > b mapping'"),   "allow"),
    # --- PowerShell: the other shell that reaches the filesystem ---
    # Guarded by TEXT, not by a parser — see the block comment above
    # _PS_WRITE_TOKENS in route-models.py. A command naming a control-plane
    # path is refused whether or not the hook could tell it was writing.
    ("PowerShell Set-Content into settings.json is denied",
     powershell("Set-Content -Path " + q(SETTINGS) + " -Value '{}'", cwd=CWD),          "deny"),
    ("PowerShell Copy-Item into .claude/hooks is denied",
     powershell("Copy-Item x.py " + q(os.path.join(HOOKS_DIR, "y.py")), cwd=CWD),       "deny"),
    ("PowerShell Remove-Item of a user agent def is denied",
     powershell("Remove-Item " + q(os.path.join(HOME, ".claude", "agents", "x.md")), cwd=CWD), "deny"),
    # The mirror image of the Bash row above, and deliberately the opposite
    # verdict: PowerShell does not treat a backslash as an escape, so an
    # unquoted Windows path reaches the cmdlet intact and must be judged.
    ("PowerShell backslash path into hooks is denied unquoted too",
     powershell("Copy-Item x.py " + WIN_HOOK, cwd=CWD),                                 "deny"),
    # ... and the false positives that are NOT being added: the same cmdlets
    # writing ordinary files, and a plugin's SOURCE tree, stay allowed.
    ("PowerShell Set-Content into an ordinary file is allowed",
     powershell("Set-Content build.log -Value ok", cwd=CWD),                            "allow"),
    ("PowerShell Copy-Item into a plugin source tree is allowed",
     powershell("Copy-Item x.py " + q(os.path.join(SRC, "hooks", "y.py")), cwd=CWD),    "allow"),
    ("PowerShell git status is allowed",
     powershell("git status", cwd=CWD),                                                 "allow"),
    # A bare cmdlet name is not a path. Without that filter a PowerShell
    # session whose cwd sat inside .claude/hooks would resolve every word into
    # the control plane and be refused for saying hello.
    ("PowerShell Get-ChildItem in a control-plane cwd is allowed",
     {"tool_name": "PowerShell", "tool_input": {"command": "Get-ChildItem"},
      "cwd": FAKE_HOOKS_CWD},                                                           "allow"),
    ("subagent PowerShell into settings is allowed",
     powershell("Set-Content " + q(SETTINGS) + " -Value x", "a1", cwd=CWD),             "allow"),
    ("PostToolUse PowerShell control plane is not denied",
     post(powershell("Set-Content " + q(SETTINGS) + " -Value x", cwd=CWD)),             "allow"),
    # --- PowerShell: a path spelled out of SEPARATE literals ---
    # The per-token pass sees one token at a time, so `Join-Path $HOME
    # ".claude" "hooks"` hands it no resolvable path at all: measured ALLOWED
    # against the branch as first shipped, by ordinary non-adversarial
    # path-building, which made the whole control-plane check optional on
    # Windows. The co-occurrence rule refuses these — write-shaped, and every
    # literal is still in the text. See _ps_cooccurring_control.
    ("PowerShell Join-Path-built control-plane destination is denied",
     powershell('$dir = Join-Path $HOME ".claude" "hooks"\n'
                'Set-Content -Path (Join-Path $dir "evil.py") -Value "pwned"',
                cwd=CWD),                                                               "deny"),
    ("PowerShell concatenation-built control-plane destination is denied",
     powershell('Set-Content -Path ($HOME + ".claude" + "hooks\\evil.py") '
                '-Value "pwned"', cwd=CWD),                                             "deny"),
    ("PowerShell -Destination built from literals is denied",
     powershell('Copy-Item x -Destination (Join-Path $HOME ".claude" "agents")',
                cwd=CWD),                                                               "deny"),
    # One contiguous literal, which the per-token pass already caught — pinned
    # so the co-occurrence rule cannot be "simplified" into replacing it.
    ("PowerShell -LiteralPath naming settings.json is denied",
     powershell('Set-Content -LiteralPath "$HOME\\.claude\\settings.json" -Value x',
                cwd=CWD),                                                               "deny"),
    # --- PowerShell: bare control-plane directory names resolve too ---
    # _ps_pathish enumerated only BASENAMES the rules judge, so a bare
    # directory name was never resolved: a session sitting in ~/.claude could
    # delete hooks/ by naming it plainly. Measured allowed.
    ("PowerShell Remove-Item of a bare hooks/ in a .claude cwd is denied",
     powershell("Remove-Item hooks -Recurse -Force", cwd=FAKE_CLAUDE_CWD),              "deny"),
    # And the per-token rule is not write-gated, which is this branch's stated
    # design: a command NAMING the control plane is refused whether or not we
    # could tell it was writing. So a bare `hooks` resolving into a .claude
    # cwd is refused even with no write shape at all — the same answer Bash
    # gives `echo x > y.py` from inside hooks/. Over-refusing costs a rephrase
    # and names what it objected to.
    ("PowerShell Write-Output of a bare hooks/ in a .claude cwd is denied",
     powershell('Write-Output "hooks"', cwd=FAKE_CLAUDE_CWD),                           "deny"),
    # --- co-occurrence is WRITE-shaped only, and keeps the plugins/data carve-out ---
    ("PowerShell Get-Content of a literal-built control-plane path is allowed",
     powershell('Get-Content (Join-Path $HOME ".claude" "hooks" "x.py")', cwd=CWD),     "allow"),
    ("PowerShell Set-Content into literal-built plugins/data is allowed",
     powershell('Set-Content (Join-Path $HOME ".claude" "plugins" "data" '
                '"state.json") -Value x', cwd=CWD),                                     "allow"),
    # The price of a text-level rule, paid out loud rather than papered over:
    # two words inside ONE prose string are indistinguishable from the two
    # literals a path is built from, because there is no parser here to say
    # otherwise. A false deny costs one retry with a different phrasing; the
    # alternative costs the guarantee, since every bypass above is spelled
    # with literals too. The seatbelt takes that trade.
    ("PowerShell prose naming .claude and hooks in a write is denied",
     powershell('Set-Content notes.md -Value "see .claude and hooks in the docs"',
                cwd=CWD),                                                               "deny"),
    # --- KNOWN GAPS, pinned at what the code actually does ---
    # Reported as a PowerShell-vs-Bash asymmetry; survives the fixes above,
    # for reasons that do not live in the PowerShell branch.
    #
    # is_control_plane judges what sits UNDER a .claude directory, so a
    # path ENDING at .claude is not the control plane on EITHER shell —
    # `rm -rf ~/.claude` is allowed by the Bash branch too (measured, not
    # assumed). Closing it means changing is_control_plane, which moves
    # both shells at once and is not a PowerShell fix.
    ("PowerShell Remove-Item of .claude itself is allowed, exactly as in Bash",
     powershell("Remove-Item .claude -Recurse -Force", cwd=FAKE_PROJ_CWD),              "allow"),
    # --- PowerShell: a write-shaped command from a control-plane cwd ---
    # A bare `y.py` is path-ish under none of the rules, so the per-token
    # pass alone never resolves it. Bash catches the mirror row above only
    # because its parser knows `y.py` is a redirect TARGET and resolves it
    # against the payload's cwd; PowerShell has no parser, so a write shape
    # from a control-plane cwd is judged on the cwd itself instead: denied
    # outright, whatever its tokens spell. The "Get-ChildItem in a
    # control-plane cwd" row above stays green because it carries no write
    # shape.
    ("PowerShell relative write in a control-plane cwd is denied",
     powershell("Set-Content y.py -Value x", cwd=FAKE_HOOKS_CWD),                       "deny"),
    # --- the plugins/data carve-out is ADJACENCY, not word presence ---
    # It used to ask whether the atom `data` appeared ANYWHERE in the command
    # text — including inside a -Value payload or a trailing comment — so one
    # word in the wrong place bought a write to the file that decides which
    # plugins load at all. Both rows below were measured ALLOWED. The single-
    # literal spelling of the same path was denied by is_control_plane the
    # whole time, so the two halves of one rule disagreed. Not win32-gated:
    # adjacency has nothing to do with the platform.
    ("PowerShell plugins/ write with data only in -Value is denied",
     powershell('Set-Content -Path (Join-Path $HOME ".claude" "plugins" '
                '"installed_plugins.json") -Value "data"', cwd=CWD),                    "deny"),
    ("PowerShell plugins/ write with data only in a comment is denied",
     powershell('Set-Content -Path (Join-Path $HOME ".claude" "plugins" '
                '"installed_plugins.json") -Value "x" # data', cwd=CWD),                "deny"),
    # And the carve-out itself, spelled the other way a real path spells it:
    # adjacency is read over ATOMS, not over the quoted argument list, so one
    # argument holding `plugins\data` still qualifies. A token-level adjacency
    # rule would deny this and break every plugin that keeps state.
    ("PowerShell backslash-spelled plugins\\data write is still allowed",
     powershell('Set-Content (Join-Path $HOME ".claude" "plugins\\data" '
                '"s.json") -Value x', cwd=CWD),                                         "allow"),
    # --- a non-string cwd must not disable the branch ---
    # `cwd` arrived from the payload uncoerced, so a non-string one raised
    # inside _resolve and fell to the module's blanket fail-open: the call was
    # ALLOWED with no log line at all, and BOTH shells' control-plane checks
    # were skipped whole. Measured — the third row here was allowed with a
    # fully spelled-out absolute path to a hook. str() at the read site, the
    # same treatment subagent_type already got.
    ("PowerShell read with a non-string cwd is allowed",
     {"tool_name": "PowerShell", "tool_input": {"command": "Get-ChildItem"},
      "cwd": 42},                                                                       "allow"),
    # "42" is a relative path: resolved under the hook process's own cwd, it
    # names nothing in the control plane, so allow is the right answer here —
    # what changed is that the branch RAN to reach it.
    ("PowerShell relative write with a non-string cwd is allowed",
     {"tool_name": "PowerShell", "tool_input": {"command": "Set-Content y.py -Value x"},
      "cwd": 42},                                                                       "allow"),
    ("PowerShell control-plane write with a non-string cwd is still denied",
     {"tool_name": "PowerShell",
      "tool_input": {"command": 'Set-Content -Path ' + q(WIN_HOOK) + ' -Value x'},
      "cwd": 42},                                                                       "deny"),
    ("Bash control-plane write with a non-string cwd is still denied",
     {"tool_name": "Bash",
      "tool_input": {"command": "echo x > " + q(WIN_HOOK)}, "cwd": 42},                 "deny"),
    # --- Windows strips a trailing dot; the guard has to know that ---
    # `~/.claude/hooks./evil.py` lands inside the real hooks directory on
    # Windows (measured with New-Item on a real machine) and in a genuinely
    # different directory on POSIX. So this row asserts the PLATFORM's own
    # reading, the way the MSYS row below does: it can only be wrong in one
    # direction on each, and neither platform is left uncovered. The POSIX
    # half is the false-positive guard — `hooks.` there must stay ordinary.
    ("a trailing dot on a Bash-spelled hooks/ is judged at the platform's own "
     "reading",
     bash("echo x > ~/.claude/hooks./evil.py", cwd=CWD),
     "deny" if sys.platform == "win32" else "allow"),
    # --- delegation routing: unchanged, this was never the lockout ---
    ("main Task->Explore allowed",   task("Explore"),                                   "allow"),
    ("main Agent->Explore allowed",  {"tool_name": "Agent",
                                      "tool_input": {"subagent_type": "Explore"}},    "allow"),
    ("main Task->general-purpose",   task("general-purpose"),                           "deny"),
    ("main Task->claude catch-all",  task("claude"),                                    "deny"),
    ("main Task->opulent lane",      task("opulent:coder"),                             "allow"),
    ("main Task->Plan",              task("Plan"),                                      "allow"),
    ("main Task->other plugin",      task("nimble:nimble-researcher"),                  "allow"),
    ("subagent Task->general",       task("general-purpose", "a3"),                     "allow"),
    ("subagent Task->Explore",       task("Explore", "a5"),                             "allow"),
    # --- the ladder is two lanes now, and both spawn freely ---
    ("main Task->coder",             task("opulent:coder"),                             "allow"),
    ("main Task->mechanic",          task("opulent:mechanic"),                          "allow"),
    ("main Task->test-runner",       task("opulent:test-runner"),                       "allow"),
    ("main Task->reviewer",          task("opulent:reviewer"),                          "allow"),
    # Retired lanes are not special-cased: an unregistered opulent:* name is an
    # ordinary delegation the harness will reject on its own, and the hook
    # inventing a denial for it would be a second source of truth.
    ("main Task->retired scout",     task("opulent:scout"),                             "allow"),
    ("main Task->retired ui-checker", task("opulent:ui-checker"),                       "allow"),
    ("main Task->retired scribe",    task("opulent:scribe"),                            "allow"),
    # --- the two events: PreToolUse decides, PostToolUse only records ---
    ("PreToolUse spelled out denies", pre(edit("Write", SETTINGS)),                     "deny"),
    ("PostToolUse control plane is not denied", post(edit("Write", SETTINGS)),          "allow"),
    ("PostToolUse catch-all is not denied", post(task("general-purpose")),              "allow"),
    ("PostToolUse canary is not denied", post(bash("touch opulent-doctor-canary", cwd=CWD)), "allow"),
    # An event name the hook does not know — a missing one, or one a future
    # Claude Code introduces — falls to the DECIDING branch. That is the safer
    # of the two mistakes: a denial nobody wanted is visible in the session,
    # and a log line nobody wanted is not.
    ("missing hook_event_name still denies", edit("Write", SETTINGS),                   "deny"),
    ("unknown hook_event_name still denies",
     {"tool_name": "Write", "tool_input": {"file_path": SETTINGS},
      "hook_event_name": "PreToolUseV2"},                                               "deny"),
    # --- reads, garbage ---
    ("main Read tool",               {"tool_name": "Read",
                                      "tool_input": {"file_path": PROJ}},              "allow"),
    ("malformed JSON",               "not json at all",                                 "allow"),
    ("non-dict payload",             "[1,2,3]",                                         "allow"),
]

failures = 0
for case in CASES:
    desc, payload, expected = case[0], case[1], case[2]
    env_extra = case[3] if len(case) > 3 else None
    got = run(payload, env_extra)
    status = "PASS" if got == expected else "FAIL"
    if status == "FAIL":
        failures += 1
    print(f"{status}  {desc}: expected={expected} got={got}")


def logged(payload, env_extra=None):
    """Run one payload against a real log file; return (decision, entries)."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    f.close()
    env = {"OPULENT_LOG": f.name}
    if env_extra:
        env.update(env_extra)
    try:
        got = run(payload, env)
        with open(f.name, encoding="utf-8") as fh:
            entries = [json.loads(line) for line in fh if line.strip()]
    finally:
        os.unlink(f.name)
    return got, entries


def schema_problems(payload, entries):
    """Every log line carries a timestamp, and carries the payload's session
    id (first 8 chars) exactly when the payload named one."""
    probs = []
    want_sid = ""
    if isinstance(payload, dict):
        want_sid = str(payload.get("session_id") or "")[:8]
    for e in entries:
        if "t" not in e:
            probs.append("line without t")
        if want_sid and e.get("sid") != want_sid:
            probs.append("sid=%r want %r" % (e.get("sid"), want_sid))
        if not want_sid and "sid" in e:
            probs.append("stray sid")
    return probs


def R(*parts):
    """Resolved fixture path, the way the hook records one."""
    return os.path.normpath(os.path.join(*parts))


SID = "session-1234-abcd"

# --- telemetry: the audit trail is what the lockout was really buying, so a
# main-loop write that is now ALLOWED still has to leave a line behind — and
# the event LIST is asserted whole, with details naming resolved paths.
TELEMETRY = [
    # --- the split itself. Until 0.20.0 every line below was written at
    # PreToolUse, where the action had not happened yet: another plugin's hook
    # on the same event could still deny the call, and the log kept the line
    # anyway. These four pin the deciding half writing NOTHING.
    ("PreToolUse test run records nothing",
     pre(bash("npm test", cwd=CWD)), "allow", []),
    ("PreToolUse ordinary edit records nothing",
     pre(edit("Edit", os.path.join(CWD, "src", "app.py"), cwd=CWD)), "allow", []),
    ("PreToolUse rm records nothing",
     pre(bash("rm src/old.py", cwd=CWD)), "allow", []),
    ("PreToolUse delegation records nothing",
     pre({"tool_name": "Agent", "tool_input": {"subagent_type": "opulent:coder"}}),
     "allow", []),
    # ... and the recording half deciding nothing. A control-plane write or a
    # catch-all spawn that reaches PostToolUse HAPPENED — the hooks were off,
    # or the denial was bypassed — so the record names it, with no output.
    ("PostToolUse control-plane write is recorded as an edit",
     post(edit("Write", SETTINGS)), "allow", ["edit"], SETTINGS),
    ("PostToolUse catch-all spawn is recorded as a delegate",
     post(task("general-purpose")), "allow", ["delegate"], "general-purpose"),
    ("PostToolUse Agent delegation logs exactly one delegate",
     post({"tool_name": "Agent", "tool_input": {"subagent_type": "opulent:coder"}}),
     "allow", ["delegate"], "opulent:coder"),
    # --- plugin data is state, so it is recorded like any other state the
    # main loop touches, both when it is written and when it is deleted ---
    ("a write under plugins/data is recorded as an edit",
     post(edit("Write", PLUGIN_DATA)), "allow", ["edit"], PLUGIN_DATA),
    ("a redirect into plugins/data is recorded as an edit",
     post(bash("echo {} > " + q(PLUGIN_DATA), cwd=CWD)), "allow", ["edit"], PLUGIN_DATA),
    ("an rm under plugins/data is recorded as a remove",
     post(bash("rm " + q(PLUGIN_DATA), cwd=CWD)), "allow", ["remove"], PLUGIN_DATA),
    # --- the pr-lane ledger is state too, and it is recorded in the ROUTING
    # log's own vocabulary: `edit`, not a sixth event name. The two files stay
    # separate, and neither borrows the other's words.
    ("a write to the pr-lane ledger is recorded as an edit",
     post(edit("Write", PRLANE_LEDGER)), "allow", ["edit"], PRLANE_LEDGER),
    ("a bash append to the pr-lane ledger is recorded as an edit",
     post(bash("echo {} >> " + q(PRLANE_LEDGER), cwd=CWD)), "allow", ["edit"],
     PRLANE_LEDGER),
    # --- the record's staples ---
    ("main edit logs exactly one edit",
     post(edit("Edit", os.path.join(CWD, "src", "app.py"), cwd=CWD)),
     "allow", ["edit"], R(CWD, "src", "app.py")),
    ("main bash write logs exactly one edit",
     post(bash("echo hi > notes.txt", cwd=CWD)), "allow", ["edit"], R(CWD, "notes.txt")),
    ("main test run logs exactly one test",
     post(bash("pytest -q", cwd=CWD)), "allow", ["test"], "pytest -q"),
    ("a write AND a test run log both events",
     post(bash("pytest > results.txt", cwd=CWD)), "allow", ["edit", "test"],
     R(CWD, "results.txt")),
    ("scratch write is not logged",
     post(edit("Write", os.path.join(TMP, "scratch.txt"), cwd=CWD)), "allow", []),
    ("bash scratch redirect is not logged",
     post(bash("echo x > " + q(os.path.join(TMP, "opulent-scratch.txt")), cwd=CWD)),
     "allow", []),
    ("bash write into plans is not logged",
     post(bash("echo x > " + q(os.path.join(HOME, ".claude", "plans", "p.md")), cwd=CWD)),
     "allow", []),
    ("subagent edit is not logged",
     post(edit("Edit", PROJ, "a1")), "allow", []),
    ("control-plane denial logs exactly one deny",
     pre(edit("Write", SETTINGS)), "deny", ["deny"], "control:" + SETTINGS),
    ("the canary is denied and logged as a probe, with its path",
     pre(bash("touch opulent-doctor-canary", cwd=CWD)), "deny", ["probe"],
     "canary:" + R(CWD, "opulent-doctor-canary")),
    # --- delegation: the log's dominant event, asserted at last ---
    ("Task delegation logs exactly one delegate",
     post(task("opulent:coder")), "allow", ["delegate"], "opulent:coder"),
    ("Agent-tool delegation logs exactly one delegate",
     post({"tool_name": "Agent", "tool_input": {"subagent_type": "opulent:mechanic"}}),
     "allow", ["delegate"], "opulent:mechanic"),
    ("Agent-tool delegation to the reviewer logs exactly one delegate",
     post({"tool_name": "Agent", "tool_input": {"subagent_type": "opulent:reviewer"}}),
     "allow", ["delegate"], "opulent:reviewer"),
    ("subagent Task logs nothing",
     post(task("opulent:coder", "a7")), "allow", []),
    ("a session id in the payload lands on the log line",
     post(task("opulent:coder", sid=SID)), "allow", ["delegate"], "opulent:coder"),
    ("session id on a bash edit line too",
     post(bash("echo hi > notes.txt", cwd=CWD, sid=SID)), "allow", ["edit"],
     R(CWD, "notes.txt")),
    # --- a malformed spawn payload cannot reach a real agent, so allow is
    # right — but it must still leave a record. subagent_type is not
    # guaranteed to be a string; these pin what the log shows when it isn't.
    ("list subagent_type still logs a delegate",
     post(task(["opulent:coder"])), "allow", ["delegate"],
     "['opulent:coder']"),
    ("dict subagent_type still logs a delegate",
     post(task({"a": 1})), "allow", ["delegate"], "{'a': 1}"),
    # int already worked before this fix — _log's own str() coercion covered
    # it — so this pins existing behavior rather than a new one.
    ("int subagent_type already logs a delegate",
     post(task(12345)), "allow", ["delegate"], "12345"),
    # --- denial events carry their kind, not `probe` ---
    ("catch-all denial logs event deny",
     pre(task("general-purpose")), "deny", ["deny"], "catchall:general-purpose"),
    # --- MultiEdit / NotebookEdit are guarded and recorded like Edit ---
    ("NotebookEdit control-plane deny",
     pre({"tool_name": "NotebookEdit",
          "tool_input": {"notebook_path": os.path.join(HOOKS_DIR, "x.ipynb")}}),
     "deny", ["deny"], "control:" + os.path.join(HOOKS_DIR, "x.ipynb")),
    ("NotebookEdit ordinary write logs an edit",
     post({"tool_name": "NotebookEdit",
           "tool_input": {"notebook_path": os.path.join(CWD, "nb.ipynb")}, "cwd": CWD}),
     "allow", ["edit"], R(CWD, "nb.ipynb")),
    ("MultiEdit control-plane deny",
     pre(edit("MultiEdit", SETTINGS)), "deny", ["deny"], "control:" + SETTINGS),
    ("MultiEdit ordinary write logs an edit",
     post(edit("MultiEdit", os.path.join(CWD, "m.py"), cwd=CWD)), "allow", ["edit"],
     R(CWD, "m.py")),
    # --- a falsy path is nothing: no judgment, no record ---
    ("Write with empty file_path logs nothing",
     post(edit("Write", "")), "allow", []),
    ("Edit with no file_path at all logs nothing",
     post({"tool_name": "Edit", "tool_input": {}}), "allow", []),
    # --- an unparseable command still leaves a line ---
    ("unbalanced quote logs unparsed",
     post(bash("echo it's here > notes.txt", cwd=CWD)), "allow", ["unparsed"],
     "echo it's here > notes.txt"),
    ("balanced apostrophe parses normally",
     post(bash('echo "it\'s" > notes.txt', cwd=CWD)), "allow", ["edit"],
     R(CWD, "notes.txt")),
    # --- deletions become visible ---
    ("rm logs a remove with resolved operands",
     post(bash("rm src/old.py", cwd=CWD)), "allow", ["remove"], R(CWD, "src", "old.py")),
    ("rm of several operands records them all",
     post(bash("rm -rf build dist", cwd=CWD)), "allow", ["remove"],
     R(CWD, "build") + ", " + R(CWD, "dist")),
    ("rm of scratch is not logged",
     post(bash("rm " + q(os.path.join(TMP, "x.tmp")), cwd=CWD)), "allow", []),
    ("git reset --hard logs a remove",
     post(bash("git reset --hard", cwd=CWD)), "allow", ["remove"], "git reset --hard"),
    ("git clean logs a remove",
     post(bash("git clean -fd", cwd=CWD)), "allow", ["remove"], "git clean -fd"),
    ("git checkout -- logs a remove",
     post(bash("git checkout -- .", cwd=CWD)), "allow", ["remove"], "git checkout -- ."),
    ("git restore logs a remove",
     post(bash("git restore app.py", cwd=CWD)), "allow", ["remove"], "git restore app.py"),
    ("git stash drop logs a remove",
     post(bash("git stash drop", cwd=CWD)), "allow", ["remove"], "git stash drop"),
    ("plain git checkout of a branch is not a remove",
     post(bash("git checkout main", cwd=CWD)), "allow", []),
    ("git stash list is not a remove",
     post(bash("git stash list", cwd=CWD)), "allow", []),
    ("mv records source and destination",
     post(bash("mv old.py new.py", cwd=CWD)), "allow", ["edit"],
     R(CWD, "old.py") + " -> " + R(CWD, "new.py")),
    # --- reserved words / compounds: the twin false-positives log nothing ---
    ("echo do-mention logs nothing",
     post(bash("echo do a barrel roll > /tmp/x", cwd=CWD)), "allow", []),
    ("quoted then-cp in a commit message logs nothing",
     post(bash('git commit -m "then cp a b"', cwd=CWD)), "allow", []),
    # --- cp/mv directory destinations record the landed file ---
    ("cp into an existing dir records dir/basename",
     post(bash("cp a.py src/", cwd=CWD)), "allow", ["edit"], R(CWD, "src", "a.py")),
    # Three or more operands can only mean a directory destination — no
    # trailing slash and no filesystem check needed. (The isdir arm is pinned
    # by the "cp settings into real dir" deny above; a real dir under the
    # suite's tempdir would be scratch-filtered out of the record here.)
    ("cp of two sources into a dir records both landed files",
     post(bash("cp a.py b.py src", cwd=CWD)), "allow", ["edit"],
     R(CWD, "src", "a.py") + ", " + R(CWD, "src", "b.py")),
    ("cp -t detail names the destination, not the source",
     post(bash("cp -t src a.py", cwd=CWD)), "allow", ["edit"], R(CWD, "src", "a.py")),
    # --- find -exec: the embedded command is judged; `{}` operands are
    # placeholders, not paths, so the RECORD skips them (the deny above
    # proves judgment still sees them) ---
    ("find -exec cp with a {} placeholder records nothing",
     post(bash("find . -name '*.py' -exec cp {} backup/ \\;", cwd=CWD)),
     "allow", []),
    ("find -exec rm with a {} placeholder records nothing",
     post(bash("find . -name '*.tmp' -exec rm {} +", cwd=CWD)), "allow", []),
    # --- csh-form redirect: fd duplication is not a file ---
    (">&2 logs nothing",
     post(bash("echo x >&2", cwd=CWD)), "allow", []),
    # --- git am is recorded like git apply ---
    ("git am of an ordinary patch logs the patched file",
     post(bash("git am " + q(SRC_PATCH), cwd=CWD)), "allow", ["edit"], R(CWD, "src", "app.py")),
    # --- prefixes: the wrapped command is recorded ---
    ("timeout-wrapped pytest logs exactly one test",
     post(bash("timeout 300 pytest -q", cwd=CWD)), "allow", ["test"],
     "timeout 300 pytest -q"),
    # --- touch value options are not targets ---
    ("touch -r records the stamped file only",
     post(bash("touch -r " + q(SETTINGS) + " stamp", cwd=CWD)), "allow", ["edit"],
     R(CWD, "stamp")),
    ("touch -d records the touched file, not the date",
     post(bash("touch -d '2020-01-01' x", cwd=CWD)), "allow", ["edit"], R(CWD, "x")),
    # --- sed's script is a program, not a file ---
    ("sed -i records only the edited file",
     post(bash("sed -i 's/x/y/' app.py", cwd=CWD)), "allow", ["edit"], R(CWD, "app.py")),
    # --- heredocs: the body is content ---
    ("heredoc-body mention logs only the real target",
     post(bash(HEREDOC_MENTION, cwd=CWD)), "allow", ["edit"], R(CWD, "guide.md")),
    # --- neighbor verbs: benign forms are recorded ---
    ("install into a project dir is recorded",
     post(bash("install m.py bin/m.py", cwd=CWD)), "allow", ["edit"], R(CWD, "bin", "m.py")),
    ("ln -s records the link name",
     post(bash("ln -s ../x.py link.py", cwd=CWD)), "allow", ["edit"], R(CWD, "link.py")),
    ("dd records its of= operand",
     post(bash("dd if=disk.img of=backup.img", cwd=CWD)), "allow", ["edit"],
     R(CWD, "backup.img")),
    ("dd without of= logs nothing",
     post(bash("dd if=disk.img", cwd=CWD)), "allow", []),
    ("curl -o records the saved file",
     post(bash("curl -o page.html https://example.com", cwd=CWD)), "allow", ["edit"],
     R(CWD, "page.html")),
    ("wget -O records the saved file",
     post(bash("wget -O out.html https://example.com", cwd=CWD)), "allow", ["edit"],
     R(CWD, "out.html")),
    # --- TEST_RE hardening ---
    ("indented pytest is a test run",
     post(bash("  pytest -q", cwd=CWD)), "allow", ["test"], "  pytest -q"),
    ("npm run test-e2e is a test run",
     post(bash("npm run test-e2e", cwd=CWD)), "allow", ["test"], "npm run test-e2e"),
    ("poetry run pytest is a test run",
     post(bash("poetry run pytest", cwd=CWD)), "allow", ["test"], "poetry run pytest"),
    ("pnpm exec vitest is a test run",
     post(bash("pnpm exec vitest run", cwd=CWD)), "allow", ["test"], "pnpm exec vitest run"),
    ("brace-group pytest is a test run",
     post(bash("{ pytest -q; }", cwd=CWD)), "allow", ["test"], "{ pytest -q; }"),
    ("tsc-watch is not tsc",
     post(bash("tsc-watch src", cwd=CWD)), "allow", []),
    ("a quoted npm test in a commit message is not a test run",
     post(bash('git commit -m "fix; npm test"', cwd=CWD)), "allow", []),
    # --- leading cd: judgment follows the directory ---
    ("cd into scratch keeps the write unlogged",
     post(bash("cd /tmp && echo x > scratch.txt", cwd=CWD)), "allow", []),
    ("chained leading cds compound",
     post(bash("cd sub && cd sub2 && echo x > f.txt", cwd=CWD)), "allow", ["edit"],
     R(CWD, "sub", "sub2", "f.txt")),
    # --- patch records: real stripped paths, resolved, no phantoms ---
    ("patched file is logged by its real stripped path",
     post(bash("git apply -p1 " + q(SRC_PATCH), cwd=CWD)), "allow", ["edit"],
     R(CWD, "src", "app.py")),
    ("a deletion is logged by the live side of the /dev/null pair",
     post(bash("git apply -p1 " + q(DELETE_PATCH), cwd=CWD)), "allow", ["edit"],
     R(CWD, "src", "old.py")),
    ("-p0 strips nothing, so the whole header path is the record",
     post(bash("patch -p0 < " + q(BARE_PATCH), cwd=CWD)), "allow", ["edit"],
     R(CWD, "src", "app.py")),
    ("git apply with no -p is judged at git's documented -p1",
     post(bash("git apply " + q(SRC_PATCH), cwd=CWD)), "allow", ["edit"],
     R(CWD, "src", "app.py")),
    ("patch with no -p records the fan-out minus a/-phantoms",
     post(bash("patch < " + q(SRC_PATCH), cwd=CWD)), "allow", ["edit"],
     R(CWD, "src", "app.py") + ", " + R(CWD, "app.py")),
    ("a deep header is capped to the two levels real tools use",
     post(bash("patch < " + q(DEEP_PATCH), cwd=CWD)), "allow", ["edit"],
     R(CWD, *(_DEEP_PARTS + ["f.py"]))[:120]),
    ("every patch on the line is read, not just the last",
     post(bash("git apply -p1 " + q(SRC_PATCH) + " " + q(SRC2_PATCH), cwd=CWD)),
     "allow", ["edit"], R(CWD, "src", "app.py") + ", " + R(CWD, "src", "other.py")),
    ("a rename is logged from its diff --git line, both sides",
     post(bash("git apply -p1 " + q(SRC_RENAME_PATCH), cwd=CWD)),
     "allow", ["edit"], R(CWD, "src", "old.py") + ", " + R(CWD, "src", "new.py")),
    ("a quoted header path is recorded unquoted",
     pre(bash("git apply -p1 " + q(QUOTED_RENAME_PATCH), cwd=CWD)),
     "deny", ["deny"], "control:" + R(CWD, ".claude", "hooks", "my file.py")),
    ("a quoted ---/+++ pair is recorded unquoted",
     post(bash("git apply -p1 " + q(QUOTED_PAIR_PATCH), cwd=CWD)),
     "allow", ["edit"], R(CWD, "sp file.py")),
    ("a spaced rename records the two paths it moves and no others",
     post(bash("git apply -p1 " + q(SPACED_SRC_RENAME_PATCH), cwd=CWD)),
     "allow", ["edit"],
     R(CWD, "src", "my file.py") + ", " + R(CWD, "src", "your file.py")),
    # --- the payload's cwd resolves the record and the judgment ---
    ("relative write in a control cwd is denied with the resolved path",
     pre({"tool_name": "Bash", "tool_input": {"command": "echo x > y.py"},
          "cwd": FAKE_HOOKS_CWD}),
     "deny", ["deny"], "control:" + R(FAKE_HOOKS_CWD, "y.py")),
    ("leading cd is honoured in the denial's path",
     pre(bash("cd && echo x > .claude/settings.json", cwd=CWD)), "deny", ["deny"],
     "control:" + R(HOME, ".claude", "settings.json")),
    # --- .env templates ---
    (".env.example is an ordinary edit",
     post(edit("Write", ".env.example", cwd=CWD)), "allow", ["edit"], R(CWD, ".env.example")),
    # --- stray << is not a heredoc: what follows must still be judged ---
    ("a quoted << does not eat the command",
     post(bash('grep -n "cout <<" a.cpp > r.txt\npytest -q', cwd=CWD)),
     "allow", ["edit", "test"], R(CWD, "r.txt")),
    ("a single-quoted << does not eat the command",
     post(bash("echo 'a << b' > r.txt\npytest -q", cwd=CWD)),
     "allow", ["edit", "test"], R(CWD, "r.txt")),
    ("a << in a comment does not eat the command",
     post(bash("# use << for heredocs\npytest -q", cwd=CWD)), "allow", ["test"]),
    ("an unterminated heredoc strips nothing that follows",
     post(bash("cat <<EOF; echo done\npytest -q", cwd=CWD)), "allow", ["test"],
     "cat <<EOF; echo done\npytest -q"),
    # --- /usr/bin/time value options are the prefix's, not sources ---
    ("/usr/bin/time -o with no writer logs nothing",
     post(bash("/usr/bin/time -o out.txt ls", cwd=CWD)), "allow", []),
    # --- newline separators: judgment follows the line structure ---
    ("newline cd into scratch keeps the write unlogged",
     post(bash("cd /tmp\necho x > scratch.txt", cwd=CWD)), "allow", []),
    ("a quoted newline in a commit message logs nothing",
     post(bash('git commit -m "line1\nline2"', cwd=CWD)), "allow", []),
    # --- option values are not sources or destinations ---
    ("install -m mode is not a source",
     post(bash("install -m 755 tool.sh bin/tool.sh", cwd=CWD)), "allow", ["edit"],
     R(CWD, "bin", "tool.sh")),
    ("install -d records the created directory",
     post(bash("install -d build/sub", cwd=CWD)), "allow", ["edit"], R(CWD, "build", "sub")),
    ("cp -S suffix is not a source",
     post(bash("cp -S .bak x.py y.py", cwd=CWD)), "allow", ["edit"], R(CWD, "y.py")),
    ("ln -t records the link inside the directory",
     post(bash("ln -t src x.py", cwd=CWD)), "allow", ["edit"], R(CWD, "src", "x.py")),
    ("ln into `.` does not record the cwd as an edit",
     post(bash("ln -s ../x.py .", cwd=CWD)), "allow", []),
    # --- heredoc leftovers are not tee operands ---
    ("tee before a heredoc records only its operand",
     post(bash("tee out.txt <<EOF\nx\nEOF", cwd=CWD)), "allow", ["edit"], R(CWD, "out.txt")),
    ("a path-shaped heredoc delimiter is not a tee target",
     post(bash("tee out.txt <<~/.claude/settings.json\ndata", cwd=CWD)),
     "allow", ["edit"], R(CWD, "out.txt")),
    # --- remove-log false positives ---
    ("git clean -n is a dry run, not a remove",
     post(bash("git clean -n", cwd=CWD)), "allow", []),
    ("git restore --staged touches the index, not the worktree",
     post(bash("git restore --staged app.py", cwd=CWD)), "allow", []),
    # --- TEST_RE: timeout options, and comments are not commands ---
    ("timeout with -k before the duration is a test run",
     post(bash("timeout -k 5 30 pytest", cwd=CWD)), "allow", ["test"]),
    ("timeout --foreground is a test run",
     post(bash("timeout --foreground 30 pytest -q", cwd=CWD)), "allow", ["test"]),
    ("a commented-out npm test is not a test run",
     post(bash("# if it fails then npm test again\nls -la", cwd=CWD)), "allow", []),
    ("a quoted comment mention is not a test run",
     post(bash("echo '# then npm test'", cwd=CWD)), "allow", []),
    ("a real pytest after a comment line still logs",
     post(bash("# note\npytest -q", cwd=CWD)), "allow", ["test"]),
    # --- record sentinels stay sentinels ---
    ("sed -i with no file records the sentinel unresolved",
     post(bash("sed -i s/a/b/", cwd=CWD)), "allow", ["edit"], "(in-place edit)"),
    ("dd with an empty of= records nothing",
     post(bash("dd if=x.img of=", cwd=CWD)), "allow", []),
    # --- the a/-b/ phantom drop is for patch fan-outs only ---
    ("a real directory named a/ is recorded",
     post(bash("cp x.py a/foo && cp y.py foo", cwd=CWD)), "allow", ["edit"],
     R(CWD, "a", "foo") + ", " + R(CWD, "foo")),
    # --- MSYS drive spellings, and the POSIX path they must not steal ---
    # On Windows `/c/Users/x` is Git Bash's spelling of C:\Users\x; on POSIX it
    # is an ordinary directory and has to stay one. The row asserts the
    # PLATFORM's own reading, which is the only way it can be wrong in exactly
    # one direction on each.
    ("an MSYS-spelled ordinary path is an edit at the platform's own reading",
     post(bash("echo x > " + MSYS_NOTES, cwd=CWD)), "allow", ["edit"],
     (os.path.normpath("C:\\Users\\x\\notes.txt")
      if sys.platform == "win32" else MSYS_NOTES)),
    # --- PowerShell: it decides on text and records `unparsed` ---
    ("PowerShell git status is allowed and unlogged",
     post(powershell("git status", cwd=CWD)), "allow", []),
    ("PowerShell Out-File to build.log is allowed and logged unparsed",
     post(powershell("'x' | Out-File build.log", cwd=CWD)), "allow", ["unparsed"],
     "powershell: 'x' | Out-File build.log"),
    # A write-shaped token inside a string still records `unparsed`, and that
    # is the honest answer rather than a bug worked around: there is no
    # PowerShell parser here to tell a mention from a run, and a false
    # `unparsed` costs one audit line — never a denial.
    ("PowerShell mentioning Set-Content in a string still records unparsed",
     post(powershell("Write-Output 'use Set-Content to write files'", cwd=CWD)),
     "allow", ["unparsed"],
     "powershell: Write-Output 'use Set-Content to write files'"),
    # TEST_RE is a textual pattern, so it reads a PowerShell command line as
    # willingly as a Bash one.
    ("cargo test through PowerShell logs exactly one test",
     post(powershell("cargo test", cwd=CWD)), "allow", ["test"], "cargo test"),
    ("PowerShell Remove-Item records unparsed, not remove",
     post(powershell("Remove-Item -Recurse build", cwd=CWD)), "allow", ["unparsed"],
     "powershell: Remove-Item -Recurse build"),
    ("subagent PowerShell records nothing",
     post(powershell("Set-Content x.txt -Value y", "a1", cwd=CWD)), "allow", []),
    # The deciding half writes a line only when it is the one refusing.
    ("PreToolUse PowerShell write records nothing",
     pre(powershell("'x' | Out-File build.log", cwd=CWD)), "allow", []),
    ("PowerShell control-plane denial logs exactly one deny",
     pre(powershell("Set-Content " + q(SETTINGS) + " -Value x", cwd=CWD)), "deny",
     ["deny"], "control:" + SETTINGS),
    # The doctor's canary, so /opulent:doctor step 4b has something to read.
    ("the PowerShell canary is denied and logged as a probe",
     pre(powershell("New-Item opulent-doctor-canary", cwd=CWD)), "deny", ["probe"],
     "canary:" + R(CWD, "opulent-doctor-canary")),
    # The co-occurrence denial is a `deny` like every other one — no sixth
    # event name — and its detail names the LITERALS, because there is no
    # resolved path to name: only PowerShell knows what they join into.
    ("a co-occurrence denial logs exactly one deny, naming the literals",
     pre(powershell('$dir = Join-Path $HOME ".claude" "hooks"\n'
                    'Set-Content -Path (Join-Path $dir "evil.py") -Value "x"',
                    cwd=CWD)), "deny", ["deny"], "control:.claude+hooks"),
    # The two allow-shaped halves of the same rule, on the recording event:
    # a literal-built write into plugins/data is one `unparsed` and no denial,
    # and a literal-built READ of the control plane records nothing at all.
    ("a literal-built plugins/data write records exactly one unparsed",
     post(powershell('Set-Content (Join-Path $HOME ".claude" "plugins" "data" '
                     '"state.json") -Value x', cwd=CWD)), "allow", ["unparsed"]),
    ("a literal-built control-plane read records nothing",
     post(powershell('Get-Content (Join-Path $HOME ".claude" "hooks" "x.py")',
                     cwd=CWD)), "allow", []),
    # The adjacency fix adds no event name of its own: a plugins/ write whose
    # `data` is not the next component is the same `deny`, naming `plugins`
    # as the literal it objected to.
    ("a non-adjacent plugins/data denial logs one deny naming plugins",
     pre(powershell('Set-Content -Path (Join-Path $HOME ".claude" "plugins" '
                    '"installed_plugins.json") -Value "data"', cwd=CWD)),
     "deny", ["deny"], "control:.claude+plugins"),
    # A non-string cwd used to raise inside _resolve and take the whole branch
    # out through the module's fail-open, leaving NO line — so the record half
    # is asserted too, not just the verdict.
    ("a relative write with a non-string cwd records exactly one unparsed",
     post({"tool_name": "PowerShell",
           "tool_input": {"command": "Set-Content y.py -Value x"}, "cwd": 42}),
     "allow", ["unparsed"], "powershell: Set-Content y.py -Value x"),
]

for case in TELEMETRY:
    desc, payload, want_decision, want_events = case[:4]
    want_detail = case[4] if len(case) > 4 else None
    env_extra = case[5] if len(case) > 5 else None
    got, entries = logged(payload, env_extra)
    events = [e.get("event") for e in entries]
    details = [e.get("detail") for e in entries]
    probs = schema_problems(payload, entries)
    ok = (got == want_decision and sorted(events) == sorted(want_events)
          and not probs)
    if want_detail is not None:
        ok = ok and want_detail in details
    status = "PASS" if ok else "FAIL"
    if status == "FAIL":
        failures += 1
    want = f"{want_decision}/{want_events}"
    is_ = f"{got}/{events or 'nothing'}"
    if want_detail is not None:
        want += f"/{want_detail}"
        is_ += f"/{details or 'nothing'}"
    if probs:
        is_ += f"/schema:{probs}"
    print(f"{status}  {desc}: expected={want} got={is_}")

# --- denial reasons: a redirect that does not NAME its lane is just a
# refusal, and a denial that does not name the offending path cannot be acted
# on. The reason text is part of the contract.
REASONS = [
    ("the catch-all denial points exploration at Explore",
     task("general-purpose"), None, "Explore"),
    ("the catch-all denial names an opulent lane",
     task("general-purpose"), None, "opulent:coder"),
    ("the control-plane denial names the offending path",
     edit("Write", SETTINGS), None, SETTINGS),
    ("the bash control-plane denial names the resolved path",
     bash("cd .claude && echo x > settings.json", cwd=CWD), None,
     R(CWD, ".claude", "settings.json")),
    ("the canary denial names the canary",
     bash("touch opulent-doctor-canary", cwd=CWD), None, "opulent-doctor-canary"),
]

for desc, payload, env_extra, want_text in REASONS:
    reason = run(payload, env_extra, field="permissionDecisionReason")
    ok = isinstance(reason, str) and want_text in reason
    status = "PASS" if ok else "FAIL"
    if status == "FAIL":
        failures += 1
    print(f"{status}  {desc}: expected text {want_text!r} got={reason!r}")

# --- the routing log guards itself: the audit record is not the main loop's
# to rewrite or delete, whichever tool reaches for it.
LOG_GUARD_CASES = [
    ("truncating the routing log is denied and logged",
     lambda p: bash("> " + q(p), cwd=CWD)),
    ("rm of the routing log is denied and logged",
     lambda p: bash("rm " + q(p), cwd=CWD)),
    ("Write of the routing log is denied and logged",
     lambda p: edit("Write", p, cwd=CWD)),
    ("PowerShell write to the routing log is denied and logged",
     lambda p: powershell("Set-Content " + q(p) + " -Value x", cwd=CWD)),
]

for desc, make in LOG_GUARD_CASES:
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    tf.close()
    norm = os.path.normpath(tf.name)
    payload = make(tf.name)
    env = {"OPULENT_LOG": tf.name}
    reason = run(payload, env, field="permissionDecisionReason")
    try:
        with open(tf.name, encoding="utf-8") as fh:
            entries = [json.loads(line) for line in fh if line.strip()]
    finally:
        os.unlink(tf.name)
    events = [e.get("event") for e in entries]
    details = [e.get("detail") for e in entries]
    ok = (isinstance(reason, str) and norm in reason
          and events == ["deny"] and ("log:" + norm) in details)
    status = "PASS" if ok else "FAIL"
    if status == "FAIL":
        failures += 1
    print(f"{status}  {desc}: expected=deny/['deny']/log:{norm} "
          f"got={reason!r}/{events or 'nothing'}/{details or 'nothing'}")

# One-off checks that do not fit a table, counted here so the total is the
# number of assertions that actually ran — a platform-gated case that is
# skipped is printed as SKIP and is not counted as a pass it never earned.
extra_checks = 0


def extra(desc, ok, want, got_):
    """Score and print one standalone check, in the tables' own format."""
    global failures, extra_checks
    extra_checks += 1
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {desc}: expected={want} got={got_}")


def fresh(path):
    """`path` with any previous run's file removed. The log-guard checks below
    point OPULENT_LOG at a fixed name under HOME and then assert the event
    list by EQUALITY, and the hook APPENDS — so one leftover file (an
    interrupted run, a hand probe using the same name) makes the next run fail
    on a line it did not write. Observed exactly once, from a hand probe."""
    try:
        os.unlink(path)
    except OSError:
        pass
    return path


# --- log-guard spellings: `~` and `..` must not slide past the guard, and a
# `~`-spelled OPULENT_LOG must actually receive lines (it used to write
# nothing, silently — open("~/...") is not expansion).
TILDE_LOG = "~/opulent-selftest-guard.jsonl"
# normpath, because the hook normalises and this expectation must be the same
# string it produces: on Windows expanduser returns `C:\Users\me/guard.jsonl`,
# mixed separators and all, and the un-normalised spelling matched nothing the
# hook could ever say. The hook was right; the fixture was not. NOT quoted in
# the command below either — quoting a `~` is how you stop Bash expanding it.
TILDE_REAL = fresh(os.path.normpath(os.path.expanduser(TILDE_LOG)))
got = run(bash("rm " + TILDE_LOG, cwd=CWD), {"OPULENT_LOG": TILDE_LOG})
try:
    with open(TILDE_REAL, encoding="utf-8") as fh:
        tilde_entries = [json.loads(line) for line in fh if line.strip()]
except OSError:
    tilde_entries = []
finally:
    try:
        os.unlink(TILDE_REAL)
    except OSError:
        pass
extra("a ~-spelled routing log is guarded and written",
      got == "deny" and [e.get("event") for e in tilde_entries] == ["deny"]
      and ("log:" + TILDE_REAL) in [e.get("detail") for e in tilde_entries],
      f"deny/['deny']/log:{TILDE_REAL}", f"{got}/{tilde_entries or 'nothing'}")

DOTDOT_DIR = tempfile.mkdtemp(prefix="opulent-guard-")
atexit.register(shutil.rmtree, DOTDOT_DIR, True)
DOTDOT_LOG = os.path.join(DOTDOT_DIR, "guard.jsonl")
open(DOTDOT_LOG, "w", encoding="utf-8").close()
dotdot_spelling = DOTDOT_DIR + "/sub/../guard.jsonl"
got = run(bash("echo x > " + q(dotdot_spelling), cwd=CWD), {"OPULENT_LOG": DOTDOT_LOG})
with open(DOTDOT_LOG, encoding="utf-8") as fh:
    dot_entries = [json.loads(line) for line in fh if line.strip()]
extra("a ..-spelled write to the routing log is denied",
      got == "deny" and [e.get("event") for e in dot_entries] == ["deny"],
      "deny/['deny']", f"{got}/{dot_entries or 'nothing'}")

# --- the record's half of the unquoted-backslash claim. The CASES row above
# pins the decision (allow); this pins that the audit line does not CLAIM a
# control-plane file was touched. A NOT-contains assertion is the whole reason
# this lives outside the telemetry table, which checks membership.
#
# Segments, not a substring: what Bash hands over is
# `C:Usersx.claudesettings.json`, whose BASENAME happens to contain the
# characters `.claude` while naming no .claude directory at all. The claim
# under test is "this is not a control-plane path", and a control-plane path
# is one with a `.claude` COMPONENT — so that is what is checked.
got, entries = logged(post(bash("echo x > " + WIN_UNQUOTED, cwd=CWD)))
details = [e.get("detail") or "" for e in entries]
segments = [s for d in details for s in d.replace("\\", "/").split("/")]
extra("an unquoted backslash path is never recorded as a .claude path",
      got == "allow" and ".claude" not in segments,
      "allow/no detail with a .claude path component",
      f"{got}/{details or 'nothing'}")

# --- OPULENT_LOG=os.devnull means NO log, and the guard must not turn "no
# log" into a real file to defend. os.devnull is `nul` on Windows and `nul` is
# not absolute, so the anchor-to-HOME step used to make it ~/nul and guard
# that: a write to ~/nul was refused as if it were the audit record. The
# observable half of the bug is that false denial — a line written to ~/nul
# goes to the null device on Windows, so "nothing was logged" is not something
# any check can see from outside.
#
# Windows-only, and skipped out loud elsewhere: the bug is the anchor-to-HOME
# step firing on a devnull spelling that is not ABSOLUTE, and `nul` is that
# spelling only here. On POSIX os.devnull is "/dev/null", already absolute and
# already excluded before the fix — so both rows pass there even against the
# pre-fix hook, and counting them on the Linux and macOS legs of the new
# 3-OS matrix would report coverage those legs do not have.
if sys.platform == "win32":
    _devnull_env = {"OPULENT_LOG": os.devnull}
    got = run(bash("echo x > /dev/null", cwd=CWD), _devnull_env)
    extra("a redirect to /dev/null is allowed when os.devnull IS the log",
          got == "allow", "allow", got)
    # The path the anchor-to-HOME step used to invent, written the way a Bash
    # command would: with the fix in place there is no log here to guard.
    _devnull_under_home = os.path.join(HOME, os.devnull)
    got = run(bash("echo x > " + q(_devnull_under_home), cwd=CWD), _devnull_env)
    extra("os.devnull as the log guards nothing under HOME",
          got == "allow", "allow", got)
else:
    print(f"SKIP  a redirect to /dev/null is allowed when os.devnull IS the "
          f"log: {os.devnull} is already absolute on {sys.platform}, so the "
          f"anchor-to-HOME step this pins cannot fire")
    print(f"SKIP  os.devnull as the log guards nothing under HOME: same "
          f"reason — there is no non-absolute devnull spelling on "
          f"{sys.platform}")

# --- the log self-guard reaches MSYS's drive spelling (Windows only). In Git
# Bash `/c/Users/...` IS `C:\Users\...`, and it is the spelling that shell
# hands out; is_control_plane reads segments and never cared, but the log
# guard compares a RESOLVED absolute path, and `/c/...` used to normalise to
# `\c\...` — which equals nothing, so the audit record was rewritable through
# the shell's own default. Skipped elsewhere, out loud: on POSIX `/c/Users` is
# an ordinary directory and must stay one (the telemetry row above pins that).
if sys.platform == "win32":
    MSYS_LOG = fresh(os.path.join(HOME, "opulent-selftest-msys.jsonl"))
    if MSYS_LOG[1:3] != ":\\":
        print(f"SKIP  MSYS-spelled routing log is guarded: HOME ({HOME}) is not "
              f"on a drive letter, so there is no /x/ spelling of it")
    else:
        msys_spelling = "/" + MSYS_LOG[0].lower() + "/" + MSYS_LOG[3:].replace("\\", "/")
        got = run(bash("echo x > " + msys_spelling, cwd=CWD), {"OPULENT_LOG": MSYS_LOG})
        try:
            with open(MSYS_LOG, encoding="utf-8") as fh:
                msys_entries = [json.loads(line) for line in fh if line.strip()]
        except OSError:
            msys_entries = []
        finally:
            try:
                os.unlink(MSYS_LOG)
            except OSError:
                pass
        want_detail = "log:" + os.path.normpath(MSYS_LOG)
        extra("an MSYS-spelled routing log is guarded",
              got == "deny" and [e.get("event") for e in msys_entries] == ["deny"]
              and want_detail in [e.get("detail") for e in msys_entries],
              f"deny/['deny']/{want_detail}", f"{got}/{msys_entries or 'nothing'}")
else:
    print(f"SKIP  MSYS-spelled routing log is guarded: {sys.platform} has no "
          f"MSYS drive spelling, and /c/Users there is an ordinary directory")

# --- Win32 strips trailing dots and spaces off every path component, so one
# extra `.` used to walk past all three PowerShell checks at once: _ps_pathish
# never called `hooks.` path-ish, the co-occurrence rule's literals never
# matched, and the cwd rule compared a cwd whose last component still had the
# dot on it. All four rows below were measured ALLOWED against b025c69, and
# the underlying claim was measured on a real machine: `New-Item -Path
# '...\hooks.\probe.txt'` creates the file inside the real hooks directory,
# and `'...\.claude.\hooks\evil.py'` lands in the real .claude one.
#
# Windows-only semantics, so skipped out loud elsewhere: on POSIX `hooks.` and
# `.claude.` are genuinely different directories and every row here is
# correctly ALLOWED there — counting them on the Linux and macOS legs would
# report coverage those legs do not have. The Bash spelling of the same trap
# is a CASES row instead, asserted at each platform's own reading, so the
# POSIX side is not left unpinned.
_DOT_CASES = [
    ("a bare hooks. in a .claude cwd is denied",
     powershell("Remove-Item hooks. -Recurse -Force", cwd=FAKE_CLAUDE_CWD)),
    ("a literal-built hooks. destination is denied",
     powershell('Set-Content -Path (Join-Path $HOME ".claude" "hooks.") '
                '-Value x', cwd=CWD)),
    ("a literal-built .claude. path is denied",
     powershell('Set-Content -Path (Join-Path $HOME ".claude." "hooks" '
                '"evil.py") -Value x', cwd=CWD)),
    ("a write from a hooks.-spelled control-plane cwd is denied",
     powershell("Set-Content y.py -Value x", cwd=FAKE_DOTHOOKS_CWD)),
]
if sys.platform == "win32":
    for _desc, _payload in _DOT_CASES:
        _got = run(_payload)
        extra(_desc, _got == "deny", "deny", _got)
else:
    for _desc, _ in _DOT_CASES:
        print(f"SKIP  {_desc}: on {sys.platform} a trailing dot names a "
              f"different directory, and allowing it is the correct answer")

# --- the pr-lane ledger (0.25.0) -------------------------------------------
#
# A different file with a different vocabulary, written at PostToolUse like
# everything else the hook records. Every row runs in a throwaway project
# directory carrying its own `.claude/pr-lane.json`, because that file is what
# switches the whole feature on: the last rows here are the same payloads with
# no config and with a broken one, and they must record NOTHING. An opt-in
# that records anything before you opt in is not one.
PRLANE_CFG_TEXT = json.dumps({"schema": "pr-lane/1", "base": "main",
                              "review": {"provider": "opulent:reviewer"}})
CONTRACT_MARKER = "PR-LANE CONTRACT v1"
BRIEF = (
    "Implement the unit below.\n\n" + CONTRACT_MARKER + "\n"
    "- unit: w4-a   hazard: none   branch: feat/w4-a off origin/main\n"
    "- Work only in the isolated worktree you were given.\n")
# The same brief with the marker filed off: an ordinary delegation, which is
# most of them, and which the ledger has no business recording.
UNMARKED_BRIEF = BRIEF.replace(CONTRACT_MARKER, "Implementation notes")
CODER_REPORT = ("Done. branch feat/w4-a, head SHA 1a2b3c4.\n"
                "Files changed: src/thing.rs — the guard.\n"
                "Red-then-green: assertion failed at thing.rs:42.\n")
REVIEW_PROMPT = "Review the diff.\n- unit: w4-b   hazard: none\n"


def prlane_project(config=PRLANE_CFG_TEXT):
    root = tempfile.mkdtemp(prefix="opulent-prlane-")
    atexit.register(shutil.rmtree, root, True)
    if config is not None:
        os.makedirs(os.path.join(root, ".claude"))
        with open(os.path.join(root, ".claude", "pr-lane.json"), "w",
                  encoding="utf-8") as fh:
            fh.write(config)
    return root


def prlane(payload, config=PRLANE_CFG_TEXT):
    """One payload against a throwaway pr-lane project: (decision, records).

    CLAUDE_PROJECT_DIR and the payload cwd both point at the fixture, so this
    says nothing about whichever project the suite happens to be run from."""
    root = prlane_project(config)
    body = dict(payload)
    body["cwd"] = root
    got = run(body, {"CLAUDE_PROJECT_DIR": root})
    try:
        with open(os.path.join(root, ".claude", "pr-lane", "ledger.jsonl"),
                  encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
    except OSError:
        records = []               # no ledger at all is the same as no records
    return got, records


def agent_return(lane, prompt, text, event="PostToolUse", agent=None, sid=None):
    """A Task/Agent call on the half that RECORDS, carrying the lane's report.

    Two field names are load-bearing and neither was exercised by this suite
    before 0.25.0: `tool_input.prompt` is where the contract marker rides in,
    and `tool_response` is where the lane's report comes back. The nested
    content-block shape is the one the harness sends for an agent; pr_lane.py
    walks whatever arrives rather than pinning one shape, and the `gh` rows
    below send the flat `stdout` shape to keep both readings honest."""
    body = {"tool_name": "Agent", "hook_event_name": event,
            "tool_input": {"subagent_type": lane, "prompt": prompt},
            "tool_response": {"content": [{"type": "text", "text": text}]}}
    if agent:
        body["agent_id"] = agent
    if sid:
        body["session_id"] = sid
    return body


def shell_return(cmd, out, tool="Bash"):
    return {"tool_name": tool, "hook_event_name": "PostToolUse",
            "tool_input": {"command": cmd},
            "tool_response": {"stdout": out, "stderr": "",
                              "interrupted": False}}


PR_URL = "https://github.com/example/repo/pull/74"
PR_LANE_LEDGER = [
    # --- the two agent returns the hook reads ---
    ("a coder return carrying the contract marker records one coded",
     agent_return("opulent:coder", BRIEF, CODER_REPORT), PRLANE_CFG_TEXT,
     [{"event": "coded", "unit": "w4-a", "by": "hook",
       "branch": "feat/w4-a", "sha": "1a2b3c4"}]),
    ("a mechanic return carrying the marker records one coded",
     agent_return("opulent:mechanic", BRIEF, CODER_REPORT), PRLANE_CFG_TEXT,
     [{"event": "coded", "unit": "w4-a", "by": "hook"}]),
    # The twin, and the one that matters most: the marker is the ONLY thing
    # separating a pr-lane unit from every other delegation, and a ledger that
    # recorded ordinary work would be a ledger nobody could read.
    ("a coder return with no marker records nothing",
     agent_return("opulent:coder", UNMARKED_BRIEF, CODER_REPORT),
     PRLANE_CFG_TEXT, []),
    ("a reviewer return ending SAFE records reviewed/SAFE",
     agent_return("opulent:reviewer", REVIEW_PROMPT,
                  "Two suggestions, no criticals.\nSAFE to merge"),
     PRLANE_CFG_TEXT,
     [{"event": "reviewed", "unit": "w4-b", "verdict": "SAFE"}]),
    # SAFE is a substring of NOT SAFE, so a naive check turns every rejection
    # into an approval — the one misreading in this file that could get bad
    # code merged.
    ("a reviewer return ending NOT SAFE records reviewed/NOT SAFE",
     agent_return("opulent:reviewer", REVIEW_PROMPT,
                  "One critical.\nNOT SAFE — 1 Critical"),
     PRLANE_CFG_TEXT,
     [{"event": "reviewed", "unit": "w4-b", "verdict": "NOT SAFE"}]),
    ("a reviewer return with no verdict line records unknown",
     agent_return("opulent:reviewer", REVIEW_PROMPT, "I had a look around."),
     PRLANE_CFG_TEXT, [{"event": "reviewed", "verdict": "unknown"}]),
    # ... and the verdict is read as anchored WORDS, not as substrings. The
    # substring version called `UNSAFE` an approval: SAFE is in it, NOT is
    # not. `UNSAFE` is not the charter's verdict line either way, so the
    # honest record is `unknown` rather than a guess at which one was meant.
    ("a reviewer return ending UNSAFE records unknown, never SAFE",
     agent_return("opulent:reviewer", REVIEW_PROMPT,
                  "This has a hole in it.\nUNSAFE"),
     PRLANE_CFG_TEXT, [{"event": "reviewed", "verdict": "unknown"}]),
    ("a lowercase not safe is still NOT SAFE",
     agent_return("opulent:reviewer", REVIEW_PROMPT,
                  "one critical\nnot safe to merge - 1 Critical"),
     PRLANE_CFG_TEXT, [{"event": "reviewed", "verdict": "NOT SAFE"}]),
    ("an all-caps SAFE TO MERGE is SAFE",
     agent_return("opulent:reviewer", REVIEW_PROMPT, "clean\nSAFE TO MERGE"),
     PRLANE_CFG_TEXT, [{"event": "reviewed", "verdict": "SAFE"}]),
    # Only the LAST line is the verdict. A report that discusses what would
    # have been NOT SAFE and then approves is an approval.
    ("NOT SAFE in the body does not outvote a SAFE last line",
     agent_return("opulent:reviewer", REVIEW_PROMPT,
                  "Without the guard this would be NOT SAFE.\nSAFE to merge"),
     PRLANE_CFG_TEXT, [{"event": "reviewed", "verdict": "SAFE"}]),
    # --- the gh commands ---
    ("gh pr create records pr_opened with the number from the URL",
     shell_return('gh pr create --head feat/w4-a --title "the unit" '
                  '--body-file body.md', PR_URL + "\n"),
     PRLANE_CFG_TEXT,
     [{"event": "pr_opened", "unit": "w4-a", "pr": 74,
       "branch": "feat/w4-a"}]),
    ("gh pr create through PowerShell records pr_opened too",
     shell_return("gh pr create --head feat/w4-a --fill", PR_URL + "\n",
                  tool="PowerShell"),
     PRLANE_CFG_TEXT, [{"event": "pr_opened", "unit": "w4-a", "pr": 74}]),
    # Quoted spans are blanked before the match, exactly as the routing log's
    # own test recogniser does it: a command that MENTIONS gh opens no PR.
    ("a quoted gh pr create records nothing",
     shell_return('echo "gh pr create --head feat/w4-a"',
                  "gh pr create --head feat/w4-a\n"), PRLANE_CFG_TEXT, []),
    # ... and quoting is not the only way to mention one. The token has to sit
    # at a COMMAND position: unquoted after `echo`, behind a `#`, or inside a
    # heredoc'd PR body, it is text about a PR, not a PR.
    ("an unquoted gh pr create after echo records nothing",
     shell_return("echo gh pr create --head feat/w4-a",
                  "gh pr create --head feat/w4-a\n"), PRLANE_CFG_TEXT, []),
    ("a commented-out gh pr create records nothing",
     shell_return("# gh pr create --head feat/w4-a\ngit status", ""),
     PRLANE_CFG_TEXT, []),
    ("gh pr create inside a heredoc body records nothing",
     shell_return("cat > body.md <<'EOF'\nThen run gh pr create --fill\nEOF",
                  ""), PRLANE_CFG_TEXT, []),
    # The other direction, which is why this cannot just be "starts with gh":
    # a real call reached through a prefix is a real call.
    ("gh pr create after a cd is still pr_opened",
     shell_return("cd repo && gh pr create --head feat/w4-a --fill",
                  PR_URL + "\n"),
     PRLANE_CFG_TEXT, [{"event": "pr_opened", "unit": "w4-a", "pr": 74}]),
    ("gh pr merge behind an env assignment is still merged",
     shell_return("GH_TOKEN=x gh pr merge 74 --squash", ""),
     PRLANE_CFG_TEXT, [{"event": "merged", "pr": 74}]),
    ("a settled gh pr checks records ci/pass",
     shell_return("gh pr checks 74",
                  "CI\tpass\t1m\nselftests (ubuntu-latest)\tpass\t2m\n"),
     PRLANE_CFG_TEXT, [{"event": "ci", "pr": 74, "verdict": "pass"}]),
    ("a failing gh pr checks records ci/fail",
     shell_return("gh pr checks 74",
                  "CI\tpass\t1m\nselftests (windows-latest)\tfail\t2m\n"),
     PRLANE_CFG_TEXT, [{"event": "ci", "pr": 74, "verdict": "fail"}]),
    # A run still in flight is not a result. Recording it as one would put a
    # verdict in the ledger that the ledger's whole value says was observed.
    ("a gh pr checks still running records nothing",
     shell_return("gh pr checks 74",
                  "CI\tpending\t0s\nselftests (macos-latest)\tpass\t2m\n"),
     PRLANE_CFG_TEXT, []),
    # The verdict is the STATUS COLUMN of each row and nothing else. Scanned
    # as whole text, the two rows below were failures: one because a job is
    # named `fail-fast`, one because a run URL ends in `/failures`. A green
    # PR reported as red is the reading that stops a merge that should happen.
    ("a job named fail-fast does not make a green run red",
     shell_return("gh pr checks 74",
                  "fail-fast (ubuntu-latest)\tpass\t1m\nCI\tpass\t2m\n"),
     PRLANE_CFG_TEXT, [{"event": "ci", "pr": 74, "verdict": "pass"}]),
    ("a run URL containing failures does not make a green run red",
     shell_return("gh pr checks 74",
                  "CI\tpass\t1m\thttps://github.com/e/r/runs/1/failures\n"),
     PRLANE_CFG_TEXT, [{"event": "ci", "pr": 74, "verdict": "pass"}]),
    # No rows this can read is not a verdict either. `gh` prints a one-line
    # summary in some modes, and guessing `pass` off prose is how a run
    # nobody looked at becomes a green light.
    ("gh pr checks output with no rows records nothing",
     shell_return("gh pr checks 74", "All checks were successful\n"),
     PRLANE_CFG_TEXT, []),
    ("gh pr merge records merged",
     shell_return("gh pr merge 74 --squash --delete-branch", ""),
     PRLANE_CFG_TEXT, [{"event": "merged", "pr": 74}]),
    # ... and only a merge that happened. `gh` reporting a refusal is not the
    # tool doing the thing, and `--auto` ARMS a merge for later — phase 1 has
    # no event for "armed", so the honest record is none.
    ("a gh pr merge that came back not mergeable records nothing",
     shell_return("gh pr merge 74 --squash",
                  "X Pull request #74 is not mergeable: the merge commit "
                  "cannot be cleanly created.\n"), PRLANE_CFG_TEXT, []),
    ("gh pr merge --auto records nothing",
     shell_return("gh pr merge 74 --auto --squash",
                  "Pull request #74 will be automatically merged when all "
                  "requirements are met\n"), PRLANE_CFG_TEXT, []),
    ("a gh pr create that came back a GraphQL error records nothing",
     shell_return("gh pr create --head feat/w4-a --fill",
                  "GraphQL: No commits between main and feat/w4-a "
                  "(createPullRequest)\n"), PRLANE_CFG_TEXT, []),
    ("an ordinary command in a pr-lane project records nothing",
     shell_return("cargo test", "test result: ok. 12 passed\n"),
     PRLANE_CFG_TEXT, []),
    # --- the opt-in itself, from three directions ---
    ("the same coder return records nothing with no config",
     agent_return("opulent:coder", BRIEF, CODER_REPORT), None, []),
    ("the same coder return records nothing on a malformed config",
     agent_return("opulent:coder", BRIEF, CODER_REPORT), "{ not json", []),
    ("a schema from the future records nothing",
     agent_return("opulent:coder", BRIEF, CODER_REPORT),
     '{"schema": "pr-lane/99"}', []),
    # PreToolUse decides and records nothing — the ledger obeys the same split
    # as the routing log, and for the same reason: another plugin's hook is
    # still free to deny this call.
    ("a coder return at PreToolUse records nothing",
     agent_return("opulent:coder", BRIEF, CODER_REPORT, event="PreToolUse"),
     PRLANE_CFG_TEXT, []),
    # Subagent calls are exempt from the record, here as everywhere: the
    # ledger covers the main loop, which is the only place units are run from.
    ("a coder return inside a subagent records nothing",
     agent_return("opulent:coder", BRIEF, CODER_REPORT, agent="a1"),
     PRLANE_CFG_TEXT, []),
    ("a ledger record carries the payload's session id",
     agent_return("opulent:coder", BRIEF, CODER_REPORT, sid="session-1234-abcd"),
     PRLANE_CFG_TEXT, [{"event": "coded", "sid": "session-"}]),
]

for _desc, _payload, _config, _want in PR_LANE_LEDGER:
    _got, _records = prlane(_payload, _config)
    _ok = _got == "allow" and len(_records) == len(_want)
    if _ok:
        for _rec, _exp in zip(_records, _want):
            for _k, _v in _exp.items():
                if _rec.get(_k) != _v:
                    _ok = False
            if "t" not in _rec:
                _ok = False        # every record is timestamped, like the log
    extra(_desc, _ok, f"allow/{_want}", f"{_got}/{_records or 'nothing'}")

# The ledger is not the routing log and never borrows its file: a recorded
# unit must leave the routing log exactly as it found it. Asserted with a real
# log file rather than the null device, because "no lines" is the claim.
#
# On its own this row proves only half of that — `delegate` is what the same
# payload logs with no pr-lane config at all, so it would stay green if the
# recorder had done nothing whatsoever. It is load-bearing WITH its
# neighbours: the table above has just asserted that this exact payload
# writes one `coded` line to the ledger, and this says the routing log did
# not grow a second copy of it.
_root = prlane_project()
_body = dict(agent_return("opulent:coder", BRIEF, CODER_REPORT))
_body["cwd"] = _root
_decision, _routing = logged(_body, {"CLAUDE_PROJECT_DIR": _root})
extra("a recorded pr-lane unit writes one delegate line and no more",
      _decision == "allow" and [e.get("event") for e in _routing] == ["delegate"],
      "allow/['delegate']", f"{_decision}/{[e.get('event') for e in _routing]}")

# The project root is resolved through the same MSYS mapping the routing hook
# applies to write targets. Without it, Git Bash's own default spelling of a
# Windows path — `/c/Users/...`, which is what `cwd` carries when a session is
# driven from that shell — normalises to `\c\Users\...`, the config lookup
# misses, and the whole module is silently off in the one shell this plugin's
# own project is driven from. `CLAUDE_PROJECT_DIR` is deliberately NOT set
# here: the payload's cwd is the fallback source, and it is the one that
# arrives MSYS-spelled.
_desc = "an MSYS-spelled cwd still finds the pr-lane config"
if sys.platform == "win32":
    _root = prlane_project()
    _drive, _rest = os.path.splitdrive(_root)
    _msys = "/" + _drive[0].lower() + _rest.replace("\\", "/")
    _body = dict(agent_return("opulent:coder", BRIEF, CODER_REPORT))
    _body["cwd"] = _msys
    _got = run(_body)
    try:
        with open(os.path.join(_root, ".claude", "pr-lane", "ledger.jsonl"),
                  encoding="utf-8") as fh:
            _records = [json.loads(l) for l in fh if l.strip()]
    except OSError:
        _records = []
    extra(_desc,
          _got == "allow" and [r.get("event") for r in _records] == ["coded"],
          "allow/['coded']", f"{_got}/{[r.get('event') for r in _records]}")
else:
    print(f"SKIP  {_desc}: on {sys.platform} `/c/Users/x` is an ordinary "
          f"directory and reading it as a drive would be the bug")

total = (len(CASES) + len(TELEMETRY) + len(REASONS) + len(LOG_GUARD_CASES)
         + extra_checks)
print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
