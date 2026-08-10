#!/usr/bin/env python3
"""Self-test for hooks/route-models.py — feeds payloads via stdin,
checks allow (exit 0, no output) vs deny (JSON with permissionDecision=deny).

Fixtures are built with os.path.join / tempfile so this suite tests the
platform it runs on (the old fixtures hardcoded forward slashes and could
not disagree with the code on Windows)."""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = str(Path(__file__).resolve().parent.parent / "hooks" / "route-models.py")
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
    # Both session dials are cleared, so a suite run inherits neither: an
    # OPULENT_ECO left set in the shell would otherwise turn the ordinary
    # coder-lane case into an eco case without saying so.
    env.pop("OPULENT_OFF", None)
    env.pop("OPULENT_ECO", None)
    if env_extra:
        env.update(env_extra)
    p = subprocess.run([sys.executable, HOOK], input=raw,
                       capture_output=True, text=True, env=env)
    if p.returncode != 0:
        return f"ERROR(exit={p.returncode}, stderr={p.stderr.strip()})"
    out = p.stdout.strip()
    if not out:
        return "allow"
    try:
        d = json.loads(out)["hookSpecificOutput"]
    except Exception:
        return f"ERROR(bad output: {out!r})"
    if field not in d:
        # Deliberately quotes nothing of the payload: an error string that
        # embedded the output would carry the reason text inside it, and a
        # `want_text in reason` check would pass on a hook whose output key
        # was misspelled — an assertion satisfied by its own failure message.
        return f"ERROR(missing {field})"
    return d[field]


def bash(cmd, agent=None, cwd=None):
    d = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    if agent:
        d["agent_id"] = agent
    if cwd:
        d["cwd"] = cwd
    return d


def edit(tool, path, agent=None, cwd=None):
    d = {"tool_name": tool, "tool_input": {"file_path": path}}
    if agent:
        d["agent_id"] = agent
    if cwd:
        d["cwd"] = cwd
    return d


def task(subagent, agent=None):
    d = {"tool_name": "Task", "tool_input": {"subagent_type": subagent}}
    if agent:
        d["agent_id"] = agent
    return d


PROJ = os.path.join(HOME, "project", "x.py")
# Session cwd, supplied the way the real payload does it (top-level "cwd").
CWD = os.path.join(HOME, "project")
# A plugin's source repo — ordinary code that changes nothing until it is
# installed. Deliberately NOT the control plane; see route-models.py.
SRC = os.path.join(HOME, "Claude", "Fabeulous")

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
MISSING_PATCH = os.path.join(PATCH_DIR, "absent.patch")
NOT_A_PATCH = patch_file("notes.txt", (
    "shopping list\n"
    "--- groceries ---\n"
    "- milk\n"
    "+ eggs\n"))

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
    ("main Write user settings",     edit("Write", os.path.join(HOME, ".claude", "settings.json")),    "deny"),
    ("main Write settings.local",    edit("Write", os.path.join(HOME, ".claude", "settings.local.json")), "deny"),
    ("main Write user hook",         edit("Write", os.path.join(HOME, ".claude", "hooks", "x.py")),    "deny"),
    ("main Write user agent def",    edit("Write", os.path.join(HOME, ".claude", "agents", "x.md")),   "deny"),
    ("main Write user command def",  edit("Write", os.path.join(HOME, ".claude", "commands", "x.md")), "deny"),
    ("main Edit project settings",   edit("Edit", os.path.join(CWD, ".claude", "settings.json"), cwd=CWD), "deny"),
    ("main Edit project agent def",  edit("Edit", os.path.join(".claude", "agents", "x.md"), cwd=CWD), "deny"),
    ("main Edit project hook def",   edit("Edit", os.path.join(".claude", "hooks", "h.py"), cwd=CWD),  "deny"),
    ("main Write .env",              edit("Write", os.path.join(CWD, ".env"), cwd=CWD), "deny"),
    ("main Write .env.local",        edit("Write", ".env.local", cwd=CWD),              "deny"),
    ("subagent Write settings",      edit("Write", os.path.join(HOME, ".claude", "settings.json"), "a1"), "allow"),
    ("main Bash redirect settings",  bash("echo x > " + os.path.join(HOME, ".claude", "settings.json")), "deny"),
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
    # The shell honours the LAST `<`, so that is the file actually applied.
    ("main patch double redirect",    bash("patch -p1 < " + SRC_PATCH + " < " + SETTINGS_PATCH, cwd=CWD), "deny"),
    ("main git apply double redirect", bash("git apply < " + SRC_PATCH + " < " + SETTINGS_PATCH, cwd=CWD), "deny"),
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
    # --- test/build/lint commands: the main loop may run them ---
    ("main Bash pytest",             bash("pytest -x tests/"),                          "allow"),
    ("main Bash cd && pytest",       bash("cd proj && pytest"),                         "allow"),
    ("main Bash npm run build",      bash("npm run build"),                             "allow"),
    ("main Bash ./gradlew test",     bash("./gradlew test"),                            "allow"),
    ("subagent Bash pytest",         bash("pytest -x", "a2"),                           "allow"),
    ("main Bash git status",         bash("git status"),                                "allow"),
    ("main Bash echo mention",       bash("echo pytest is great"),                      "allow"),
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
    ("main Task->Explore redirect",  task("Explore"),                                   "deny"),
    ("main Agent->Explore redirect", {"tool_name": "Agent",
                                      "tool_input": {"subagent_type": "Explore"}},     "deny"),
    ("main Task->general-purpose",   task("general-purpose"),                           "deny"),
    ("main Task->claude catch-all",  task("claude"),                                    "deny"),
    ("main Task->opulent lane",      task("opulent:coder"),                             "allow"),
    ("main Task->Plan",              task("Plan"),                                      "allow"),
    ("main Task->other plugin",      task("nimble:nimble-researcher"),                  "allow"),
    ("subagent Task->general",       task("general-purpose", "a3"),                     "allow"),
    ("subagent Task->Explore",       task("Explore", "a5"),                             "allow"),
    # --- eco mode: OPULENT_ECO moves complex implementation one rung down ---
    # Coder only, and one-way. The eco-unset half of the pair is the
    # "main Task->opulent lane" row above: with the dial off, nothing changes.
    # With it on, only the coder lane is redirected — the twin itself stays
    # spawnable in both directions, since spending less is not a violation.
    # The subagent_type is the plugin-qualified name: 79 delegate lines in the
    # routing log say "opulent:coder" and none say bare "coder".
    ("eco Task->coder redirected",   task("opulent:coder"),          "deny",  {"OPULENT_ECO": "1"}),
    ("eco Agent->coder redirected",  {"tool_name": "Agent",
                                      "tool_input": {"subagent_type": "opulent:coder"}},
                                                                     "deny",  {"OPULENT_ECO": "1"}),
    ("eco Task->coder-eco spawns",   task("opulent:coder-eco"),      "allow", {"OPULENT_ECO": "1"}),
    ("eco Task->mechanic untouched", task("opulent:mechanic"),       "allow", {"OPULENT_ECO": "1"}),
    # scribe, not scout: the other Opus lane is the one an over-eager "eco the
    # expensive lanes" edit actually catches, and coder-only is the design.
    ("eco Task->scribe untouched",   task("opulent:scribe"),         "allow", {"OPULENT_ECO": "1"}),
    ("eco subagent Task->coder",     task("opulent:coder", "a4"),    "allow", {"OPULENT_ECO": "1"}),
    ("no eco Task->coder-eco",       task("opulent:coder-eco"),      "allow"),
    # --- escape hatch, reads, garbage ---
    ("OPULENT_OFF disables all",     edit("Edit", os.path.join(HOME, ".claude", "settings.json")), "allow", {"OPULENT_OFF": "1"}),
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
    """Run one payload against a real log file; return (decision, events,
    details)."""
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
    return got, [e.get("event") for e in entries], [e.get("detail") for e in entries]


# --- telemetry: the audit trail is what the lockout was really buying, so a
# main-loop write that is now ALLOWED still has to leave a line behind.
TELEMETRY = [
    ("main edit logs an event",
     edit("Edit", os.path.join(CWD, "src", "app.py"), cwd=CWD), "allow", "edit"),
    ("main bash write logs an event",
     bash("echo hi > notes.txt", cwd=CWD), "allow", "edit"),
    ("main test run logs an event",
     bash("pytest -q", cwd=CWD), "allow", "test"),
    ("scratch write is not logged",
     edit("Write", os.path.join(TMP, "scratch.txt"), cwd=CWD), "allow", None),
    ("subagent edit is not logged",
     edit("Edit", PROJ, "a1"), "allow", None),
    ("control-plane denial logs a deny",
     edit("Write", os.path.join(HOME, ".claude", "settings.json")), "deny", "deny"),
    ("the canary is denied and logged as a probe",
     bash("touch opulent-doctor-canary"), "deny", "probe"),
    # A fifth field pins the logged detail: the point of reading the patch is
    # that the record names the file it writes, not a "(patch)" sentinel.
    ("patched file is logged by its real stripped path",
     bash("git apply -p1 " + SRC_PATCH, cwd=CWD), "allow", "edit", "src/app.py"),
    ("a deletion is logged by the live side of the /dev/null pair",
     bash("git apply -p1 " + DELETE_PATCH, cwd=CWD), "allow", "edit", "src/old.py"),
    ("-p0 strips nothing, so the whole header path is the record",
     bash("patch -p0 < " + BARE_PATCH, cwd=CWD), "allow", "edit", "src/app.py"),
    # Both patches on one `git apply` are read, so both land in the record.
    ("every patch on the line is read, not just the last",
     bash("git apply -p1 " + SRC_PATCH + " " + SRC2_PATCH, cwd=CWD),
     "allow", "edit", "src/app.py, src/other.py"),
    # A rename is invisible without the `diff --git` line: no ---/+++ pair
    # exists to parse, so an unfixed hook logs nothing at all here.
    ("a rename is logged from its diff --git line, both sides",
     bash("git apply -p1 " + SRC_RENAME_PATCH, cwd=CWD),
     "allow", "edit", "src/old.py, src/new.py"),
    # The quotes git puts round a name are not part of the name, so the record
    # names the file rather than a quoted approximation of it.
    ("a quoted header path is recorded unquoted",
     bash("git apply -p1 " + QUOTED_RENAME_PATCH, cwd=CWD),
     "deny", "deny", "control:.claude/hooks/my file.py"),
    # An unsplittable `diff --git` line is read from the rename lines, which
    # name the two paths and nothing else — so the record does too.
    ("a spaced rename records the two paths it moves and no others",
     bash("git apply -p1 " + SPACED_SRC_RENAME_PATCH, cwd=CWD),
     "allow", "edit", "src/my file.py, src/your file.py"),
]

for case in TELEMETRY:
    desc, payload, want_decision, want_event = case[:4]
    want_detail = case[4] if len(case) > 4 else None
    got, events, details = logged(payload)
    ok = got == want_decision and (
        want_event in events if want_event else not events)
    if want_detail is not None:
        ok = ok and want_detail in details
    status = "PASS" if ok else "FAIL"
    if status == "FAIL":
        failures += 1
    want = f"{want_decision}/{want_event}"
    is_ = f"{got}/{events or 'nothing'}"
    if want_detail is not None:
        want += f"/{want_detail}"
        is_ += f"/{details or 'nothing'}"
    print(f"{status}  {desc}: expected={want} got={is_}")

# --- eco mode: a redirect that does not NAME the lane it redirects to is just
# a refusal, and a redirect logged as a denial inflates the denial count the
# doctor reports — the same reason `probe` was given its own event. run()
# reports only the decision, so the reason text, the event and the detail are
# all checked here.
ECO_ENV = {"OPULENT_ECO": "1"}
ECO = [
    ("the eco redirect names the eco lane and logs event eco / eco:coder",
     task("opulent:coder"), "coder-eco", "eco", "eco:coder"),
]

for desc, payload, want_text, want_event, want_detail in ECO:
    reason = run(payload, ECO_ENV, field="permissionDecisionReason")
    got, events, details = logged(payload, ECO_ENV)
    ok = (got == "deny" and want_text in reason
          and events == [want_event] and want_detail in details)
    status = "PASS" if ok else "FAIL"
    if status == "FAIL":
        failures += 1
    print(f"{status}  {desc}: expected=deny/[{want_event}]/{want_detail}/names "
          f"{want_text!r} got={got}/{events or 'nothing'}/{details or 'nothing'}/{reason!r}")

total = len(CASES) + len(TELEMETRY) + len(ECO)
print(f"\n{total - failures}/{total} passed")
sys.exit(1 if failures else 0)
