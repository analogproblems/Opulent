#!/usr/bin/env python3
"""Public-hygiene gate: scans the whole object database for private residue.

This repo once shared a home with a lens plugin, and the stored list below
hunted that plugin's internals — the matcher constants, the escape-hatch
variables, the file paths they lived at, and its release prose. That plugin
was published under its own name in 2026-08, so the list they justified went
empty as of 0.13.0, and it stays empty: a term is not secret once its subject
ships in public.

What is left is the machinery, which was never about that plugin. A working
tree can be cleaned in an afternoon; a history keeps every draft of it
forever. So this reads the object database — literally every object git
holds, via `cat-file --batch-all-objects`, plus every ref name — rather than
the checkout. That is the corpus the identity terms still run over, and the
corpus a new stored term would run over the day one is needed.

It read `git log --all -p` until 2026-08-13, and that was not the object
database: `log -p` renders reachable-history *diffs*, a strict subset that
omits merge-commit conflict resolutions (`-p` prints no patch for a merge),
unreachable and reflog-held objects, binary blobs, annotated tag messages,
committer identity, and refs outside heads/remotes. The miss was not
theoretical — this gate certified a checkout clean while all ten stored terms
of the day sat in its object database, in objects `log` cannot reach. Enumerating objects
instead closes that whole family at once, because there is nothing under an
object database that `--batch-all-objects` does not enumerate.

Three properties worth stating out loud:

- **It fails closed.** The runtime hooks fail open by house rule: a hook that
  cannot parse its payload allows, because a broken hook must never brick a
  session. A hygiene gate is the opposite. A scan that could not read the
  object database has not cleared it, and reporting "clean" is the one outcome
  worse than a false alarm.
- **It is a denylist.** It proves the absence of the terms below and nothing
  more. A leak nobody wrote down is a leak nobody is checking for, so a new
  private mechanism means a new entry here, in the same commit. An empty
  stored list therefore says one thing only — that no stored mechanism is
  private right now — and never that the check has been switched off.
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
import re
import subprocess
import sys
import traceback
import unicodedata
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

# Empty as of 0.13.0, and empty on purpose rather than by neglect. Every term
# this list held named an internal of the lens plugin this repo used to share a
# home with — its matcher constants, its danger-hook escape hatch, the
# filenames they lived in, the shared-repo paths from before the split, its
# release-note headings — and every one of them was published. A denylist entry
# whose subject is published is worse than no entry at all: it fails a gate
# nobody can satisfy, and it teaches the next reader that a public name is a
# secret one.
#
# This list is the part of the gate meant to change. A new private mechanism
# means a new Term here, in the commit that creates it. An identity is the one
# thing that never goes here — those arrive through PUBLIC_GATE_PRIVATE_TERMS
# below, for the reason spelled out there.
DENY = []

# Tag names are matched as globs rather than substrings, because the residue
# this path exists for is a naming convention rather than a word. Empty for the
# same reason the list above is: its one glob covered the pre-split release
# tags of the plugin that used to live here, those releases went public, and no
# tag in this repo matches it.
DENY_TAGS = []

# This file names every term it hunts for, so scanning it would flag it — the
# gate would be its own only finding, forever. That stays true of every past
# revision now that the stored list is empty, which is what SELF_MARKER below
# is for. Excluded by path, which is the honest trade: residue hidden *inside*
# this file is the one place the gate cannot see, and that is a thing a
# reviewer of this file can see instead.
SELF = "tests/public_gate.py"

# Recognises a copy of this file by content, not just by path — every past
# revision of it carries this sentence, and a revision at an older path would
# otherwise become a permanent finding the moment the file moved.
SELF_MARKER = "gate: scans the whole object database"

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
    renumber the terms a maintainer is trying to map a finding back to.

    Newlines separate as well as colons. A multi-line secret is the default
    shape for this value in a CI secret store, and splitting on `:` alone kept
    the newline *inside* the term — where it could never match, since the
    corpus is matched line by line. That produced the one outcome this file
    exists to prevent: a term reported as supplied and matched, a run reported
    as clean, and nothing actually scanned for."""
    kept = [part.strip().lower() for part in re.split(r"[:\r\n]+", raw or "")]
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


def variants(text):
    """A term as it can legitimately appear: both Unicode normal forms.

    An identity term is usually a name, and a name with an accent has two
    equally valid encodings — `é` as one code point or as `e` plus a combining
    mark. They are the same name to a reader and different strings to `in`.
    A gate that matched only the form the operator happened to type would
    clear a history that carries the other one."""
    return {v for v in (unicodedata.normalize("NFC", text),
                        unicodedata.normalize("NFD", text)) if v}


def censor(s):
    """`s` with every occurrence of every private term masked.

    Case-insensitive and exhaustive, because a path routinely carries the same
    term more than once and in more than one casing, and a censor that stops at
    the first hit or that only matches the casing the operator happened to type
    has not censored the path. Masked left to right and non-overlapping, so
    overlapping occurrences lose their overlap to the one that started first.

    Offsets are taken against `s` itself, via a case-insensitive regex, and
    that is load-bearing rather than stylistic. This searched a `s.lower()`
    copy and sliced the original until 2026-08-13 — but `str.lower()` is not
    length-preserving (U+0130 lowers to two characters), so every such
    character ahead of a match slid the mask further right, and past the first
    one the mask stopped covering the term at all: the term printed in full,
    on the line directly above the promise that it never does. A match found
    in the string being edited cannot drift from it.

    A term that is a substring of the mask is masked to nothing instead — the
    single case where a fixed mask would reprint what it stands in for."""
    for term in PRIVATE:
        mask = "" if term.text in PRIVATE_MASK.lower() else PRIVATE_MASK
        for form in variants(term.text):
            # A function replacement, so a mask containing a backslash or a
            # group reference is inserted literally rather than interpreted.
            s = re.sub(re.escape(form), lambda _m: mask, s, flags=re.IGNORECASE)
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


def git_bytes(repo, *args):
    """Like git(), but undecoded — object contents are not all text, and a
    blob decoded with `errors="replace"` has had its non-UTF-8 bytes turned
    into U+FFFD before any term could be matched against them."""
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True,
                       timeout=600)
    if p.returncode != 0:
        sys.stderr.write(censor(p.stderr.decode("utf-8", "replace")))
        raise SystemExit(censor(
            f"public gate: `git {' '.join(args[:3])}` exited {p.returncode} in "
            f"{repo} — the object database could not be read, so nothing here "
            f"has been cleared"))
    return p.stdout


def objects(repo):
    """Every object git holds, contents included: (sha, type, body-bytes).

    `--batch-all-objects` is the whole point of this file. It enumerates the
    object database itself — including objects no ref can reach, which is
    where residue lands after the `reset --hard` or history rewrite that a
    failure of this gate tells someone to perform."""
    raw = git_bytes(repo, "cat-file", "--batch-all-objects", "--batch",
                    "--buffer")
    i, n = 0, len(raw)
    while i < n:
        nl = raw.find(b"\n", i)
        if nl == -1:
            break
        header = raw[i:nl].decode("utf-8", "replace").split()
        if len(header) < 3 or not header[2].isdigit():
            i = nl + 1          # a missing/!-marked object: nothing to read
            continue
        sha, otype, size = header[0], header[1], int(header[2])
        yield sha, otype, raw[nl + 1:nl + 1 + size]
        i = nl + 1 + size + 1


def blob_places(repo):
    """blob sha -> sorted (commit, path) pairs it is stored at.

    A finding needs somewhere to point, and the commit is the half that can be
    acted on: "the residue lives in the object database" is advice to rewrite
    a history, and a history is rewritten by commit. The path says which file
    to look in once you are there.

    An unreachable blob has neither by definition — nothing indexes it — so it
    is reported by its own sha, which is still exactly what `git cat-file -p`
    needs to show a maintainer what leaked."""
    places = {}
    if git(repo, "rev-list", "--all", "--count").stdout.strip() in ("", "0"):
        return places
    for commit in git(repo, "rev-list", "--all").stdout.split():
        for line in git(repo, "ls-tree", "-r", "--full-tree",
                        commit).stdout.splitlines():
            meta, _, path = line.partition("\t")
            bits = meta.split()
            if len(bits) >= 3 and path:
                places.setdefault(bits[2], set()).add((commit[:9], path))
    return {sha: sorted(v) for sha, v in places.items()}


def corpus(repo):
    """The whole object database plus every ref name, as (location, text).

    Located per object rather than by streaming attribution. The old patch
    stream had to guess — it filed a hit under whichever `+++` header had gone
    past most recently — and a guess is not good enough for a secret term,
    where the location is the entire finding. An object knows its own name.

    Trees are scanned because a *filename* is residue as surely as a file's
    contents, and a filename that only ever existed inside a merge result
    appears in no diff anywhere."""
    places = blob_places(repo)
    for sha, otype, body in objects(repo):
        text = body.decode("utf-8", "replace")
        if otype == "blob":
            where = places.get(sha, [])
            # This file names every term it hunts, so scanning any copy of it
            # would make the gate its own only finding, forever. Matched on
            # content as well as path: an older revision of it is still a copy
            # of it, and after a rename the path alone would stop recognising
            # one.
            if (where and all(p == SELF for _, p in where)) or SELF_MARKER in text:
                continue
            if where:
                commit, path = where[0]
                extra = f" (+{len(where) - 1} more)" if len(where) > 1 else ""
                yield f"{commit} {path}{extra}", text
            else:
                # Unreachable: no commit and no path exist to name. This is
                # the case `git log -p` could not see at all, and the one a
                # history rewrite leaves behind.
                yield f"{sha[:9]} (unreachable blob)", text
        elif otype == "commit":
            # The raw object, so `committer` is scanned and not just `author`:
            # `git log` prints one of the two by default, GitHub shows both.
            yield f"{sha[:9]} commit object", text
        elif otype == "tag":
            yield f"{sha[:9]} tag object", text
        elif otype == "tree":
            # Binary: 'mode name\0<20 raw bytes>'. The names are the only part
            # worth scanning, and the shas between them are hex noise that
            # would never match a term anyway.
            names = re.findall(rb"[^\x00]*? ([^\x00]+)\x00", body)
            yield (f"{sha[:9]} tree",
                   "\n".join(n.decode("utf-8", "replace") for n in names))
    for ref in git(repo, "for-each-ref", "--format=%(refname)").stdout.split():
        # A ref name inherits nothing and the ref *is* the place — which for a
        # secret term means the location carries the payload. It is printed
        # anyway, through the censor, because `ref refs/heads/wip/[private]`
        # still says which ref to delete.
        yield f"ref {ref}", ref


def scan(chunks, terms):
    """Hits per term, each carrying where it was found — because "the term is
    in your history somewhere" is a finding nobody can act on.

    Takes (location, text) pairs, so a hit is attributed to the object it was
    actually found in rather than to whichever header last streamed past.

    Matching is case-insensitive and normalization-insensitive: each line is
    compared in both Unicode normal forms, because a term and a history can
    spell the same accented name two equally valid ways.

    A secret term's matched line is not kept at all. The renderer would refuse
    to print it, but a report cannot print what the scan never held, and that
    is the version of this promise that survives an edit to the renderer."""
    hits = {t: [] for t in terms}
    wanted = [(t, variants(t.text)) for t in terms]
    for where, text in chunks:
        for line in text.splitlines():
            low = line.lower()
            forms = {low, unicodedata.normalize("NFC", low),
                     unicodedata.normalize("NFD", low)}
            for term, term_forms in wanted:
                if any(f in form for f in term_forms for form in forms):
                    hits[term].append(
                        (where,
                         None if term.secret else line.strip()[:MAX_WIDTH]))
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

    tags = git(repo, "tag", "-l").stdout.split()
    chunks = list(corpus(repo))
    say(f"scanned: {len(chunks)} objects and refs, {len(tags)} tags in {repo}")
    if PRIVATE:
        say(f"private terms: {len(PRIVATE)} supplied via {PRIVATE_ENV}, "
            f"matched but never echoed")
    else:
        say(f"private terms: scan skipped — {PRIVATE_ENV} is unset or empty. "
            f"Not a failure; a run without secrets has none to scan for.")

    # Ref names are history too — a branch or tag can carry in its name what
    # the tree it points at never says. corpus() yields them as their own
    # located chunks, so a ref hit is filed against the ref rather than
    # against whatever object happened to be enumerated before it.
    hits = scan(chunks, terms)
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
        # printed in full, and a line carrying a stored path term is exactly
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
    # A gate with nothing to hunt reports that, not "clean". Green on an empty
    # search is the shape of a check that has quietly stopped checking, and
    # this file's whole argument is that a scan which cleared nothing must
    # never read as a scan that cleared something.
    if not terms and not DENY_TAGS:
        say("public gate: nothing to scan for — the stored list, the tag "
            "globs and " + PRIVATE_ENV + " are all empty. The corpus was read "
            "and holds no residue of anything this gate was told to hunt, "
            "which is not the same as holding none.")
        return
    say(f"public gate: clean — none of the {len(DENY)} denied terms, "
        f"{len(PRIVATE)} private terms or {len(DENY_TAGS)} denied tag "
        f"patterns appear anywhere in the object database")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))),
        help="checkout to scan (default: the repo this script lives in)")
    main(ap.parse_args().repo)
