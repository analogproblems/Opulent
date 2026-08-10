#!/usr/bin/env python3
"""Self-test for public_gate.py's environment-supplied private terms.

The gate's stored DENY list has a witness already: it runs against this repo
on every push, and a term that quietly stopped matching would surface as a
history that suddenly scanned clean. The environment half has no such witness.
`PUBLIC_GATE_PRIVATE_TERMS` carries identity terms — a real name, an old
username — and the point of that channel is that neither the terms nor the
lines they match may be written down anywhere a reader can reach. The property
worth locking is therefore a *negative* one, and negative properties do not
announce their own decay: a renderer that started quoting the matched line
would still pass every test that only checked the exit code.

So this plants nonsense terms in a throwaway history, in the throwaway
checkout's own path because the gate's diagnostics are output too, and in the
path of a throwaway copy of the gate itself because a traceback is output too —
then asserts what the gate says about them: that it fails, that it says
*where*, and that nowhere in its output does it say *what*. The plants are
invented here, public here — which is what makes it safe to write a test about
redaction at all.

    python3 tests/gate_selftest.py
"""
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

GATE = str(Path(__file__).resolve().parent / "public_gate.py")
PRIVATE_ENV = "PUBLIC_GATE_PRIVATE_TERMS"

# Name-shaped nonsense, because names are what the channel exists for. No
# string here appears anywhere but this file and the fixtures it builds.
PLANTED = "quillfeather"      # committed into a file, so a patch carries it
REF_PLANTED = "harrowgate"    # committed into a branch name, which is history too
ABSENT = "zzzznotpresent"     # supplied and never present: the clean-scan case
# The third plant is committed nowhere. The gate opens with a banner naming the
# checkout it scanned, and a checkout path is `/home/<username>/…` — so for a
# term supplied precisely *because* it is a username, the gate's own
# diagnostics are a channel the findings-side redaction never looks at. This
# one is planted in directory names instead of in commits, twice and in two
# casings, because a censor that stops after the first occurrence or that only
# matches the casing the operator typed has not censored a path.
PATH_PLANTED = "bellwright"   # in the scanned checkout's own path, and nowhere else
PLANTS = {"the file-content plant": PLANTED,
          "the ref-name plant": REF_PLANTED,
          "the checkout-path plant": PATH_PLANTED}

# public_gate's PRIVATE_MASK, spelled out rather than imported. This suite
# reads the gate the way a CI log does — through its output — so the mask is
# part of the contract being asserted, and one that changed shape should fail
# here rather than be quietly followed.
MASK = "[private]"

# Committer identity and defaults are passed per invocation rather than
# written into the fixture: a CI runner has no global git config, and a fixture
# that borrowed the developer's would be a fixture that builds on one machine.
GIT_CONF = ["-c", "user.name=gate selftest",
            "-c", "user.email=gate@example.invalid",
            "-c", "init.defaultBranch=main",
            "-c", "commit.gpgsign=false"]


def git(repo, *args):
    """A fixture git command, or a loud death. There is no fail-open here —
    a fixture that half-built would test a history nobody described."""
    p = subprocess.run(["git", "-C", repo, *GIT_CONF, *args],
                       capture_output=True, text=True, timeout=60)
    if p.returncode:
        sys.stderr.write(p.stderr)
        raise SystemExit(f"gate selftest: fixture `git {args[0]}` exited "
                         f"{p.returncode}")
    return p.stdout


def scratch(*parts):
    """A throwaway directory, removed on exit. `parts` are subdirectories to
    place it under, which is how a fixture gets a *path* worth asserting about:
    the gate prints where it looked, so a checkout's own name is part of the
    output this suite has to watch."""
    base = tempfile.mkdtemp(prefix="opulent-gate-selftest-")
    atexit.register(shutil.rmtree, base, True)
    return os.path.join(base, *parts)


def build_repo(repo):
    """A throwaway object database carrying the history plants and nothing else.

    Nothing on the gate's DENY list appears in it, so every expected-clean
    case below is clean because of the private-term logic rather than because
    some unrelated finding happened to be absent."""
    os.makedirs(repo, exist_ok=True)
    git(repo, "init", "-q")
    with open(os.path.join(repo, "notes.txt"), "w") as fh:
        fh.write(f"reachable at {PLANTED}@example.invalid\n")
    git(repo, "add", "notes.txt")
    git(repo, "commit", "-qm", "notes")
    git(repo, "branch", f"wip/{REF_PLANTED}")
    return repo


REPO = build_repo(scratch())
# The same history, at a path that carries the path plant. Same fixture, a
# different thing asserted about it: not what the gate found, but what it says
# about where it went looking.
PATH_REPO = build_repo(scratch(f"{PATH_PLANTED}-work",
                               f"{PATH_PLANTED.capitalize()}-checkout"))
HEAD9 = git(REPO, "rev-parse", "HEAD").strip()[:9]

# --- The output the gate does not write itself -------------------------------
#
# Every line asserted about above is the gate's own: printed through say(), or
# raised as a SystemExit it censored on the way out. A crash is nobody's line.
# The interpreter formats that traceback, and a traceback names the file it was
# reading — absolutely, in every frame — on the machine where the terms are
# real. So one case kills the gate on purpose and reads the wreckage.
#
# The plant has to be in the *script's* path, because that is the part a
# traceback actually carries: `FileNotFoundError: 'git'` names the program that
# was missing, not the argv it belonged to. (The argv leak is the timeout's —
# TimeoutExpired stringifies to the whole command, `-C <repo>` and all — and no
# suite can afford to wait out a ten-minute timeout to watch it. Same stream
# and same hook, so censoring the one censors the other.)
CRASH_GATE = os.path.join(scratch(f"{PATH_PLANTED}-tools"), "public_gate.py")
os.makedirs(os.path.dirname(CRASH_GATE))
shutil.copyfile(GATE, CRASH_GATE)
# A PATH with no git on it: the cheapest unhandled exception the gate has, and
# it fires in the first subprocess, before a line of the gate's own output. A
# real empty directory rather than an empty string, because execvp falls back
# to a built-in default path when PATH is unset or empty, and git lives on it.
NO_GIT = scratch()


def run_gate(private, repo=REPO, crash=False):
    """(exit code, everything the gate said). The two streams are joined
    because the redaction property is about the log a CI run leaves behind,
    and a CI log does not keep them apart.

    `crash` runs the copy at the planted path with git off the PATH, so what
    comes back is what the interpreter prints when the gate never reaches a
    line of its own."""
    env = dict(os.environ)
    # Cleared before it is maybe re-set: the maintainer's own shell may hold
    # the real value, and a suite that inherited it would be testing a term
    # this file knows nothing about — and could print.
    env.pop(PRIVATE_ENV, None)
    if private is not None:
        env[PRIVATE_ENV] = private
    if crash:
        env["PATH"] = NO_GIT
    p = subprocess.run([sys.executable, CRASH_GATE if crash else GATE,
                        "--repo", repo],
                       capture_output=True, text=True, env=env, timeout=600)
    return p.returncode, p.stdout + p.stderr


# desc, PUBLIC_GATE_PRIVATE_TERMS value (None = unset), want failure,
# [must appear], [must not appear], checkout to scan (default: REPO),
# crash the gate rather than let it finish (default: no)
CASES = [
    # The attribution pair is the entire permitted output for a private hit: a
    # commit to check out, and a path to look in once you are there.
    ("a term planted in a patch fails the gate, by position and place",
     PLANTED, True, ["private term #1", HEAD9, "notes.txt"]),
    # Ref names are the other half of the corpus, and there the matched line
    # *is* the term — so nothing but the location can survive the report.
    ("a term planted in a branch name fails the gate",
     REF_PLANTED, True, ["private term #1"]),
    # And the location is the ref itself, not whichever commit and file was
    # last in the patch stream the ref names were appended to. A ref hit is
    # the one finding whose location carries the term it locates —
    # the name *is* the leak — so this asserts both halves in one string: the
    # ref is named well enough to delete, and the name is masked inside it.
    ("a ref-name hit is located at the ref, with the name masked inside it",
     REF_PLANTED, True, [f"ref refs/heads/wip/{MASK}"]),
    ("terms are folded on intake, so the operator's casing cannot matter",
     PLANTED.upper(), True, ["private term #1"]),
    # Numbering runs over the terms actually scanned. #1 missed here, so #1
    # must not appear at all, or "which one hit?" has no answer.
    ("a hit is numbered by its place in the list",
     f"{ABSENT}:{PLANTED}", True, ["private term #2"], ["private term #1"]),
    ("empty tokens are dropped rather than numbered",
     f"::{PLANTED}:", True, ["private term #1"]),
    ("a supplied term that is absent is a clean pass",
     ABSENT, False, ["clean"]),
    # The skip cases run against the same planted history: exit 0 here is the
    # gate declining to look, not a repo with nothing in it. The notice is the
    # assertion that matters — a fork PR gets no secrets, and a log that said
    # nothing would be indistinguishable from one that scanned and cleared.
    ("unset is an audited skip, not a failure",
     None, False, ["skipped", PRIVATE_ENV]),
    ("empty is the same skip",
     "", False, ["skipped", PRIVATE_ENV]),
    ("whitespace is the same skip",
     "  ", False, ["skipped", PRIVATE_ENV]),
    ("separators alone are the same skip",
     ":::", False, ["skipped", PRIVATE_ENV]),
    # The last two scan a checkout whose own path carries a plant, which is the
    # ordinary case rather than an exotic one: a home-directory clone plus a
    # term that is a username. Their exit codes are the same as their
    # history-scanning twins above — a path is not a finding, and censoring it
    # must not invent one. What is new is where a leak could hide, so the
    # assertion that matters is the every-case one below, which reads the whole
    # of `out` and does not care which line carried the plant.
    ("a term in the scanned path is censored out of a clean run's banner",
     PATH_PLANTED, False, ["clean"], [], PATH_REPO),
    ("a term in the scanned path survives neither the banner nor a failure",
     f"{PATH_PLANTED}:{PLANTED}", True, ["private term #2", "notes.txt"],
     ["private term #1"], PATH_REPO),
    # A death the gate did not plan for. Nonzero is not the interesting half —
    # the interpreter has always done that — so this asserts the traceback
    # arrived *and* came through the censor, and leaves "and said nothing else"
    # to the every-case check below.
    ("a crash censors the traceback the interpreter prints, not the gate",
     PATH_PLANTED, True, ["Traceback (most recent call last)",
                          f"{MASK}-tools"], [], PATH_REPO, True),
]

failures = 0
for case in CASES:
    desc, private, want_fail = case[0], case[1], case[2]
    must_say = case[3] if len(case) > 3 else []
    must_not_say = case[4] if len(case) > 4 else []
    repo = case[5] if len(case) > 5 else REPO
    crash = case[6] if len(case) > 6 else False
    code, out = run_gate(private, repo, crash)
    wrong = []
    if bool(code) != want_fail:
        wrong.append(f"exit {code}, wanted {'nonzero' if want_fail else '0'}")
    wrong += [f"never said {s!r}" for s in must_say if s not in out]
    wrong += [f"said {s!r}" for s in must_not_say if s in out]
    # Checked on every case rather than only the ones expecting a hit: a term
    # echoed by a run that passed has leaked exactly as far. Case-folded,
    # because a redaction holding only for the casing the operator typed is
    # not one. Named rather than quoted, so a failing CI log does not finish
    # the leak on the test's behalf.
    wrong += [f"ECHOED {name}" for name, plant in PLANTS.items()
              if plant in out.lower()]
    status = "FAIL" if wrong else "PASS"
    failures += bool(wrong)
    print(f"{status}  {desc}" + (f": {'; '.join(wrong)}" if wrong else ""))

print(f"\n{len(CASES) - failures}/{len(CASES)} passed")
sys.exit(1 if failures else 0)
