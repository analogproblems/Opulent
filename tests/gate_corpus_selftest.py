#!/usr/bin/env python3
"""Self-test for public_gate.py's CORPUS — the half gate_selftest.py doesn't cover.

gate_selftest.py proves the gate reports a finding safely: numbered, located,
never echoed. It says nothing about whether the gate FINDS anything, because
every one of its fixtures plants residue somewhere `git log -p` was already
looking. That gap had teeth: until 2026-08-13 this gate scanned reachable
history diffs, certified a checkout clean while all ten stored terms sat in
its object database, and no test noticed.

So each case here plants residue in a place the old corpus could not see, and
asserts the gate now FAILS. A case that passes clean is a regression to the
exact bug that motivated the rewrite.

The stored-term case is the other missing witness. `DENY` had no positive
control at all — emptying the whole list left the suite green, because a clean
repo scans clean whether matching works or not. `stored term in an ordinary
commit` is that control: it fails if `DENY` is empty, if matching breaks, or
if the corpus stops reaching ordinary blobs.

    python3 tests/gate_corpus_selftest.py
"""
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Overridable so this suite can be pointed at an OLD copy of the gate and
# watched to fail. A corpus test that has never failed is a corpus test nobody
# has checked, and the bug it exists for was invisible to a green suite once
# already.
GATE = os.environ.get("PUBLIC_GATE_PATH") or str(
    Path(__file__).resolve().parent / "public_gate.py")
ROOT = tempfile.mkdtemp(prefix="opulent-gate-corpus-")
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)

# Never a real identity. These are fixtures, and a fixture that had to be a
# real name would make this file the leak it exists to prevent.
SECRET = "zebrahorse"


def first_stored_term(gate_path):
    """A real DENY entry, read out of the gate rather than copied in here.

    The first draft of this file spelled one out as a constant, and the gate
    failed the very next run — correctly, because a denied term written into a
    published test file is residue like any other. Reading it at runtime keeps
    the positive control real without writing the term down, and it cannot go
    stale when the list changes."""
    src = open(gate_path, encoding="utf-8").read()
    m = re.search(r'Term\(\s*"((?:[^"\\]|\\.)*)"', src[src.index("DENY = ["):])
    return m.group(1) if m else ""


STORED = first_stored_term(GATE)

GIT_CONF = ["-c", "user.name=t", "-c", "user.email=t@t",
            "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]


def git(repo, *args, check=True):
    p = subprocess.run(["git", "-C", repo, *GIT_CONF, *args],
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"fixture setup failed: git {' '.join(args)}\n{p.stderr}")
    return p


def new_repo(name):
    repo = os.path.join(ROOT, name)
    os.makedirs(repo)
    git(repo, "init", "-q")
    (Path(repo) / "readme.md").write_text("nothing to see\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


# --- fixtures, one per blind spot -------------------------------------------

def merge_resolution(repo):
    """Residue that exists ONLY in a hand-resolved merge. `log -p` prints no
    patch for a merge commit, so this content appears in no diff anywhere."""
    (Path(repo) / "f.txt").write_text("shared\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add f")
    git(repo, "switch", "-qc", "side")
    (Path(repo) / "f.txt").write_text("side\n")
    git(repo, "commit", "-qam", "side")
    git(repo, "switch", "-q", "main")
    (Path(repo) / "f.txt").write_text("main\n")
    git(repo, "commit", "-qam", "main")
    git(repo, "merge", "side", check=False)          # conflicts on purpose
    (Path(repo) / "f.txt").write_text(f"{SECRET} resolved it\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "resolve")


def unreachable(repo):
    """Residue orphaned by a reset — the state a failed gate tells you to
    create, and the one this gate then has to keep seeing."""
    (Path(repo) / "leak.txt").write_text(f"{SECRET} was here\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "oops")
    git(repo, "reset", "--hard", "HEAD~1", check=False)


def binary_blob(repo):
    """Residue inside a blob git calls binary: `-p` renders 'Bin N -> M bytes'
    and never the content."""
    (Path(repo) / "blob.bin").write_bytes(
        b"\x00\x01\x02" + SECRET.encode() + b"\x00\xff")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add binary")


def tag_message(repo):
    """Residue in an annotated tag's message. Tag objects are not printed by
    `git log` at all, and `git tag -l` yields only names."""
    git(repo, "-c", f"user.name=t", "tag", "-a", "v9", "-m",
        f"released by {SECRET}")


def committer_identity(repo):
    """Residue in the COMMITTER field while the author is clean. Default
    `git log` prints Author: only; GitHub shows both."""
    p = subprocess.run(
        ["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false",
         "-c", f"committer.name={SECRET}", "-c", f"committer.email={SECRET}@x.invalid",
         "commit", "-q", "--allow-empty", "-m", "clean message"],
        capture_output=True, text=True,
        env={**os.environ, "GIT_COMMITTER_NAME": SECRET,
             "GIT_COMMITTER_EMAIL": f"{SECRET}@x.invalid"})
    if p.returncode:
        raise SystemExit(f"fixture setup failed (committer): {p.stderr}")


def filename_only(repo):
    """Residue in a FILENAME rather than in content — a tree entry."""
    (Path(repo) / f"{SECRET}-notes.md").write_text("innocuous contents\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "add notes")


def stored_term(repo):
    """A stored DENY term in an ordinary commit: the positive control the
    stored half never had."""
    (Path(repo) / "notes.md").write_text(f"see the {STORED} transcripts\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "reference")


def nfd_spelling(repo):
    """Residue spelled in the opposite Unicode normal form to the term."""
    (Path(repo) / "who.txt").write_text("contact josé about it\n")  # NFD
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "contact")


def run_gate(repo, private=None):
    env = dict(os.environ)
    env.pop("PUBLIC_GATE_PRIVATE_TERMS", None)
    if private:
        env["PUBLIC_GATE_PRIVATE_TERMS"] = private
    p = subprocess.run([sys.executable, GATE, "--repo", repo],
                       capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr


# name, fixture, private-terms value, must-fail
CASES = [
    ("residue only in a merge conflict resolution", merge_resolution, SECRET),
    ("residue in an unreachable object after reset --hard", unreachable, SECRET),
    ("residue inside a binary blob", binary_blob, SECRET),
    ("residue in an annotated tag message", tag_message, SECRET),
    ("residue in the committer field, author clean", committer_identity, SECRET),
    ("residue in a filename, not in any content", filename_only, SECRET),
    ("a stored DENY term in an ordinary commit", stored_term, None),
    ("residue spelled in the other Unicode normal form", nfd_spelling, "josé"),
]


def main():
    failures = 0
    for i, (name, fixture, private) in enumerate(CASES):
        repo = new_repo(f"case{i}")
        fixture(repo)
        code, out = run_gate(repo, private)
        # Every case is residue. The gate must refuse it.
        caught = code != 0
        # And it must never echo a secret term while refusing.
        echoed = private and private.lower() in out.lower()
        ok = caught and not echoed
        why = "" if ok else (
            "  <- scanned CLEAN (the corpus cannot see it)" if not caught
            else "  <- ECHOED the private term")
        print(f"{'PASS' if ok else 'FAIL'}  {name}{why}")
        failures += not ok

    # The censor's length-safety, end to end: a term preceded by a character
    # whose lowercase is longer than itself must still be masked, and the
    # banner naming the checkout is where it shows up.
    repo = new_repo("censor-offsets")
    # U+0130 lowercases to TWO characters, so each one ahead of the match slid
    # the old mask one place right. The term only escapes entirely once the
    # drift exceeds its own length — hence one per character plus slack, not a
    # token few. A fixture with four of these leaked "zebr" and looked clean.
    holder = os.path.join(ROOT, "İ" * (len(SECRET) + 2) + SECRET + "-work")
    shutil.copytree(repo, holder)
    code, out = run_gate(holder, SECRET)
    leaked = SECRET.lower() in out.lower()
    print(f"{'FAIL' if leaked else 'PASS'}  a term after a length-changing "
          f"character is still masked" + ("  <- ECHOED" if leaked else ""))
    failures += leaked

    total = len(CASES) + 1
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
