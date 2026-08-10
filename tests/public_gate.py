#!/usr/bin/env python3
"""Public-hygiene gate: scans the whole object database for private residue.

lens-master ships from its own private repo now. Its *existence* is public on
purpose — the README documents the companion contracts, and the doctor probes
its hook by name — but its internals are not: the matcher constants, the
escape-hatch variables, the file paths they lived at, and its release prose.
A working tree can be cleaned in an afternoon; a history keeps every draft of
it forever. So this reads the object database — `git log --all -p` over every
ref, plus the tag and branch names — rather than the checkout.

Three properties worth stating out loud:

- **It fails closed.** The runtime hooks fail open by house rule: a hook that
  cannot parse its payload allows, because a broken hook must never brick a
  session. A hygiene gate is the opposite. A scan that could not read the
  object database has not cleared it, and reporting "clean" is the one outcome
  worse than a false alarm.
- **It is a denylist.** It proves the absence of the terms below and nothing
  more. A leak nobody wrote down is a leak nobody is checking for, so a new
  private mechanism means a new entry here, in the same commit.
- **It cannot store every term it hunts.** Each entry below names a
  *mechanism*, and a mechanism's name is safe to print beside the proof that
  it is gone. An identity is not like that — for a real name or an old
  username the term text is itself the leak, so a gate that hunted one by
  writing it down would publish the name in the file that proves the name
  absent. Those terms arrive through the environment instead, and every line
  this file prints censors itself — the report about them, the banner naming
  the checkout, because a checkout path is where an identity usually lives,
  and the traceback of a death it did not plan for; see
  PUBLIC_GATE_PRIVATE_TERMS below.

Runs on every CI push as well as before a visibility change — residue is
cheapest to catch on the push that introduces it. CI must check out with
`fetch-depth: 0`; a shallow clone is not the object database, and this refuses
to pretend otherwise.

    python3 tests/public_gate.py [--repo /path/to/checkout]
"""
import argparse
import fnmatch
import os
import subprocess
import sys
import traceback
from collections import namedtuple

# text   — matched case-insensitively as a plain substring, so it is stored
#          lowercase and the source lines are lowered before comparison
# leak   — what finding it would tell a reader they were not meant to know
# label  — how the report names the term. A stored term names itself; a term
#          that must not be written down needs a name that is not its text.
# secret — the term's text, and any line carrying it, are themselves the leak.
#          Set only on environment-supplied terms, and the single switch every
#          redaction below reads.
Term = namedtuple("Term", "text leak label secret", defaults=(None, False))

DENY = [
    Term("supersmart",
         "the private predecessor plugin, whose pressure-campaign transcripts "
         "are the evidence base behind several shipped hooks"),
    Term("lens_danger_off",
         "lens-master's danger-hook escape hatch — publishing the name of the "
         "switch that turns an enforcement hook off is publishing the bypass"),
    Term("keeper_re",
         "the Secret Keeper matcher constant — naming it exposes the shape of "
         "what the hook catches, and by omission what it misses"),
    Term("undertaker_re",
         "the Data Undertaker matcher constant — same exposure"),
    Term("git_destroy_re",
         "the git-destruction matcher constant — same exposure, over the "
         "family whose miss is unrecoverable"),
    Term("danger-lenses.py",
         "the danger hook's filename: a path that exists only in the private "
         "repo, and a pointer to the file a reader would go looking for"),
    Term("lens-master/hooks",
         "an in-tree path from when the two plugins shared a repo — the bare "
         "name in prose is fine, a path under it is residue"),
    Term("lens-master/tests",
         "likewise: the companion's suite moved out with the companion"),
    Term("danger_matchers",
         "the matcher unit test, moved to the private repo with the hook it "
         "covers"),
    # A heading, not the bare name. `lens-master` in prose is ALLOWED and
    # deliberate — the README's companion section and the CONTRIBUTING
    # checklist both name it. Only the release prose is private, and a "## "
    # heading is what that prose is filed under.
    Term("## lens-master",
         "a changelog heading: the companion's release notes are its own "
         "repo's to publish"),
]

# Tag names are matched as globs rather than substrings, because the residue
# here is a naming convention: every pre-split release of the companion was
# tagged in the shared repo, and those tags belong to the private archive.
DENY_TAGS = [("lens-master--v*", "a companion release tag from the shared repo")]

# This file names every term it hunts for, so scanning it would flag it — the
# gate would be its own only finding, forever. Excluded by path, which is the
# honest trade: residue hidden *inside* this file is the one place the gate
# cannot see, and that is a thing a reviewer of this file can see instead.
SELF = "tests/public_gate.py"

MAX_EXAMPLES = 3   # per term; the count is the finding, the lines are the lead
MAX_WIDTH = 140    # a minified or generated line must not own the report

# --- Identity terms, which cannot live in this file --------------------------
#
# Every term above is a pointer to something private. An identity is not a
# pointer, it *is* the private thing, so hunting one from a stored list would
# leak the name in the act of proving it gone. Identity terms therefore arrive
# out of band: colon-separated in PUBLIC_GATE_PRIVATE_TERMS, lowered on intake,
# matched as plain substrings over exactly the corpus the stored terms are
# matched over, and counted toward the failing total in exactly the same way.
# Nothing about the matching is different. Only the reporting is.
#
# The environment specifically, and not an argument: a command line is echoed
# into the CI job log by the runner before the step even starts, and stays
# readable in `ps` for as long as the process lives. A value handed to the step
# as a secret is masked wherever the runner sees it reappear.
#
# "Wherever it sees it reappear" is doing less work than it looks like, and
# that is why the report below censors itself instead of trusting the masker.
# GitHub Actions masks a secret's *whole value*; nobody has told it what that
# value's parts are, so a report that split the list and printed one term, or
# that quoted the history line a term matched, would print something the
# masker never learned to hide — into a log that outlives the run. So a
# private finding is named by its position in the list and evidenced by
# location alone: `1a2b3c4d5 path/to/file` is a place, not a payload, and a
# place is the entire thing someone about to rewrite a history needs.
#
# One location is both, and it is the reason locations are censored rather than
# merely trusted. A hit in a ref *name* is located at `ref refs/heads/<name>`,
# where the name is the leak, so the place carries the payload inside it. The
# report prints it anyway, through the censor like every other line, because
# `ref refs/heads/wip/[private]` still says which ref to delete.
#
# Unset or empty is a skip and not a failure — a fork's pull_request run is
# handed no secrets, and a gate that failed there would fail for every
# contributor who is not the maintainer. The skip prints, though: an absent
# scan that said nothing would read, in the log, exactly like one that cleared.
PRIVATE_ENV = "PUBLIC_GATE_PRIVATE_TERMS"
PRIVATE_LEAK = ("an identity term supplied by the environment — its text and "
                "the lines it matched are themselves the leak, so this report "
                "carries neither")


def private_terms(raw):
    """The environment's terms: positionally labelled, and marked secret so
    the reporter knows it is holding something it must not print.

    Numbered over the terms actually scanned rather than over the raw split,
    so `#2` is the second term the gate looked for and agrees with the count
    printed beside them. Blank tokens are dropped rather than numbered: a
    secret stored with a stray separator or a trailing newline should not
    renumber the terms a maintainer is trying to map a finding back to."""
    kept = [part.strip().lower() for part in (raw or "").split(":")]
    return [Term(text, PRIVATE_LEAK, f"private term #{i} (environment)", True)
            for i, text in enumerate([t for t in kept if t], 1)]


# --- The gate's own diagnostics, which are output too ------------------------
#
# Everything above guards the *findings*: a private term is named by position,
# and scan() does not even keep the line it matched. None of it guards the
# gate's own bookkeeping, and bookkeeping is a log line like any other. The
# banner names the checkout it scanned, and a checkout path is
# `/home/<username>/project` — so on the machine where a maintainer actually
# runs this, the first line printed hands over the very identity the terms were
# supplied to hunt, immediately above the line promising it never would. The
# refusals do it too: "not a git repository" and "shallow clone" both name the
# path, and both fire before any scan they could have been protecting.
#
# So the terms are read at import, before this file is able to print anything
# at all, and every string the gate emits — stdout line, exit message, and
# git's own complaint on the way through — goes out through censor() first. The
# mask replaces the term and nothing around it, because
# `/home/[private]/Claude/Opulent` still answers "which checkout was that?",
# and that question is the only reason the banner exists.
PRIVATE_MASK = "[private]"
PRIVATE = private_terms(os.environ.get(PRIVATE_ENV))


def censor(s):
    """`s` with every occurrence of every private term masked.

    Case-insensitive and exhaustive, because a path routinely carries the same
    term more than once and in more than one casing, and a censor that stops at
    the first hit or that only matches the casing the operator happened to type
    has not censored the path. Masked greedily from the left, so overlapping
    occurrences lose their overlap to the one that started first and no run of
    the term's own text is left behind either way.

    A term that is a substring of the mask is masked to nothing instead — the
    single case where a fixed mask would reprint what it stands in for."""
    for term in PRIVATE:
        mask = "" if term.text in PRIVATE_MASK.lower() else PRIVATE_MASK
        low, out, i = s.lower(), [], 0
        j = low.find(term.text)
        while j != -1:
            out.append(s[i:j])
            out.append(mask)
            i = j + len(term.text)
            j = low.find(term.text, i)
        out.append(s[i:])
        s = "".join(out)
    return s


def say(line):
    """Print, censored. The gate has one mouth, so a line added later is
    covered by construction rather than by whoever remembers to wrap it."""
    print(censor(line))


def excepthook(kind, exc, tb):
    """A traceback, censored — the gate's deliberate deaths censor themselves,
    and the interpreter's must too.

    say() and the SystemExits cover every line the gate means to write. A crash
    is not one of those: no git binary on the PATH, a subprocess that outlived
    its timeout, and the interpreter prints the traceback instead — naming this
    script's own absolute path in every frame, and, for a timeout, the argv it
    gave up on, `-C <repo>` and all. A hygiene tool that leaks on the way down
    has picked the worst possible moment to do it.

    SystemExit never arrives here — the interpreter handles it before it
    consults this hook — so the refusals above keep their single censoring and
    are neither masked twice nor swallowed. The exit status is left alone too:
    an unhandled exception is a 1 whether this hook exists or not."""
    sys.stderr.write(censor(
        "".join(traceback.format_exception(kind, exc, tb))))


sys.excepthook = excepthook


def git(repo, *args, ok=(0,)):
    """A git command, or a loud death. `ok` widens the accepted exit codes for
    the one case where failure is information rather than breakage."""
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                       text=True, errors="replace", timeout=600)
    if p.returncode not in ok:
        # git's own complaint is passed through, and git names paths freely —
        # so it is censored on the way out like anything else this file says.
        sys.stderr.write(censor(p.stderr))
        raise SystemExit(censor(
            f"public gate: `git {' '.join(args[:3])}` exited {p.returncode} in "
            f"{repo} — the object database could not be read, so nothing here "
            f"has been cleared"))
    return p


def history(repo):
    """Every commit reachable from any ref, message and patch alike.

    `--full-history` because path-limited log otherwise simplifies commits
    away, and a commit git considers uninteresting can still carry a secret.
    A repo with no commits yet scans as empty rather than failing: there is
    nothing in it to leak."""
    if git(repo, "rev-list", "--all", "--count").stdout.strip() in ("", "0"):
        return ""
    return git(repo, "log", "--all", "--full-history", "-p", "--no-color",
               "--", ":/", f":(top,exclude){SELF}").stdout


def scan(text, terms):
    """Hits per term, each carrying where it was found — because "the term is
    in your history somewhere" is a finding nobody can act on. Three kinds of
    location, one per kind of line the corpus is made of: a commit for a hit in
    a message, that commit and a path for a hit inside a patch, and the ref
    itself for a hit in a name. The patch-stream half is best-effort, since it
    attributes by the last header that streamed past; a ref name arrives
    already labelled and is exact.

    A secret term's matched line is not kept at all. The renderer would refuse
    to print it, but a report cannot print what the scan never held, and that
    is the version of this promise that survives an edit to the renderer."""
    hits = {t: [] for t in terms}
    commit, where = "?", "(no commit)"
    for line in text.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1][:9]
            where = f"{commit} commit message"
        elif line.startswith("diff --git "):
            # The header names the path even for a delete, where +++ is
            # /dev/null and the removed content is the whole point.
            where = f"{commit} {line.split(' b/')[-1]}"
        elif line.startswith("+++ b/"):
            where = f"{commit} {line[6:]}"
        elif line.startswith("refname "):
            # A ref name inherits nothing: it is not in the patch stream, and
            # the ref *is* the place. Without this the hit would be filed under
            # whichever commit and file happened to stream past last — a
            # location that does not contain the term, which for a secret term
            # is the whole of the evidence and therefore fatal. Nothing git
            # prints can be mistaken for one of these: every line of a patch
            # body carries a prefix, and a message body is indented.
            where = f"ref {line[8:]}"
        low = line.lower()
        for term in terms:
            if term.text in low:
                hits[term].append(
                    (where, None if term.secret else line.strip()[:MAX_WIDTH]))
    return hits


def main(repo):
    repo = os.path.abspath(repo)
    # Both refusals name the path, and both fire before a term has been
    # matched — which is why PRIVATE is read at import rather than here. A
    # first line in this function would be early enough today, and would stop
    # being early enough the first time anything printed above it.
    if git(repo, "rev-parse", "--is-inside-work-tree", ok=(0, 128)).returncode:
        raise SystemExit(censor(f"public gate: {repo} is not a git repository"))
    if git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        raise SystemExit(censor(
            f"public gate: {repo} is a shallow clone, which is not the object "
            f"database — check out with fetch-depth: 0 and run this again"))

    terms = DENY + PRIVATE

    text = history(repo)
    tags = git(repo, "tag", "-l").stdout.split()
    branches = git(repo, "branch", "-a", "--format=%(refname)").stdout.split()
    say(f"scanned: {text.count(chr(10)) + bool(text)} lines of history, "
        f"{len(tags)} tags, {len(branches)} branches in {repo}")
    if PRIVATE:
        say(f"private terms: {len(PRIVATE)} supplied via {PRIVATE_ENV}, "
            f"matched but never echoed")
    else:
        say(f"private terms: scan skipped — {PRIVATE_ENV} is unset or empty. "
            f"Not a failure; a run without secrets has none to scan for.")

    # Ref names are history too — a branch or tag can carry in its name what
    # the tree it points at never says. They join the same corpus as synthetic
    # `refname ` lines, which scan() attributes to the ref rather than to the
    # patch above them. The separating newline is not decoration: a ref glued
    # to the tail of the last patch line is not a ref line any more, and its
    # hit goes back to being filed under the last file git happened to print.
    refs = "\n".join(f"refname {r}" for r in tags + branches)
    hits = scan(f"{text}\n{refs}", terms)
    bad_tags = [(pattern, why, [t for t in tags
                                if fnmatch.fnmatch(t.lower(), pattern)])
                for pattern, why in DENY_TAGS]
    bad_tags = [(p, why, found) for p, why, found in bad_tags if found]

    def report(label, leak, found, render):
        say(f"\nFAIL  {label}: {len(found)} hit(s) — {leak}")
        for item in found[:MAX_EXAMPLES]:
            say(f"        {render(item)}")
        if len(found) > MAX_EXAMPLES:
            say(f"        … and {len(found) - MAX_EXAMPLES} more")

    for term in terms:
        if not hits[term]:
            continue
        # The branch that matters. On the secret side the term is named by its
        # position and evidenced by location; everything a reader could
        # reconstruct it from — the text, and the lines it appeared in — lives
        # on the other side and is never reached for it.
        #
        # Both sides still go out through say(), and each side needs it for its
        # own reason. On the non-secret side a *stored* term's matched line is
        # printed in full, and a line carrying `lens-master/hooks` is exactly
        # the kind of line that carries `/home/<username>/` in front of it. On
        # the secret side the location can be the term: a ref-name hit is
        # located at the name that leaked, so the censor is what makes printing
        # the only evidence there is safe to print.
        if term.secret:
            report(term.label, term.leak, hits[term], lambda h: h[0])
        else:
            report(repr(term.text), term.leak, hits[term],
                   lambda h: f"{h[0]}: {h[1]}")
    for pattern, why, found in bad_tags:
        report(f"tag {pattern!r}", why, found, str)

    total = sum(1 for t in terms if hits[t]) + len(bad_tags)
    if total:
        raise SystemExit(censor(
            f"\npublic gate: {total} denied term(s) present. This history is "
            f"not publishable — the residue lives in the object database, so "
            f"editing the working tree does not remove it."))
    say(f"public gate: clean — none of the {len(DENY)} denied terms, "
        f"{len(PRIVATE)} private terms or {len(DENY_TAGS)} denied tag "
        f"patterns appear anywhere in the object database")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))),
        help="checkout to scan (default: the repo this script lives in)")
    main(ap.parse_args().repo)
