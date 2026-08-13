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

Two cases plant in a place the corpus always saw and vary the TERM instead —
its splitting and its casing — because both halves of matching decayed
invisibly once already: every earlier plant was a lowercase single-token
value, so reverting the multi-line split fix or deleting the corpus-side
case-fold left both suites green.

The refusal paths are corpus properties too, and get cases here: a shallow
clone, a directory that is not a repository, and a git that dies mid-scan
must each end nonzero — a scan that could not read the object database has
not cleared it, and until now every one of those refusals was deletable with
both suites green. DENY_TAGS gets the positive control DENY already has: its
glob is read out of the gate at runtime and a matching tag synthesized, so an
emptied list fails loudly here instead of passing silently forever.

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


def first_deny_tag(gate_path):
    """A real DENY_TAGS glob, read out of the gate at runtime for the same
    reason as first_stored_term: a denied pattern spelled into a published
    test file is residue, and a copy goes stale the day the list changes.
    Returns "" when the list is empty — which the case below treats as its
    own failure, because an emptied DENY_TAGS leaves the tag path with
    nothing to hunt and no test that would ever say so."""
    src = open(gate_path, encoding="utf-8").read()
    m = re.search(r'DENY_TAGS\s*=\s*\[\s*\(\s*"((?:[^"\\]|\\.)*)"', src)
    return m.group(1) if m else ""


DENY_TAG_GLOB = first_deny_tag(GATE)

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


def ordinary_commit(repo):
    """Residue in a plainly reachable commit — deliberately boring, because
    its case varies the TERM, not the corpus: the private value it runs with
    is multi-line, the shape a CI secret store hands over. Until 2026-08-13
    the gate split that value on `:` alone, the newline stayed *inside* the
    term where a line-by-line corpus could never match it, and the run
    reported the term as supplied, matched-but-never-echoed, and clean.
    Every other plant here is a single token, so reverting that split fix
    left both suites green."""
    (Path(repo) / "plain.txt").write_text(f"ping {SECRET} about it\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "plain")


def capitalized_occurrence(repo):
    """Residue with a capital letter — the ordinary shape of a name opening
    an old commit message. Terms are folded on intake; each corpus line is
    folded before comparison; and with every other plant lowercase, the
    corpus-side fold was the removable half: deleting it left both suites
    green while any capitalized occurrence scanned clean."""
    git(repo, "commit", "-q", "--allow-empty", "-m",
        f"{SECRET.capitalize()} reviewed this before the split")


def note_content(repo):
    """Residue in a `git notes` message — content reachable only via
    refs/notes/commits, a ref outside heads/remotes. The gate's docstring
    names that family as an old-corpus blind spot and the changelog claims a
    plant in each one; this is the plant that makes the claim true."""
    git(repo, "notes", "add", "-m", f"ghost-written by {SECRET}")


def stashed_content(repo):
    """Residue in a stash. Blind to the old corpus twice over: the stash
    commit is a MERGE commit, for which `-p` prints no patch, and refs/stash
    is outside heads/remotes."""
    (Path(repo) / "readme.md").write_text(f"wip: do not tell {SECRET}\n")
    git(repo, "stash", "push", "-q")


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
    ("residue matched by line two of a multi-line private value",
     ordinary_commit, f"first-line-decoy\n{SECRET}"),
    ("residue capitalized in a commit message, term supplied lowercase",
     capitalized_occurrence, SECRET),
    ("residue in a git note, reachable only via refs/notes",
     note_content, SECRET),
    ("residue in a stash, reachable only via refs/stash",
     stashed_content, SECRET),
]


def main():
    failures = 0
    for i, (name, fixture, private) in enumerate(CASES):
        repo = new_repo(f"case{i}")
        fixture(repo)
        code, out = run_gate(repo, private)
        # Every case is residue. The gate must refuse it.
        caught = code != 0
        # And it must never echo a secret term while refusing. Checked per
        # token, split the way the gate itself splits the value: a joined
        # multi-line value could never match the output its own second line
        # leaked into.
        tokens = [t for t in re.split(r"[:\r\n]+", (private or "").lower()) if t]
        echoed = any(t in out.lower() for t in tokens)
        ok = caught and not echoed
        why = "" if ok else (
            "  <- scanned CLEAN (the gate cannot see it)" if not caught
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

    # --- Refusal paths: what the gate could not read, it must refuse to
    # clear. Fail-closed is the gate's founding property and CONTRIBUTING
    # pins it in prose, yet each of these refusals was deletable with both
    # suites green. Every case wants nonzero AND the refusal's own words —
    # the words matter, because two of these still die nonzero without their
    # refusal (a later git call falls over), and a case satisfied by any
    # death would keep a deleted refusal invisible.

    # A shallow clone is not the object database. CI's fetch-depth: 0 rests
    # on this refusal actually firing when someone forgets it.
    src = new_repo("shallow-src")
    shallow = os.path.join(ROOT, "shallow-clone")
    git(ROOT, "clone", "-q", "--depth", "1", Path(src).as_uri(), shallow)
    code, out = run_gate(shallow)
    ok = code != 0 and "shallow clone" in out
    print(f"{'PASS' if ok else 'FAIL'}  a shallow clone is refused, never "
          f"scanned" + ("" if ok else ("  <- certified a shallow clone"
                                       if code == 0 else
                                       "  <- died without the shallow refusal")))
    failures += not ok

    # A directory with no repository in it. The needle is the gate's own
    # sentence ("… is not a git repository"), NOT git's — with the refusal
    # deleted, a later git call still dies and its passed-through stderr says
    # "fatal: not a git repository", so a looser needle would let the deleted
    # refusal hide behind git's phrasing of the same fact.
    notrepo = os.path.join(ROOT, "not-a-repo")
    os.makedirs(notrepo)
    code, out = run_gate(notrepo)
    ok = code != 0 and "is not a git repository" in out
    print(f"{'PASS' if ok else 'FAIL'}  a directory that is not a repo is "
          f"refused by name" + ("" if ok else ("  <- certified a non-repo"
                                               if code == 0 else
                                               "  <- died without the refusal")))
    failures += not ok

    # git dying mid-scan. A corrupted loose object kills `rev-list` and
    # `cat-file` alike, so a gate whose subprocess wrapper stopped raising
    # would stream past the failure and print clean — the one outcome worse
    # than a false alarm. Corruption over a PATH shim because it needs no
    # shell and behaves the same on every platform.
    victim = new_repo("corrupt")
    sha = git(victim, "rev-parse", "HEAD").stdout.strip()
    obj = os.path.join(victim, ".git", "objects", sha[:2], sha[2:])
    os.chmod(obj, 0o644)          # git writes loose objects read-only
    with open(obj, "wb") as fh:
        fh.write(b"not a git object")
    code, out = run_gate(victim)
    ok = code != 0 and "could not be read" in out
    print(f"{'PASS' if ok else 'FAIL'}  git dying mid-scan fails closed"
          + ("" if ok else "  <- certified a history it could not read"))
    failures += not ok

    # DENY_TAGS' positive control: a tag synthesized at runtime from the
    # gate's own glob must fail the scan and be named in the report. An
    # empty list is itself the failure — the case a silently-emptied
    # DENY_TAGS would otherwise never produce.
    if not DENY_TAG_GLOB:
        print("FAIL  a tag matching a DENY_TAGS glob fails the gate"
              "  <- DENY_TAGS is empty: the tag path has nothing to hunt")
        failures += 1
    else:
        repo = new_repo("denied-tag")
        tag = DENY_TAG_GLOB.replace("*", "0.0.0").replace("?", "x")
        git(repo, "tag", tag)
        code, out = run_gate(repo)
        ok = code != 0 and tag in out
        print(f"{'PASS' if ok else 'FAIL'}  a tag matching a DENY_TAGS glob "
              f"fails the gate"
              + ("" if ok else ("  <- scanned CLEAN (the tag glob path is dead)"
                                if code == 0 else
                                "  <- failed without naming the tag")))
        failures += not ok

    # CASES, the censor-offsets case, three refusals, and the tag glob.
    total = len(CASES) + 5
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
