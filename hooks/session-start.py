#!/usr/bin/env python3
"""SessionStart hook: inject the routing policy as session context so the
main model delegates proactively instead of bouncing off PreToolUse denials.
Also surfaces recent routing telemetry so enforcement is visible, not
invisible — invisible enforcement is unloved enforcement."""
import json
import os

CONTEXT = """# Model routing policy (opulent plugin)

The main conversation is the architect/orchestrator only. Delegate execution:

- Complex implementation -> `opulent:coder` agent (Opus). Give it a full spec: files, approach, constraints.
- Routine/mechanical edits -> `opulent:mechanic` agent (Sonnet). Give exact instructions.
- Tests, builds, linters, typechecks -> `opulent:test-runner` agent (Sonnet). Delegate anything beyond a quick one-off check.
- Visual/UI verification (screenshots, rendered pages, console errors) -> `opulent:ui-checker` agent (Sonnet).
- Documentation beyond a one-line fix (READMEs, guides, ADRs, release notes) -> `opulent:scribe` agent (Opus); trivial doc tweaks stay with `opulent:mechanic`.
- Reading/searching/exploration -> `opulent:scout` agent (Haiku) for anything beyond a single known file. Use it instead of the built-in Explore agent. Scout LOCATES only — never ask it to analyze, judge, or diagnose; interpretation stays with you or an Opus lane.

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
appended to the log, so what the main loop touched stays visible. Four things are still denied —
the control plane (settings, hooks, agent and command definitions, the installed plugin tree
under ~/.claude, and any .env), the built-in Explore agent, and catch-all agents
(general-purpose, claude). A plugin's SOURCE repo is ordinary code: edit it directly. Scratch
writes under the system temp dir and ~/.claude/{plans,projects,todos} are allowed and not logged.

Delegation bridge: instructions do not cross the agent boundary on their own. When delegated work
runs under a lens or contract (a refactoring contract, a debugging oath, a review lens), paste the
contract text verbatim into the agent brief. The same applies to skills from other plugins: when a
skill's steps instruct you to edit files, run tests, or spawn a general-purpose agent directly,
translate each step into a brief for the matching opulent lane, carrying the skill's contract text
(TDD discipline, review checklist, and so on) verbatim — the skill's process survives; only the
executor changes.

Escalation: if a problem exceeds your reach after honest attempts, say so plainly and recommend
the user take it to a stronger model in a dedicated session - do not burn the budget flailing."""

# Eco mode (OPULENT_ECO) swaps the implementation lane for its one-rung-down
# twin. A substitution rather than a second copy of the policy — two copies of
# this text would drift, and only one of them would be the one anyone reads.
CODER_LINE = ("- Complex implementation -> `opulent:coder` agent (Opus). "
              "Give it a full spec: files, approach, constraints.")
ECO_CODER_LINE = ("- Complex implementation -> `opulent:coder-eco` agent (Opus, effort xhigh "
                  "— eco mode). Give it a full spec: files, approach, constraints.")
ECO_NOTE = ("\n\nEco mode is on for this session (OPULENT_ECO): implementation runs on the "
            "`opulent:coder-eco` twin, and the routing hook denies `opulent:coder` with a "
            "redirect to it. Every other lane is unchanged.")


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
    """The routing policy, with the implementation lane swapped for its eco
    twin when the session asked for one, and the enforcement paragraph
    corrected when enforcement is not actually running."""
    text = CONTEXT
    if dial("OPULENT_ECO"):
        text = text.replace(CODER_LINE, ECO_CODER_LINE) + ECO_NOTE
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
        return ""
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
    # Delegations and denials are always reported, so a quiet session still
    # says so out loud. Probes and eco redirects are reported only when they
    # happened: both exist to stay OUT of the denial count, and a pair of
    # permanent zeroes would just be noise in the line people actually read.
    always = [("delegations", "delegate"), ("denials", "deny")]
    when_seen = [("probes", "probe"), ("eco redirects", "eco")]
    counts = [(name, events.count(key)) for name, key in always]
    counts += [(name, n) for name, n in
               ((name, events.count(key)) for name, key in when_seen) if n]
    if not any(n for _, n in counts):
        return ""
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
        return _policy() + _recent_activity()
    except Exception:
        try:
            return _policy()
        except Exception:
            return ""


print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": _context()}}))
