#!/usr/bin/env python3
"""Behaviour tests for bin/opulent-codex. Every assertion here is about what the
program DOES: the argv it builds, the exit code it passes through, the ledger
line it leaves, the citations it checks, the files it attributes to a run.

Nothing here asserts the wording of a markdown file. The orrery suite this
came from did little else — needles that read a sentence in an agent
definition, so every prose edit broke a test and every review round could
always find another sentence to pin. 7,208 lines of test against 2,298 lines of
code is what that looks like from the inside.

    python3 tests/codex_cases.py
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DISPATCH = HERE.parent / "bin" / "opulent-codex"

# An installed plugin directory is not a build directory: importing the
# program to test it must not leave bytecode beside it.
sys.dont_write_bytecode = True

spec = importlib.util.spec_from_loader(
    "opulent_codex",
    importlib.machinery.SourceFileLoader("opulent_codex", str(DISPATCH)))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ROOT = tempfile.mkdtemp(prefix="opulent-codex-tests-")
FAILURES = []
GIT_CONF = ["-c", "user.name=t", "-c", "user.email=t@t",
            "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]

SID = "01a0367b-6801-7ca0-8b7a-4207b74a41e5"


def check(name, condition, detail=""):
    print(("PASS  " if condition else "FAIL  ") + name
          + ("" if condition else "  <- " + detail))
    if not condition:
        FAILURES.append(name)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *GIT_CONF, *args],
                          capture_output=True, text=True)


def new_repo(name):
    repo = os.path.join(ROOT, name)
    os.makedirs(repo)
    git(repo, "init", "-q")
    Path(repo, "app.py").write_text("one\ntwo\nthree\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


def stub_codex(name, exit_code=0, message="all done", sid=SID, touches=None):
    """A codex that behaves like codex: reads the brief on stdin, announces a
    session id, writes its final message to the -o path, optionally edits the
    tree, and exits with the code we asked for."""
    path = os.path.join(ROOT, name)
    Path(path).write_text(f"""#!/usr/bin/env python3
import sys, os, json
sys.stdin.read()
print("session id: {sid}")
argv = sys.argv
out = argv[argv.index("-o") + 1]
cwd = argv[argv.index("-C") + 1]
open(out, "w").write({message!r})
for rel in {touches or []!r}:
    open(os.path.join(cwd, rel), "a").write("touched\\n")
sys.exit({exit_code})
""")
    os.chmod(path, 0o755)
    return path


def dispatch(args, codex, log=None, cwd=None):
    env = dict(os.environ)
    env["OPULENT_CODEX_BIN"] = codex
    env["OPULENT_CODEX_LOG"] = log or os.path.join(ROOT, "ledger.jsonl")
    p = subprocess.run([sys.executable, str(DISPATCH), *args],
                       capture_output=True, text=True, env=env, cwd=cwd or ROOT)
    return p.returncode, p.stdout + p.stderr


def ledger(log):
    try:
        return [json.loads(l) for l in open(log) if l.strip()]
    except OSError:
        return []


# --- argv: the pins are the product ------------------------------------------
argv = mod.build_argv("/bin/codex", "sol", "max", "workspace-write",
                      "/w", "/tmp/last.txt")
check("sol runs its own model at the effort it was given",
      "gpt-5.6-sol" in argv and "model_reasoning_effort=max" in argv, str(argv))
check("the prompt positional is the trailing dash, which is how the brief gets in",
      argv[-1] == "-", str(argv[-1]))
check("the working directory reaches codex as -C",
      argv[argv.index("-C") + 1] == "/w", str(argv))
check("the sandbox reaches codex as -s",
      argv[argv.index("-s") + 1] == "workspace-write", str(argv))
check("no network access unless it is asked for",
      mod.NETWORK not in argv, str(argv))
check("--network is a codex config override, not a flag we invented",
      mod.NETWORK in mod.build_argv("/bin/codex", "sol", "max", "workspace-write",
                                    "/w", "/l", network=True))

rv = mod.build_argv("/bin/codex", "review", "max", "read-only", "/w", "/l")
check("review runs on sol's model — there is no gpt-5.6-review",
      "gpt-5.6-sol" in rv and "gpt-5.6-review" not in rv, str(rv))
check("review defaults to a read-only sandbox",
      mod.SANDBOX["review"] == "read-only", mod.SANDBOX["review"])

# --- exit codes and the ledger ------------------------------------------------
repo = new_repo("exit")
brief = os.path.join(ROOT, "brief.md")
Path(brief).write_text("do the thing\n")

log = os.path.join(ROOT, "ok.jsonl")
code, out = dispatch(["sol", repo, brief], stub_codex("codex-ok"), log)
check("a clean run exits zero", code == 0, "exit %d\n%s" % (code, out))
lines = ledger(log)
check("a clean run leaves exactly one ledger line", len(lines) == 1, str(lines))
check("the ledger records the argv actually executed",
      lines and lines[0]["argv"][:2][1] == "exec"
      and "gpt-5.6-sol" in lines[0]["argv"], str(lines[:1]))
check("the ledger records the session id codex printed",
      lines and lines[0]["sid"] == SID, str(lines[:1]))

log = os.path.join(ROOT, "fail.jsonl")
code, out = dispatch(["sol", repo, brief], stub_codex("codex-3", exit_code=3), log)
check("codex's exit code is passed through, not laundered", code == 3, str(code))
check("a failed run is still in the ledger",
      len(ledger(log)) == 1 and ledger(log)[0]["exit"] == 3, str(ledger(log)))
check("a failed run is reported as failed, in words",
      "failed" in out, out[:200])

# --- what the run touched, measured rather than claimed ----------------------
repo = new_repo("touch")
Path(repo, "already-dirty.txt").write_text("not this run's doing\n")
log = os.path.join(ROOT, "touch.jsonl")
code, out = dispatch(["sol", repo, brief],
                     stub_codex("codex-edit", touches=["app.py"]), log)
check("a file codex edited is reported as changed", "app.py" in out, out[:400])
check("a file that was already dirty is not attributed to the run",
      "already-dirty.txt" not in out, out[:400])

repo = new_repo("nodiff")
code, out = dispatch(["sol", repo, brief], stub_codex("codex-noop"), log)
check("an empty diff is reported as empty, not as success",
      "the diff is empty" in out, out[:400])

# --- citations ----------------------------------------------------------------
repo = new_repo("cites")
Path(repo, "app.py").write_text("a\nb\nc\n")
git(repo, "commit", "-qam", "second")   # so HEAD~1..HEAD has a diff to review
Path(repo, "sub").mkdir()
Path(repo, "sub", "deep.py").write_text("a\nb\n")
cites = dict(mod.citations(
    "app.py:2 is fine, app.py:99 is not, gone.py:1 vanished, "
    "sub/deep.py:1 nested, ../outside.py:1 escapes", repo))
check("a real line in a real file verifies", cites.get("app.py:2") == "ok", str(cites))
check("a line past the end of the file is caught",
      "no such line" in cites.get("app.py:99", ""), str(cites))
check("a citation to a file that is not there is caught",
      cites.get("gone.py:1") == "no such file", str(cites))
check("a nested path resolves against the working directory",
      cites.get("sub/deep.py:1") == "ok", str(cites))
check("a citation escaping the tree is refused, not stat'ed",
      cites.get("../outside.py:1") == "outside the tree", str(cites))

msg = "found one at app.py:99 — HIGH — off by one"
code, out = dispatch(["review", repo, "--range", "HEAD~1..HEAD"],
                     stub_codex("codex-cite", message=msg), log)
check("review names an unverifiable citation instead of dropping the finding",
      "UNVERIFIABLE" in out and "app.py:99" in out, out[:500])

# --- review's own preconditions ----------------------------------------------
repo = new_repo("empty")
code, out = dispatch(["review", repo], stub_codex("codex-never"), log)
check("review with nothing to review exits zero and dispatches nothing",
      code == 0 and "nothing to review" in out, "%d %s" % (code, out[:200]))

code, out = dispatch(["review", repo, brief], stub_codex("codex-never"), log)
check("review refuses a hand-written brief — it builds its own",
      code != 0 and "builds its own brief" in out, out[:200])

code, out = dispatch(["sol", repo], stub_codex("codex-never"), log)
check("a work lane without a brief is refused", code != 0, out[:200])

code, out = dispatch(["sol", "relative/path", brief], stub_codex("codex-never"), log)
check("a relative working directory is refused",
      code != 0 and "absolute" in out, out[:200])

# --- session id ---------------------------------------------------------------
runlog = os.path.join(ROOT, "quiet.log")
Path(runlog).write_text("codex said nothing identifying\n")
check("a run log with no session id yields None, never a constructed one",
      mod.session_id(runlog) is None, str(mod.session_id(runlog)))

shutil.rmtree(ROOT, ignore_errors=True)
print("\n%d checks, %d failed" % (
    len([l for l in open(__file__) if l.startswith("check(")]), len(FAILURES)))
sys.exit(1 if FAILURES else 0)
