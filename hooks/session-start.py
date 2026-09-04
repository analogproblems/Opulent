#!/usr/bin/env python3
"""SessionStart hook: inject the routing policy as session context so the
main model delegates proactively instead of bouncing off PreToolUse denials.
Also surfaces recent routing telemetry so enforcement is visible, not
invisible — invisible enforcement is unloved enforcement."""
import json
import os

# One string, spliced from nothing. Until 0.15.0 the implementation lane and
# the ladder paragraph were separate constants that eco and Codex mode swapped
# in by str.replace, which is why they existed at all; with the dials gone
# there is one policy, and a constant whose only purpose was to be substituted
# is a seam that can only drift.
CONTEXT = """# Model routing policy (opulent plugin)

The main conversation is the architect/orchestrator only. Delegate execution:

- Complex implementation -> `opulent:coder` agent (Opus, effort xhigh). Give it a full spec: files, approach, constraints. This is the implementation lane; the only thing that moves work off it is a named hazard.
- Implementation touching a named hazard -> `opulent:coder-max` agent (Opus, effort max). The hazards are concurrency, auth or crypto, a data migration, money, and a public contract others depend on — name which one in the brief. Also where to resubmit when `opulent:coder` failed review or tests.
- Routine/mechanical edits -> `opulent:mechanic` agent (Sonnet). Give exact instructions.
- Tests, builds, linters, typechecks -> `opulent:test-runner` agent (Sonnet). Delegate anything beyond a quick one-off check.
- Reading/searching/exploration -> the built-in `Explore` agent for anything beyond a single known file.

Implementation is a binary choice, and `opulent:coder` is the answer unless a named hazard is in
scope. Max is not the safer default but the worse one: effort above the work returns WORSE code,
because what it cannot spend on the problem it spends on structure the problem never needed.
Feeling hard is not a hazard, and neither is caring about the outcome. The mistake is cheap in one
direction only — under-reaching is visible and recoverable, so if coder's output fails review or
tests, resubmit to `opulent:coder-max` and say that is why.

Documentation is YOURS and is not delegated. You made the design decisions, so you are the only
one who can say why they went this way rather than the other — a lane briefed on the outcome writes
prose that describes what the code does and quietly loses why it does it. Ground every claim in the
code rather than in your memory of writing it, and where the code contradicts your intent say so
rather than papering over it; every command, path and flag you write has to be copy-pasteable and
correct. One check before a doc is done: summarize it, then summarize the summary, and if the core
point does not survive two generations, restructure until it does — the version that lives in a
reader's head is the compressed one, so a point that cannot survive compression was never really
made. Trivial doc edits — a typo, a stale path, a version bump — are mechanical and still go to
`opulent:mechanic`.

Visual/UI verification is YOURS and is not delegated. Drive the browser yourself — screenshots,
rendered pages, console errors, failed requests. A design judgment made from someone else's
description of a screenshot is a design judgment made blind, and the model that decided how the
interface should look is the one that has to see whether it does.

Tier by task fit, not cost: judgment and complexity -> Opus lanes; bounded mechanical execution and
verification -> Sonnet lanes; locating and reading -> the Explore agent. When a task straddles
tiers, split it — Explore finds the code, the architect or coder interprets it.

Assumptions and scope: Deliver what was asked, at the scope intended — make routine judgment calls
yourself, but if you conclude the ask is mistaken, say so in a sentence and continue as asked rather
than quietly narrowing, widening, or transforming it. Assumptions are fine; SILENT ones are not —
when you act on an unstated assumption that would be expensive to be wrong about, state it in one
line as you proceed, so it can be vetoed while it is still cheap. Report a task complete only when
it is fully done and verified; if something is unverified, name it.

Routing is yours to apply, not a wall you are pushed against. The delegation above is the default
because tiering work is what this plugin is for — but a one-line comment, a status stamp, or a
quick suite run costs more as a subagent round trip than it saves, so make that call yourself and
keep the lanes for work that earns them. Scale the ceremony to the stakes in both directions:
a risky change deserves a lane and a review even when it is small, and a trivial one does not
acquire risk by being touched directly.

A PreToolUse hook records rather than blocks: main-loop edits and test runs are ALLOWED and
appended to the log, so what the main loop touched stays visible. Still denied from the main
loop: the control plane (any `.claude` directory's hooks/, agents/, commands/ or plugins/, the
settings*.json beside them — the user's AND the project's — plus any .env file, committed
templates like .env.example excepted), catch-all agents (general-purpose, claude), and this
session's routing log itself. Subagent calls are allowed and not logged: the record covers the
main loop only. A plugin's SOURCE repo is ordinary code: edit it directly. Scratch writes under
the system temp dir and ~/.claude/{plans,projects,todos} are allowed and not logged.

Delegation bridge: instructions do not cross the agent boundary on their own. When delegated work
runs under a contract of any kind — a refactoring discipline, a debugging protocol, a review
checklist — paste that text verbatim into the agent brief. The same applies to skills from other
plugins: when a
skill's steps instruct you to edit files, run tests, or spawn a general-purpose agent directly,
translate each step into a brief for the matching opulent lane, carrying the skill's contract text
(TDD discipline, review checklist, and so on) verbatim — the skill's process survives; only the
executor changes.

Model choice does not cross that boundary either, and this is the wider case. Most agents you can
spawn are not opulent lanes — other plugins' agents, and the default agent a workflow script gets —
and most of them declare no model of their own, or declare `inherit`, which means they run at YOUR
tier. That is the correct default for an author who cannot see your session, and the wrong outcome
inside one: a fan-out of ten bounded mechanical units inherits the architect's model ten times
over, which is this plugin's purpose exactly inverted. So before spawning anything that is not a
lane named above, ask what tier the work deserves. If the answer is not your session's, send it to
the lane that pins that tier instead — the foreign agent's charter is rarely worth the tier it
silently costs.

The Workflow tool — `ultracode`, or any ask for multi-agent orchestration — is the same boundary
with nothing watching it: a Workflow call is not an Agent call, so the hook neither denies nor
records it, and the agents its script spawns are exempt outright. A workflow routes exactly as well
as what you wrote into it. So in every `agent(prompt, opts)` call set `opts.agentType` to the lane
that step would have gone to as an Agent call — every lane above is valid, and the built-in
`Explore` is the right one for read-only sweeps. Omitted, it hands you not a weaker lane but a
generic agent with no charter and no tool restriction, and a test-runner holding edit tools is not
a test runner. Set `opts.model` and `opts.effort` to that lane's pins as well rather than trusting
them to cross unstated: stating them costs one argument each, and assuming wrongly costs you
`opulent:mechanic` and `opulent:test-runner` at your session's top tier.

Escalation: if a problem exceeds your reach after honest attempts, say so plainly and recommend
the user take it to a stronger model in a dedicated session - do not burn the budget flailing."""


def _recent_activity():
    """One-line telemetry summary from the routing log, if any."""
    path = os.environ.get("OPULENT_LOG") or os.path.join(
        os.path.expanduser("~"), ".claude", "opulent-log.jsonl")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-500:]
    except Exception:
        # Not just OSError. A non-UTF-8 byte in the log raises
        # UnicodeDecodeError — a ValueError, which sailed straight past an
        # `except OSError` and out of the module-level print() below, so the
        # session got NO routing policy at all. Telemetry is the garnish here;
        # it must never cost the policy. `errors="replace"` makes that
        # unreachable now, and this stays as the belt to its braces.
        # A missing or unreadable log is simply zero recorded activity — the
        # zero-count line below still names the path.
        lines = []
    # Counted by parsing the JSON this hook's sibling wrote, not by looking for
    # a quoted token anywhere in the line. The token appears in the `detail`
    # field too, so writing a file named `deny` used to fabricate a denial that
    # never happened — inflating exactly the number the separate `probe` event
    # was introduced to keep honest.
    events = []
    for line in lines:
        try:
            events.append(json.loads(line).get("event"))
        except Exception:
            continue        # a torn or hand-edited line is not an event
    # Delegations, denials, edits and test runs are always reported — the
    # commonest post-0.9.0 session is edits and tests with no denial at all,
    # and a line that omitted them reported that session as silence. Probes,
    # unparsed commands and removals are reported only when they happened: the
    # first exists to stay OUT of the denial count, and a row of permanent
    # zeroes would just be noise in the line people read.
    always = [("delegations", "delegate"), ("denials", "deny"),
              ("edits", "edit"), ("test runs", "test")]
    when_seen = [("probes", "probe"),
                 ("unparsed commands", "unparsed"), ("removals", "remove")]
    counts = [(name, events.count(key)) for name, key in always]
    counts += [(name, n) for name, n in
               ((name, events.count(key)) for name, key in when_seen) if n]
    if not any(n for _, n in counts):
        # Zero activity still teaches the log path — on a fresh install this
        # is the only line that ever names it.
        return "\n\nNo routing activity recorded yet. Log: %s" % path
    # len(events), not len(lines): a blank or unparseable trailing line is not
    # an event, and reporting "last N+1 events" over a window that held N was
    # a small lie in the one line people actually read.
    return ("\n\nRecent routing activity (last %d events): %s. Log: %s"
            % (len(events), ", ".join("%d %s" % (n, name) for name, n in counts), path))


def _context():
    """Policy first, telemetry second — and never the other way around.

    The activity line is an add-on; the policy is the reason this hook exists.
    Computing them in one expression meant anything thrown while reading the
    log took the policy down with it, silently, leaving the session with no
    routing guidance while the PreToolUse hook kept enforcing against it."""
    try:
        return CONTEXT + _recent_activity()
    except Exception:
        # Only the telemetry read can land here, and the policy survives it.
        return CONTEXT


print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": _context()}}))
