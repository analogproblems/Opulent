#!/usr/bin/env python3
"""Self-test for hooks/route-models.py — feeds payloads via stdin,
checks allow (exit 0, no output) vs deny (JSON with permissionDecision=deny).

Fixtures are built with os.path.join / tempfile so this suite tests the
platform it runs on (the old fixtures hardcoded forward slashes and could
not disagree with the code on Windows).

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


def patch_file(name, body):
    p = os.path.join(PATCH_DIR, name)
    with open(p, "w") as fh:
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
    if env_extra:
        env.update(env_extra)
    try:
        # A hook that hangs has failed: pointed at the 0.11.1 hook, a suite
        # with no timeout spun forever on the FIFO case (its ERROR() could
        # never fire). TIMEOUT matches no expectation, so it always fails.
        p = subprocess.run([sys.executable, HOOK], input=raw,
                           capture_output=True, text=True, env=env,
                           timeout=20)
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


def task(subagent, agent=None, sid=None):
    d = {"tool_name": "Task", "tool_input": {"subagent_type": subagent}}
    if agent:
        d["agent_id"] = agent
    if sid:
        d["session_id"] = sid
    return d


PROJ = os.path.join(HOME, "project", "x.py")
# Session cwd, supplied the way the real payload does it (top-level "cwd").
CWD = os.path.join(HOME, "project")
# A plugin's source repo — ordinary code that changes nothing until it is
# installed. Deliberately NOT the control plane; see route-models.py.
SRC = os.path.join(HOME, "Claude", "Fabeulous")
HOOKS_DIR = os.path.join(HOME, ".claude", "hooks")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")

# Real directories, so the cp/mv "destination is a directory" branch can be
# tested by what the filesystem says rather than by a trailing slash.
DEST_PROJ = os.path.join(PATCH_DIR, "proj")
os.makedirs(os.path.join(DEST_PROJ, ".claude"))
os.makedirs(os.path.join(DEST_PROJ, "src"))
# A cwd that sits inside a control-plane directory: a RELATIVE write there
# must be judged against the payload's cwd, not the hook process's.
FAKE_HOOKS_CWD = os.path.join(PATCH_DIR, "fake", ".claude", "hooks")

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
    ("main Bash tee plugin src",     bash("ls | tee " + os.path.join(SRC, "hooks", "x.py")),           "allow"),
    # --- the control plane: what governs the session that is running now ---
    ("main Write installed plugin",  edit("Write", os.path.join(HOME, ".claude", "plugins", "opulent", "hooks", "route-models.py")), "deny"),
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
    ("main Bash redirect settings",  bash("echo x > " + SETTINGS),                      "deny"),
    ("main Bash cp into plugins",    bash("cp x.py " + os.path.join(HOME, ".claude", "plugins", "p", "h.py")), "deny"),
    ("main Bash tee project .env",   bash("echo K=v | tee .env", cwd=CWD),              "deny"),
    # --- a patch writes the files named inside it, not the ones on the argv ---
    ("main git apply settings patch", bash("git apply " + SETTINGS_PATCH, cwd=CWD),     "deny"),
    ("main patch stdin settings",     bash("patch -p1 < " + SETTINGS_PATCH, cwd=CWD),   "deny"),
    ("main patch arg user hook",      bash("patch -p1 " + HOOK_PATCH, cwd=HOME),        "deny"),
    # -i names the patch; the positional beside it is the file being patched.
    ("main patch -i user hook",       bash("patch -i " + HOOK_PATCH + " x.py", cwd=HOME), "deny"),
    ("main patch creates .env",       bash("git apply -p1 " + ENV_PATCH, cwd=CWD),      "deny"),
    # `git apply [<patch>...]` applies every patch it is given, so the verdict
    # must not depend on which one happens to be last on the line.
    ("main git apply evil then ok",   bash("git apply " + SETTINGS_PATCH + " " + SRC_PATCH, cwd=CWD), "deny"),
    ("main git apply ok then evil",   bash("git apply " + SRC_PATCH + " " + SETTINGS_PATCH, cwd=CWD), "deny"),
    ("main git apply two ok patches", bash("git apply -p1 " + SRC_PATCH + " " + SRC2_PATCH, cwd=CWD), "allow"),
    # A rename has no ---/+++ pair; the `diff --git` line is the only header.
    ("main git apply rename to hook", bash("git apply " + RENAME_PATCH, cwd=CWD),       "deny"),
    ("main patch rename to hook",     bash("patch -p1 " + RENAME_PATCH, cwd=CWD),       "deny"),
    ("main git apply plain rename",   bash("git apply -p1 " + SRC_RENAME_PATCH, cwd=CWD), "allow"),
    # A space in the renamed file's name must not be a way out of the check,
    # quoted by git or not.
    ("main git apply spaced rename",  bash("git apply -p1 " + SPACED_RENAME_PATCH, cwd=CWD), "deny"),
    ("main git apply spaced no -p",   bash("git apply " + SPACED_RENAME_PATCH, cwd=CWD),  "deny"),
    ("main patch spaced rename",      bash("patch -p1 < " + SPACED_RENAME_PATCH, cwd=CWD), "deny"),
    ("main git apply quoted rename",  bash("git apply -p1 " + QUOTED_RENAME_PATCH, cwd=CWD), "deny"),
    ("main git apply spaced chmod",   bash("git apply -p1 " + SPACED_MODE_PATCH, cwd=CWD), "deny"),
    ("main git apply spaced src rename", bash("git apply -p1 " + SPACED_SRC_RENAME_PATCH, cwd=CWD), "allow"),
    # Quoted ---/+++ headers: the name inside the quotes is the one judged.
    ("main git apply quoted settings", bash("git apply -p1 " + QUOTED_SETTINGS_PATCH, cwd=CWD), "deny"),
    # The shell honours the LAST `<`, so that is the file actually applied.
    ("main patch double redirect",    bash("patch -p1 < " + SRC_PATCH + " < " + SETTINGS_PATCH, cwd=CWD), "deny"),
    ("main git apply double redirect", bash("git apply < " + SRC_PATCH + " < " + SETTINGS_PATCH, cwd=CWD), "deny"),
    # A pair straddling the read cap is completed, not dropped.
    ("main patch straddles read cap", bash("patch -p1 < " + STRADDLE_PATCH, cwd=CWD),   "deny"),
    # `git am` is `git apply` for format-patch output — same machinery.
    ("main git am settings patch",    bash("git am " + SETTINGS_PATCH, cwd=CWD),        "deny"),
    # --- 2026-08-13 review: each of these was ALLOWED, most of them silently.
    # Every case below was traced against the real tool before being written,
    # and every one of them fails against the hook as it stood.
    #
    # A git global option that takes a separate value used to swallow the
    # subcommand search, so the whole apply branch never ran: no denial, and no
    # log line either. The `=` spellings never had the problem, which is why
    # the bug survived: `--git-dir=x apply` works.
    ("main git -C apply settings",    bash("git -C . apply " + SETTINGS_PATCH, cwd=CWD), "deny"),
    ("main git --git-dir apply",      bash("git --git-dir .git apply " + SETTINGS_PATCH, cwd=CWD), "deny"),
    # The tool applies INTO a directory the headers never mention, so an
    # innocent header was judged while a control-plane file was rewritten —
    # and the audit line named the innocent one.
    ("main git apply --directory",    bash("git apply --directory=.claude/hooks " + SRC_PATCH, cwd=CWD), "deny"),
    ("main patch -d control dir",     bash("patch -d .claude/hooks -p1 < " + SRC_PATCH, cwd=CWD), "deny"),
    ("main patch -o control file",    bash("patch -p1 -o .claude/hooks/x.py < " + SRC_PATCH, cwd=CWD), "deny"),
    # GNU patch reads the patch from stdin when given one positional, so the
    # positional is the file being patched — consulting the redirect only when
    # no positional existed made this exact spelling allowed.
    ("main patch positional + stdin", bash("patch -p1 x.py < " + SETTINGS_PATCH, cwd=CWD), "deny"),
    # Both tools consume `./` as the component -p1 strips.
    ("main patch ./ header -p1",      bash("patch -p1 < " + DOT_PATCH, cwd=CWD),        "deny"),
    # tee and touch write EVERY operand; a decoy first argument hid the rest.
    ("main tee decoy then settings",  bash("ls | tee decoy.txt " + SETTINGS),           "deny"),
    ("main touch decoy then hook",    bash("touch decoy.txt " + os.path.join(HOOKS_DIR, "x.py")), "deny"),
    # -t puts the destination FIRST, so "last operand is the destination" was
    # exactly backwards — and the log named the source file instead.
    ("main cp -t into hooks",         bash("cp -t " + HOOKS_DIR + " evil.py"),          "deny"),
    ("main mv -t into agents",        bash("mv -t " + os.path.join(HOME, ".claude", "agents") + " a.md"), "deny"),
    # A prefix's own flag used to blank the detection of the command behind it.
    ("main sudo -u root cp hook",     bash("sudo -u root cp x.py " + os.path.join(HOOKS_DIR, "h.py")), "deny"),
    ("main nice -n 10 cp hook",       bash("nice -n 10 cp x.py " + os.path.join(HOOKS_DIR, "h.py")), "deny"),
    # ... but a prefix flag that takes NO value must not swallow the command.
    ("main sudo -n cp ordinary",      bash("sudo -n cp a.txt b.txt", cwd=CWD),          "allow"),
    # GNU sed's documented long form.
    ("main sed --in-place settings",  bash("sed --in-place s/a/b/ " + SETTINGS),        "deny"),
    ("main sed --in-place= settings", bash("sed --in-place=bak s/a/b/ " + SETTINGS),    "deny"),
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
    ("OPULENT_CODEX no longer closes", task("opulent:coder-max"), "allow", {"OPULENT_CODEX": "1"}),
    # A named pipe blocks open() forever; the size cap bounds how much is read,
    # not whether the read returns. isfile() rejects it, and the ERROR() a hang
    # would produce is what this case is really watching for.
    ("main git apply a FIFO",         bash("git apply " + FIFO_PATCH, cwd=CWD),         "allow"),
    # Fail open: an unreadable or unparseable patch must never block a session.
    ("main patch file is missing",    bash("git apply " + MISSING_PATCH, cwd=CWD),      "allow"),
    ("main patch file is not a patch", bash("patch -p1 < " + NOT_A_PATCH, cwd=CWD),     "allow"),
    # Inside a subagent the patch is nobody's business — the blanket allow wins.
    ("subagent git apply settings",   bash("git apply " + SETTINGS_PATCH, "a1", cwd=CWD), "allow"),
    ("subagent patch stdin settings", bash("patch -p1 < " + SETTINGS_PATCH, "a1", cwd=CWD), "allow"),
    ("subagent patch arg user hook",  bash("patch -p1 " + HOOK_PATCH, "a1", cwd=HOME),  "allow"),
    ("subagent patch -i user hook",   bash("patch -i " + HOOK_PATCH + " x.py", "a1", cwd=HOME), "allow"),
    ("subagent patch creates .env",   bash("git apply -p1 " + ENV_PATCH, "a1", cwd=CWD), "allow"),
    ("subagent git apply two patches", bash("git apply " + SETTINGS_PATCH + " " + SRC_PATCH, "a1", cwd=CWD), "allow"),
    ("subagent git apply rename",     bash("git apply " + RENAME_PATCH, "a1", cwd=CWD), "allow"),
    ("subagent spaced rename",        bash("git apply -p1 " + SPACED_RENAME_PATCH, "a1", cwd=CWD), "allow"),
    ("subagent quoted rename",        bash("git apply -p1 " + QUOTED_RENAME_PATCH, "a1", cwd=CWD), "allow"),
    ("subagent patch double redirect", bash("patch -p1 < " + SRC_PATCH + " < " + SETTINGS_PATCH, "a1", cwd=CWD), "allow"),
    ("subagent git am settings",      bash("git am " + SETTINGS_PATCH, "a1", cwd=CWD),  "allow"),
    # --- writers inside shell compounds: reserved words are not commands ---
    ("main for-loop cp into hooks",   bash("for f in a.py b.py; do cp $f " + HOOKS_DIR + "/; done"), "deny"),
    ("main if/then cp into hooks",    bash("if true; then cp x.py " + os.path.join(HOOKS_DIR, "x.py") + "; fi"), "deny"),
    ("main brace group touch hook",   bash("{ touch " + os.path.join(HOOKS_DIR, "t.py") + "; }"), "deny"),
    ("main while/do tee settings",    bash("while read l; do echo $l | tee " + SETTINGS + "; done"), "deny"),
    ("main case arm cp into hooks",   bash("case $1 in x) echo ok ;; y) cp f.py " + os.path.join(HOOKS_DIR, "h.py") + " ;; esac"), "deny"),
    # ... while words that merely LOOK like reserved words stay data.
    ("main echo do-mention (no FP)",  bash("echo do a barrel roll > /tmp/x"),           "allow"),
    # --- cp/mv with a directory destination classify the landed file ---
    ("main cp settings into ~/.claude/", bash("cp settings.json " + os.path.join(HOME, ".claude") + os.sep), "deny"),
    ("main cp settings into real dir",   bash("cp settings.json .claude", cwd=DEST_PROJ), "deny"),
    ("main xargs cp -t into hooks",      bash("ls *.py | xargs cp -t " + HOOKS_DIR),    "deny"),
    # --- find -exec runs the command it generates ---
    ("main find -exec cp into hooks",    bash("find . -name '*.py' -exec cp {} " + HOOKS_DIR + "/ \\;"), "deny"),
    # --- csh-form redirect ---
    ("main >& into settings",            bash("make build >& " + SETTINGS),             "deny"),
    ("main >&2 is not a file",           bash("echo x >&2"),                            "allow"),
    # --- prefix gaps: the wrapped command is still the command ---
    ("main timeout cp into hooks",       bash("timeout 30 cp x.py " + os.path.join(HOOKS_DIR, "h.py")), "deny"),
    ("main nohup tee settings",          bash("nohup tee " + SETTINGS),                 "deny"),
    ("main setsid cp into hooks",        bash("setsid cp x.py " + os.path.join(HOOKS_DIR, "h.py")), "deny"),
    ("main stdbuf tee settings",         bash("stdbuf -o0 tee " + SETTINGS),            "deny"),
    ("main sudo --user cp hook",         bash("sudo --user root cp x.py " + os.path.join(HOOKS_DIR, "h.py")), "deny"),
    ("main xargs -a cp -t hooks",        bash("xargs -a list.txt cp -t " + HOOKS_DIR),  "deny"),
    # --- touch value options are not targets ---
    ("main touch -r ref is not target",  bash("touch -r " + SETTINGS + " stamp", cwd=CWD), "allow"),
    # --- heredoc bodies are content, not commands ---
    ("main heredoc mentions settings",   bash(HEREDOC_MENTION, cwd=CWD),                "allow"),
    ("main redirect then heredoc",       bash("cat > " + SETTINGS + " <<EOF\nx\nEOF"),  "deny"),
    ("main heredoc then redirect",       bash("cat <<EOF > " + SETTINGS + "\nx\nEOF"),  "deny"),
    # ... and a stray `<<` that is NOT a heredoc must not eat what follows.
    ("main here-string then cp",         bash('read -r a b <<< "$line"\ncp x.py ' + os.path.join(HOOKS_DIR, "x.py")), "deny"),
    ("main arithmetic shift then cp",    bash("n=$((1 << 3))\ncp x.py " + os.path.join(HOOKS_DIR, "x.py")), "deny"),
    # --- /usr/bin/time takes value options; the wrapped command is judged ---
    ("main /usr/bin/time -o cp hook",    bash("/usr/bin/time -o times.txt cp evil.py " + os.path.join(HOOKS_DIR, "h.py")), "deny"),
    ("main time keyword cp hook",        bash("time cp x.py " + os.path.join(HOOKS_DIR, "h.py")), "deny"),
    # --- newline is a command separator, like `;` ---
    ("main newline cd then settings",    bash("cd .claude\necho x > settings.json", cwd=CWD), "deny"),
    ("main multi-line for-loop cp",      bash("for f in a.py b.py\ndo\ncp $f " + HOOKS_DIR + "/\ndone"), "deny"),
    ("main comment then cp hook",        bash("# staging the hook\ncp x.py " + os.path.join(HOOKS_DIR, "x.py")), "deny"),
    # --- install writes directories with -d, and via -t ---
    ("main install -d control dir",      bash("install -d " + HOOKS_DIR),               "deny"),
    ("main install -t into hooks",       bash("install -t " + HOOKS_DIR + " x.py"),     "deny"),
    # --- ln -t targets the directory, not the last operand ---
    ("main ln -t into hooks",            bash("ln -t " + HOOKS_DIR + " x.py"),          "deny"),
    # --- accident-shaped neighbor verbs ---
    ("main install into hooks",          bash("install m.py " + os.path.join(HOOKS_DIR, "m.py")), "deny"),
    ("main ln -sf into hooks",           bash("ln -sf x.py " + os.path.join(HOOKS_DIR, "link.py")), "deny"),
    ("main dd of= into hooks",           bash("dd if=/dev/zero of=" + os.path.join(HOOKS_DIR, "h.py")), "deny"),
    ("main curl -o into hooks",          bash("curl -o " + os.path.join(HOOKS_DIR, "x.py") + " https://example.com"), "deny"),
    ("main wget -O into hooks",          bash("wget -O " + os.path.join(HOOKS_DIR, "x.py") + " https://example.com"), "deny"),
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
    ("main Task->coder-max",         task("opulent:coder-max"),                         "allow"),
    ("main Task->mechanic",          task("opulent:mechanic"),                          "allow"),
    ("main Task->scribe",            task("opulent:scribe"),                            "allow"),
    ("main Task->test-runner",       task("opulent:test-runner"),                       "allow"),
    # Lanes retired in 0.15.0 are not special-cased: an unregistered opulent:*
    # name is an ordinary delegation the harness will reject on its own, and
    # the hook inventing a denial for it would be a second source of truth.
    ("main Task->retired scout",     task("opulent:scout"),                             "allow"),
    ("main Task->retired ui-checker", task("opulent:ui-checker"),                       "allow"),
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
        with open(f.name) as fh:
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
    # --- the record's staples ---
    ("main edit logs exactly one edit",
     edit("Edit", os.path.join(CWD, "src", "app.py"), cwd=CWD),
     "allow", ["edit"], R(CWD, "src", "app.py")),
    ("main bash write logs exactly one edit",
     bash("echo hi > notes.txt", cwd=CWD), "allow", ["edit"], R(CWD, "notes.txt")),
    ("main test run logs exactly one test",
     bash("pytest -q", cwd=CWD), "allow", ["test"], "pytest -q"),
    ("a write AND a test run log both events",
     bash("pytest > results.txt", cwd=CWD), "allow", ["edit", "test"],
     R(CWD, "results.txt")),
    ("scratch write is not logged",
     edit("Write", os.path.join(TMP, "scratch.txt"), cwd=CWD), "allow", []),
    ("bash scratch redirect is not logged",
     bash("echo x > " + os.path.join(TMP, "opulent-scratch.txt"), cwd=CWD),
     "allow", []),
    ("bash write into plans is not logged",
     bash("echo x > " + os.path.join(HOME, ".claude", "plans", "p.md"), cwd=CWD),
     "allow", []),
    ("subagent edit is not logged",
     edit("Edit", PROJ, "a1"), "allow", []),
    ("control-plane denial logs exactly one deny",
     edit("Write", SETTINGS), "deny", ["deny"], "control:" + SETTINGS),
    ("the canary is denied and logged as a probe, with its path",
     bash("touch opulent-doctor-canary", cwd=CWD), "deny", ["probe"],
     "canary:" + R(CWD, "opulent-doctor-canary")),
    # --- delegation: the log's dominant event, asserted at last ---
    ("Task delegation logs exactly one delegate",
     task("opulent:coder"), "allow", ["delegate"], "opulent:coder"),
    ("Agent-tool delegation logs exactly one delegate",
     {"tool_name": "Agent", "tool_input": {"subagent_type": "opulent:mechanic"}},
     "allow", ["delegate"], "opulent:mechanic"),
    ("subagent Task logs nothing",
     task("opulent:coder", "a7"), "allow", []),
    ("a session id in the payload lands on the log line",
     task("opulent:coder", sid=SID), "allow", ["delegate"], "opulent:coder"),
    ("session id on a bash edit line too",
     bash("echo hi > notes.txt", cwd=CWD, sid=SID), "allow", ["edit"],
     R(CWD, "notes.txt")),
    # --- a malformed spawn payload cannot reach a real agent, so allow is
    # right — but it must still leave a record. subagent_type is not
    # guaranteed to be a string; these pin what the log shows when it isn't.
    ("list subagent_type still logs a delegate",
     task(["opulent:coder-max"]), "allow", ["delegate"],
     "['opulent:coder-max']"),
    ("dict subagent_type still logs a delegate",
     task({"a": 1}), "allow", ["delegate"], "{'a': 1}"),
    # int already worked before this fix — _log's own str() coercion covered
    # it — so this pins existing behavior rather than a new one.
    ("int subagent_type already logs a delegate",
     task(12345), "allow", ["delegate"], "12345"),
    # --- denial events carry their kind, not `probe` ---
    ("catch-all denial logs event deny",
     task("general-purpose"), "deny", ["deny"], "catchall:general-purpose"),
    # --- MultiEdit / NotebookEdit are guarded and recorded like Edit ---
    ("NotebookEdit control-plane deny",
     {"tool_name": "NotebookEdit",
      "tool_input": {"notebook_path": os.path.join(HOOKS_DIR, "x.ipynb")}},
     "deny", ["deny"], "control:" + os.path.join(HOOKS_DIR, "x.ipynb")),
    ("NotebookEdit ordinary write logs an edit",
     {"tool_name": "NotebookEdit",
      "tool_input": {"notebook_path": os.path.join(CWD, "nb.ipynb")}, "cwd": CWD},
     "allow", ["edit"], R(CWD, "nb.ipynb")),
    ("MultiEdit control-plane deny",
     edit("MultiEdit", SETTINGS), "deny", ["deny"], "control:" + SETTINGS),
    ("MultiEdit ordinary write logs an edit",
     edit("MultiEdit", os.path.join(CWD, "m.py"), cwd=CWD), "allow", ["edit"],
     R(CWD, "m.py")),
    # --- a falsy path is nothing: no judgment, no record ---
    ("Write with empty file_path logs nothing",
     edit("Write", ""), "allow", []),
    ("Edit with no file_path at all logs nothing",
     {"tool_name": "Edit", "tool_input": {}}, "allow", []),
    # --- an unparseable command still leaves a line ---
    ("unbalanced quote logs unparsed",
     bash("echo it's here > notes.txt", cwd=CWD), "allow", ["unparsed"],
     "echo it's here > notes.txt"),
    ("balanced apostrophe parses normally",
     bash('echo "it\'s" > notes.txt', cwd=CWD), "allow", ["edit"],
     R(CWD, "notes.txt")),
    # --- deletions become visible ---
    ("rm logs a remove with resolved operands",
     bash("rm src/old.py", cwd=CWD), "allow", ["remove"], R(CWD, "src", "old.py")),
    ("rm of several operands records them all",
     bash("rm -rf build dist", cwd=CWD), "allow", ["remove"],
     R(CWD, "build") + ", " + R(CWD, "dist")),
    ("rm of scratch is not logged",
     bash("rm " + os.path.join(TMP, "x.tmp"), cwd=CWD), "allow", []),
    ("git reset --hard logs a remove",
     bash("git reset --hard", cwd=CWD), "allow", ["remove"], "git reset --hard"),
    ("git clean logs a remove",
     bash("git clean -fd", cwd=CWD), "allow", ["remove"], "git clean -fd"),
    ("git checkout -- logs a remove",
     bash("git checkout -- .", cwd=CWD), "allow", ["remove"], "git checkout -- ."),
    ("git restore logs a remove",
     bash("git restore app.py", cwd=CWD), "allow", ["remove"], "git restore app.py"),
    ("git stash drop logs a remove",
     bash("git stash drop", cwd=CWD), "allow", ["remove"], "git stash drop"),
    ("plain git checkout of a branch is not a remove",
     bash("git checkout main", cwd=CWD), "allow", []),
    ("git stash list is not a remove",
     bash("git stash list", cwd=CWD), "allow", []),
    ("mv records source and destination",
     bash("mv old.py new.py", cwd=CWD), "allow", ["edit"],
     R(CWD, "old.py") + " -> " + R(CWD, "new.py")),
    # --- reserved words / compounds: the twin false-positives log nothing ---
    ("echo do-mention logs nothing",
     bash("echo do a barrel roll > /tmp/x", cwd=CWD), "allow", []),
    ("quoted then-cp in a commit message logs nothing",
     bash('git commit -m "then cp a b"', cwd=CWD), "allow", []),
    # --- cp/mv directory destinations record the landed file ---
    ("cp into an existing dir records dir/basename",
     bash("cp a.py src/", cwd=CWD), "allow", ["edit"], R(CWD, "src", "a.py")),
    # Three or more operands can only mean a directory destination — no
    # trailing slash and no filesystem check needed. (The isdir arm is pinned
    # by the "cp settings into real dir" deny above; a real dir under the
    # suite's tempdir would be scratch-filtered out of the record here.)
    ("cp of two sources into a dir records both landed files",
     bash("cp a.py b.py src", cwd=CWD), "allow", ["edit"],
     R(CWD, "src", "a.py") + ", " + R(CWD, "src", "b.py")),
    ("cp -t detail names the destination, not the source",
     bash("cp -t src a.py", cwd=CWD), "allow", ["edit"], R(CWD, "src", "a.py")),
    # --- find -exec: the embedded command is judged; `{}` operands are
    # placeholders, not paths, so the RECORD skips them (the deny above
    # proves judgment still sees them) ---
    ("find -exec cp with a {} placeholder records nothing",
     bash("find . -name '*.py' -exec cp {} backup/ \\;", cwd=CWD),
     "allow", []),
    ("find -exec rm with a {} placeholder records nothing",
     bash("find . -name '*.tmp' -exec rm {} +", cwd=CWD), "allow", []),
    # --- csh-form redirect: fd duplication is not a file ---
    (">&2 logs nothing",
     bash("echo x >&2", cwd=CWD), "allow", []),
    # --- git am is recorded like git apply ---
    ("git am of an ordinary patch logs the patched file",
     bash("git am " + SRC_PATCH, cwd=CWD), "allow", ["edit"], R(CWD, "src", "app.py")),
    # --- prefixes: the wrapped command is recorded ---
    ("timeout-wrapped pytest logs exactly one test",
     bash("timeout 300 pytest -q", cwd=CWD), "allow", ["test"],
     "timeout 300 pytest -q"),
    # --- touch value options are not targets ---
    ("touch -r records the stamped file only",
     bash("touch -r " + SETTINGS + " stamp", cwd=CWD), "allow", ["edit"],
     R(CWD, "stamp")),
    ("touch -d records the touched file, not the date",
     bash("touch -d '2020-01-01' x", cwd=CWD), "allow", ["edit"], R(CWD, "x")),
    # --- sed's script is a program, not a file ---
    ("sed -i records only the edited file",
     bash("sed -i 's/x/y/' app.py", cwd=CWD), "allow", ["edit"], R(CWD, "app.py")),
    # --- heredocs: the body is content ---
    ("heredoc-body mention logs only the real target",
     bash(HEREDOC_MENTION, cwd=CWD), "allow", ["edit"], R(CWD, "guide.md")),
    # --- neighbor verbs: benign forms are recorded ---
    ("install into a project dir is recorded",
     bash("install m.py bin/m.py", cwd=CWD), "allow", ["edit"], R(CWD, "bin", "m.py")),
    ("ln -s records the link name",
     bash("ln -s ../x.py link.py", cwd=CWD), "allow", ["edit"], R(CWD, "link.py")),
    ("dd records its of= operand",
     bash("dd if=disk.img of=backup.img", cwd=CWD), "allow", ["edit"],
     R(CWD, "backup.img")),
    ("dd without of= logs nothing",
     bash("dd if=disk.img", cwd=CWD), "allow", []),
    ("curl -o records the saved file",
     bash("curl -o page.html https://example.com", cwd=CWD), "allow", ["edit"],
     R(CWD, "page.html")),
    ("wget -O records the saved file",
     bash("wget -O out.html https://example.com", cwd=CWD), "allow", ["edit"],
     R(CWD, "out.html")),
    # --- TEST_RE hardening ---
    ("indented pytest is a test run",
     bash("  pytest -q", cwd=CWD), "allow", ["test"], "  pytest -q"),
    ("npm run test-e2e is a test run",
     bash("npm run test-e2e", cwd=CWD), "allow", ["test"], "npm run test-e2e"),
    ("poetry run pytest is a test run",
     bash("poetry run pytest", cwd=CWD), "allow", ["test"], "poetry run pytest"),
    ("pnpm exec vitest is a test run",
     bash("pnpm exec vitest run", cwd=CWD), "allow", ["test"], "pnpm exec vitest run"),
    ("brace-group pytest is a test run",
     bash("{ pytest -q; }", cwd=CWD), "allow", ["test"], "{ pytest -q; }"),
    ("tsc-watch is not tsc",
     bash("tsc-watch src", cwd=CWD), "allow", []),
    ("a quoted npm test in a commit message is not a test run",
     bash('git commit -m "fix; npm test"', cwd=CWD), "allow", []),
    # --- leading cd: judgment follows the directory ---
    ("cd into scratch keeps the write unlogged",
     bash("cd /tmp && echo x > scratch.txt", cwd=CWD), "allow", []),
    ("chained leading cds compound",
     bash("cd sub && cd sub2 && echo x > f.txt", cwd=CWD), "allow", ["edit"],
     R(CWD, "sub", "sub2", "f.txt")),
    # --- patch records: real stripped paths, resolved, no phantoms ---
    ("patched file is logged by its real stripped path",
     bash("git apply -p1 " + SRC_PATCH, cwd=CWD), "allow", ["edit"],
     R(CWD, "src", "app.py")),
    ("a deletion is logged by the live side of the /dev/null pair",
     bash("git apply -p1 " + DELETE_PATCH, cwd=CWD), "allow", ["edit"],
     R(CWD, "src", "old.py")),
    ("-p0 strips nothing, so the whole header path is the record",
     bash("patch -p0 < " + BARE_PATCH, cwd=CWD), "allow", ["edit"],
     R(CWD, "src", "app.py")),
    ("git apply with no -p is judged at git's documented -p1",
     bash("git apply " + SRC_PATCH, cwd=CWD), "allow", ["edit"],
     R(CWD, "src", "app.py")),
    ("patch with no -p records the fan-out minus a/-phantoms",
     bash("patch < " + SRC_PATCH, cwd=CWD), "allow", ["edit"],
     R(CWD, "src", "app.py") + ", " + R(CWD, "app.py")),
    ("a deep header is capped to the two levels real tools use",
     bash("patch < " + DEEP_PATCH, cwd=CWD), "allow", ["edit"],
     R(CWD, *(_DEEP_PARTS + ["f.py"]))[:120]),
    ("every patch on the line is read, not just the last",
     bash("git apply -p1 " + SRC_PATCH + " " + SRC2_PATCH, cwd=CWD),
     "allow", ["edit"], R(CWD, "src", "app.py") + ", " + R(CWD, "src", "other.py")),
    ("a rename is logged from its diff --git line, both sides",
     bash("git apply -p1 " + SRC_RENAME_PATCH, cwd=CWD),
     "allow", ["edit"], R(CWD, "src", "old.py") + ", " + R(CWD, "src", "new.py")),
    ("a quoted header path is recorded unquoted",
     bash("git apply -p1 " + QUOTED_RENAME_PATCH, cwd=CWD),
     "deny", ["deny"], "control:" + R(CWD, ".claude", "hooks", "my file.py")),
    ("a quoted ---/+++ pair is recorded unquoted",
     bash("git apply -p1 " + QUOTED_PAIR_PATCH, cwd=CWD),
     "allow", ["edit"], R(CWD, "sp file.py")),
    ("a spaced rename records the two paths it moves and no others",
     bash("git apply -p1 " + SPACED_SRC_RENAME_PATCH, cwd=CWD),
     "allow", ["edit"],
     R(CWD, "src", "my file.py") + ", " + R(CWD, "src", "your file.py")),
    # --- the payload's cwd resolves the record and the judgment ---
    ("relative write in a control cwd is denied with the resolved path",
     {"tool_name": "Bash", "tool_input": {"command": "echo x > y.py"},
      "cwd": FAKE_HOOKS_CWD},
     "deny", ["deny"], "control:" + R(FAKE_HOOKS_CWD, "y.py")),
    ("leading cd is honoured in the denial's path",
     bash("cd && echo x > .claude/settings.json", cwd=CWD), "deny", ["deny"],
     "control:" + R(HOME, ".claude", "settings.json")),
    # --- .env templates ---
    (".env.example is an ordinary edit",
     edit("Write", ".env.example", cwd=CWD), "allow", ["edit"], R(CWD, ".env.example")),
    # --- stray << is not a heredoc: what follows must still be judged ---
    ("a quoted << does not eat the command",
     bash('grep -n "cout <<" a.cpp > r.txt\npytest -q', cwd=CWD),
     "allow", ["edit", "test"], R(CWD, "r.txt")),
    ("a single-quoted << does not eat the command",
     bash("echo 'a << b' > r.txt\npytest -q", cwd=CWD),
     "allow", ["edit", "test"], R(CWD, "r.txt")),
    ("a << in a comment does not eat the command",
     bash("# use << for heredocs\npytest -q", cwd=CWD), "allow", ["test"]),
    ("an unterminated heredoc strips nothing that follows",
     bash("cat <<EOF; echo done\npytest -q", cwd=CWD), "allow", ["test"],
     "cat <<EOF; echo done\npytest -q"),
    # --- /usr/bin/time value options are the prefix's, not sources ---
    ("/usr/bin/time -o with no writer logs nothing",
     bash("/usr/bin/time -o out.txt ls", cwd=CWD), "allow", []),
    # --- newline separators: judgment follows the line structure ---
    ("newline cd into scratch keeps the write unlogged",
     bash("cd /tmp\necho x > scratch.txt", cwd=CWD), "allow", []),
    ("a quoted newline in a commit message logs nothing",
     bash('git commit -m "line1\nline2"', cwd=CWD), "allow", []),
    # --- option values are not sources or destinations ---
    ("install -m mode is not a source",
     bash("install -m 755 tool.sh bin/tool.sh", cwd=CWD), "allow", ["edit"],
     R(CWD, "bin", "tool.sh")),
    ("install -d records the created directory",
     bash("install -d build/sub", cwd=CWD), "allow", ["edit"], R(CWD, "build", "sub")),
    ("cp -S suffix is not a source",
     bash("cp -S .bak x.py y.py", cwd=CWD), "allow", ["edit"], R(CWD, "y.py")),
    ("ln -t records the link inside the directory",
     bash("ln -t src x.py", cwd=CWD), "allow", ["edit"], R(CWD, "src", "x.py")),
    ("ln into `.` does not record the cwd as an edit",
     bash("ln -s ../x.py .", cwd=CWD), "allow", []),
    # --- heredoc leftovers are not tee operands ---
    ("tee before a heredoc records only its operand",
     bash("tee out.txt <<EOF\nx\nEOF", cwd=CWD), "allow", ["edit"], R(CWD, "out.txt")),
    ("a path-shaped heredoc delimiter is not a tee target",
     bash("tee out.txt <<~/.claude/settings.json\ndata", cwd=CWD),
     "allow", ["edit"], R(CWD, "out.txt")),
    # --- remove-log false positives ---
    ("git clean -n is a dry run, not a remove",
     bash("git clean -n", cwd=CWD), "allow", []),
    ("git restore --staged touches the index, not the worktree",
     bash("git restore --staged app.py", cwd=CWD), "allow", []),
    # --- TEST_RE: timeout options, and comments are not commands ---
    ("timeout with -k before the duration is a test run",
     bash("timeout -k 5 30 pytest", cwd=CWD), "allow", ["test"]),
    ("timeout --foreground is a test run",
     bash("timeout --foreground 30 pytest -q", cwd=CWD), "allow", ["test"]),
    ("a commented-out npm test is not a test run",
     bash("# if it fails then npm test again\nls -la", cwd=CWD), "allow", []),
    ("a quoted comment mention is not a test run",
     bash("echo '# then npm test'", cwd=CWD), "allow", []),
    ("a real pytest after a comment line still logs",
     bash("# note\npytest -q", cwd=CWD), "allow", ["test"]),
    # --- record sentinels stay sentinels ---
    ("sed -i with no file records the sentinel unresolved",
     bash("sed -i s/a/b/", cwd=CWD), "allow", ["edit"], "(in-place edit)"),
    ("dd with an empty of= records nothing",
     bash("dd if=x.img of=", cwd=CWD), "allow", []),
    # --- the a/-b/ phantom drop is for patch fan-outs only ---
    ("a real directory named a/ is recorded",
     bash("cp x.py a/foo && cp y.py foo", cwd=CWD), "allow", ["edit"],
     R(CWD, "a", "foo") + ", " + R(CWD, "foo")),
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
     lambda p: bash("> " + p, cwd=CWD)),
    ("rm of the routing log is denied and logged",
     lambda p: bash("rm " + p, cwd=CWD)),
    ("Write of the routing log is denied and logged",
     lambda p: edit("Write", p, cwd=CWD)),
]

for desc, make in LOG_GUARD_CASES:
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    tf.close()
    norm = os.path.normpath(tf.name)
    payload = make(tf.name)
    env = {"OPULENT_LOG": tf.name}
    reason = run(payload, env, field="permissionDecisionReason")
    try:
        with open(tf.name) as fh:
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

# --- log-guard spellings: `~` and `..` must not slide past the guard, and a
# `~`-spelled OPULENT_LOG must actually receive lines (it used to write
# nothing, silently — open("~/...") is not expansion).
TILDE_LOG = "~/opulent-selftest-guard.jsonl"
TILDE_REAL = os.path.expanduser(TILDE_LOG)
got = run(bash("rm " + TILDE_LOG, cwd=CWD), {"OPULENT_LOG": TILDE_LOG})
try:
    with open(TILDE_REAL) as fh:
        tilde_entries = [json.loads(line) for line in fh if line.strip()]
except OSError:
    tilde_entries = []
finally:
    try:
        os.unlink(TILDE_REAL)
    except OSError:
        pass
ok = (got == "deny" and [e.get("event") for e in tilde_entries] == ["deny"]
      and ("log:" + TILDE_REAL) in [e.get("detail") for e in tilde_entries])
status = "PASS" if ok else "FAIL"
if status == "FAIL":
    failures += 1
print(f"{status}  a ~-spelled routing log is guarded and written: "
      f"expected=deny/['deny']/log:{TILDE_REAL} got={got}/{tilde_entries or 'nothing'}")

DOTDOT_DIR = tempfile.mkdtemp(prefix="opulent-guard-")
atexit.register(shutil.rmtree, DOTDOT_DIR, True)
DOTDOT_LOG = os.path.join(DOTDOT_DIR, "guard.jsonl")
open(DOTDOT_LOG, "w").close()
dotdot_spelling = DOTDOT_DIR + "/sub/../guard.jsonl"
got = run(bash("echo x > " + dotdot_spelling, cwd=CWD), {"OPULENT_LOG": DOTDOT_LOG})
with open(DOTDOT_LOG) as fh:
    dot_entries = [json.loads(line) for line in fh if line.strip()]
ok = (got == "deny" and [e.get("event") for e in dot_entries] == ["deny"])
status = "PASS" if ok else "FAIL"
if status == "FAIL":
    failures += 1
print(f"{status}  a ..-spelled write to the routing log is denied: "
      f"expected=deny/['deny'] got={got}/{dot_entries or 'nothing'}")

LOG_GUARD_EXTRA = 2

total = (len(CASES) + len(TELEMETRY) + len(REASONS) + len(LOG_GUARD_CASES)
         + LOG_GUARD_EXTRA)
print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
