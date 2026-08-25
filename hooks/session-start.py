#!/usr/bin/env python3
"""SessionStart hook: inject the routing policy as session context so the
main model delegates proactively instead of bouncing off PreToolUse denials.
Also surfaces recent routing telemetry so enforcement is visible, not
invisible — invisible enforcement is unloved enforcement."""
import json
import os

# Spliced into CONTEXT rather than typed into it, and therefore defined above
# it: eco mode replaces this paragraph wholesale, and a constant that merely
# looked like the text in CONTEXT would substitute nothing the day the two
# drifted apart. CODER_LINE below is the older, hand-matched form of the same
# trick — which is why CI checks that it still matches.
LADDER_PARA = """The coder lane is a ladder — one charter, four effort rungs. Pick the rung AFTER you have
written the spec, from what the spec says, not from how the task felt before you wrote it. A rung
above the work does not merely cost more — it returns WORSE code, because the effort it cannot
spend on the problem it spends on structure the problem never needed. Under-reaching is visible
and recoverable; over-reaching is neither, which is why the reflex to escalate is the one to
distrust.

Three questions decide the rung, and all three are answerable from the spec in front of you.
Can you name every file the change touches? Would an existing test, typecheck or lint catch a
wrong answer? Does it touch a named hazard — concurrency, auth or crypto, a data migration,
money, or a public contract others depend on?

- All three favourable (every file named, a check catches it, no hazard) -> `opulent:coder-lite` (medium).
- A few known files, no hazard, an answer that needs reading to find but whose shape is clear -> `opulent:coder-high` (high).
- Files you cannot all name up front, or finding the right change is itself part of the job -> `opulent:coder` (xhigh) — the default when none of the others clearly fits.
- A named hazard in scope, OR a lower rung already attempted this task and failed review or tests -> `opulent:coder-max` (max). Name which of the two in the brief; feeling hard is not a hazard, and neither is caring about the outcome.

A misroute self-corrects: if a rung's output fails verification, resubmit one rung up. That
recovery is cheap and it is the reason the ladder is safe to descend."""

CONTEXT = """# Model routing policy (opulent plugin)

The main conversation is the architect/orchestrator only. Delegate execution:

- Complex implementation -> `opulent:coder` agent (Opus, effort xhigh) — the ladder's default rung, not its only one; pick from the ladder below. Give it a full spec: files, approach, constraints.
- Routine/mechanical edits -> `opulent:mechanic` agent (Sonnet). Give exact instructions.
- Tests, builds, linters, typechecks -> `opulent:test-runner` agent (Sonnet). Delegate anything beyond a quick one-off check.
- Visual/UI verification (screenshots, rendered pages, console errors) -> `opulent:ui-checker` agent (Sonnet).
- Documentation beyond a one-line fix (READMEs, guides, ADRs, release notes) -> `opulent:scribe` agent (Opus); trivial doc tweaks stay with `opulent:mechanic`.
- Reading/searching/exploration -> `opulent:scout` agent (Haiku) for anything beyond a single known file. Use it instead of the built-in Explore agent. Scout LOCATES only — never ask it to analyze, judge, or diagnose; interpretation stays with you or an Opus lane.

""" + LADDER_PARA + """

Tier by task fit, not cost: judgment and complexity -> Opus lanes; bounded mechanical execution and
verification -> Sonnet lanes; locating and reading -> Haiku scout. When a task straddles tiers, split
it — scout finds the code, the architect or coder interprets it.

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
templates like .env.example excepted), the built-in Explore agent, catch-all agents
(general-purpose, claude), and this session's routing log itself. Subagent calls are allowed
and not logged: the record covers the main loop only. A plugin's SOURCE repo is ordinary code:
edit it directly. Scratch writes under the system temp dir and ~/.claude/{plans,projects,todos}
are allowed and not logged.

Delegation bridge: instructions do not cross the agent boundary on their own. When delegated work
runs under a lens or contract (a refactoring contract, a debugging oath, a review lens), paste the
contract text verbatim into the agent brief. The same applies to skills from other plugins: when a
skill's steps instruct you to edit files, run tests, or spawn a general-purpose agent directly,
translate each step into a brief for the matching opulent lane, carrying the skill's contract text
(TDD discipline, review checklist, and so on) verbatim — the skill's process survives; only the
executor changes.

Escalation: if a problem exceeds your reach after honest attempts, say so plainly and recommend
the user take it to a stronger model in a dedicated session - do not burn the budget flailing."""

# Eco mode (OPULENT_ECO) swaps the implementation lane for the ladder's high
# rung — an ordinary rung anyone can spawn, which eco simply caps the ladder at
# — and the ladder paragraph for the capped version of itself. Two
# substitutions rather than a second copy of the policy — two copies of this
# text would drift, and only one of them would be the one anyone reads.
CODER_LINE = ("- Complex implementation -> `opulent:coder` agent (Opus, effort xhigh) — "
              "the ladder's default rung, not its only one; pick from the ladder below. "
              "Give it a full spec: files, approach, constraints.")
ECO_CODER_LINE = ("- Complex implementation -> `opulent:coder-high` agent (Opus, effort high "
                  "— eco cap; the ladder is capped here and `opulent:coder-lite` stays open). "
                  "Give it a full spec: files, approach, constraints.")
ECO_LADDER_PARA = (
    "Eco mode caps the coder ladder: `opulent:coder` and `opulent:coder-max` are denied with a\n"
    "redirect to `opulent:coder-high` (high). The cheaper rungs stay available — voluntarily\n"
    "spending less is never a routing violation, and it is often the more accurate call: a rung\n"
    "above the work returns worse code, not safer code, because the effort it cannot spend on\n"
    "the problem it spends on structure the problem never needed. So still drop to\n"
    "`opulent:coder-lite` (medium) when the spec names every file the change touches, an existing\n"
    "test or typecheck would catch a wrong answer, and no named hazard — concurrency, auth or\n"
    "crypto, a data migration, money, a public contract — is in scope.")
ECO_NOTE = ("\n\nEco mode is on for this session (OPULENT_ECO): implementation is capped at the "
            "`opulent:coder-high` rung, and the routing hook denies `opulent:coder` and "
            "`opulent:coder-max` with a redirect to it. Every other lane is unchanged.")

# The Codex dial (OPULENT_CODEX) swaps the same two pieces eco does, one rung
# wider and one vendor over: the implementation lane becomes a command rather
# than an agent, and the ladder paragraph becomes the brief-writing rules that
# replace rung selection. Rung selection is exactly what stops mattering here —
# effort is codex's own pin, and the choice the architect still owns is how
# much context the brief carries.
CODEX_CODER_LINE = (
    "- Complex implementation -> `opulent-codex sol` (OpenAI Codex, GPT-5.6, effort max), "
    "backgrounded. Write a self-contained brief first; codex shares none of this conversation.")
CODEX_LADDER_PARA = """The coder ladder is closed for this session: `opulent:coder` and its three other rungs
are denied with a redirect here. Implementation is judged by a model that shares neither this
vendor nor this conversation, which is the entire reason the dial exists — not cost, and not
speed.

Two steps, every time, and the first is the one that decides whether the second is worth
anything. Write a self-contained brief to your scratchpad: the absolute working directory, the
goal, the constraints, the acceptance checks, and any contract or lens text pasted verbatim.
Codex cannot ask you a follow-up question and cannot see what you have read, so a brief with a
hole in it produces a run you cannot verify. Then background the dispatch and relay what it
prints:

    opulent-codex sol <absolute dir> <brief path>

It blocks, so `run_in_background` is not optional — the harness re-invokes you when it exits.
Add `--sandbox read-only` for a look-don't-touch run, `--network` only if the work genuinely
needs it, `--timeout SECS` to bound it. Never assemble a `codex` command yourself: the model,
effort and sandbox pins live in that script, and a hand-built invocation is one nobody
configured and nothing logged.

Two lanes sit beside it, and neither is switched on by the dial — you send work there
deliberately. `opulent-codex terra` is the cheap tier, worth it for bounded batch work where
what you want is provenance rather than judgment. `opulent-codex review <dir> [--range R]`
puts codex on a diff read-only as a second witness, builds its own brief, and checks every
file:line it cites against the tree before you read it; that one is available whether or not
the dial is thrown.

The brief is the whole job now. A rung was a choice about how hard to think; a brief is a
choice about what the other model gets to know, and it is the only one of the two you can get
wrong in a way no retry fixes."""
CODEX_NOTE = ("\n\nThe Codex lane is on for this session (OPULENT_CODEX): implementation goes to "
              "`opulent-codex sol` and the routing hook denies all four coder rungs with a "
              "redirect there. Every other lane — mechanic, test-runner, ui-checker, scribe, "
              "scout — is unchanged and still Claude: a brief costs more than the work for "
              "bounded mechanical tasks, and a second vendor buys nothing when running a test "
              "suite or locating a file.")


# Spelled out rather than imported: hooks are standalone scripts, invoked by
# path, with no package to import a sibling from. Kept identical to
# route-models.py's `dial()` on purpose — two readers of one dial that
# disagreed about what "set" means would be worse than either rule alone.
_OFF_VALUES = {"", "0", "false", "no", "off"}


def dial(name):
    """True when the named session dial is set to something meaning yes."""
    return os.environ.get(name, "").strip().lower() not in _OFF_VALUES


# What the policy says when enforcement is switched off. The paragraph naming
# what "is still denied" is false in every particular in that session, and the
# hook that would otherwise contradict it logs nothing either — OPULENT_OFF
# returns before any telemetry is written. So the session ran on a policy
# nothing could correct.
OFF_NOTE = ("\n\nEnforcement is OFF for this session (OPULENT_OFF): the "
            "PreToolUse hook allows everything and records nothing. The "
            "delegation above is still how this project prefers to work, but "
            "nothing is denying anything, and no routing log is being written.")


def _policy():
    """The routing policy, with the implementation lane swapped for the
    ladder's high rung and the ladder capped there when the session asked for
    it, and the enforcement paragraph corrected when enforcement is not
    actually running."""
    text = CONTEXT
    # Codex first, and exclusive of eco: eco caps the ladder at one of its own
    # rungs, and with implementation leaving for another vendor there is no
    # ladder left to cap. A session with both dials set that applied both would
    # advertise a redirect to `opulent:coder-high` in the same breath as
    # denying it.
    if dial("OPULENT_CODEX"):
        text = (text.replace(CODER_LINE, CODEX_CODER_LINE)
                    .replace(LADDER_PARA, CODEX_LADDER_PARA) + CODEX_NOTE)
        if dial("OPULENT_ECO"):
            text += (" Eco mode is also set and has nothing to do this session — "
                     "it caps a ladder that is closed.")
    elif dial("OPULENT_ECO"):
        text = (text.replace(CODER_LINE, ECO_CODER_LINE)
                    .replace(LADDER_PARA, ECO_LADDER_PARA) + ECO_NOTE)
    if dial("OPULENT_OFF"):
        text += OFF_NOTE
    return text


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
    # field too, so writing a file named `deny` or `eco` used to fabricate a
    # denial and an eco redirect that never happened — inflating exactly the
    # number the separate `probe` and `eco` events were introduced to keep
    # honest.
    events = []
    for line in lines:
        try:
            events.append(json.loads(line).get("event"))
        except Exception:
            continue        # a torn or hand-edited line is not an event
    # Delegations, denials, edits and test runs are always reported — the
    # commonest post-0.9.0 session is edits and tests with no denial at all,
    # and a line that omitted them reported that session as silence. Probes,
    # eco redirects, unparsed commands and removals are reported only when
    # they happened: the first two exist to stay OUT of the denial count, and
    # a row of permanent zeroes would just be noise in the line people read.
    always = [("delegations", "delegate"), ("denials", "deny"),
              ("edits", "edit"), ("test runs", "test")]
    when_seen = [("probes", "probe"), ("eco redirects", "eco"),
                 ("codex redirects", "codex"),
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
    if dial("OPULENT_OFF"):
        # OFF_NOTE says no routing log is being written; printing activity
        # counts (or the no-activity line) directly beneath it would
        # contradict it on the same screen.
        return _policy()
    try:
        return _policy() + _recent_activity()
    except Exception:
        # _policy() is string substitution over constants and cannot raise;
        # only the telemetry read can land here, and the policy survives it.
        return _policy()


print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": _context()}}))
