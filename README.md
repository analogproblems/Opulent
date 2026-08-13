# Opulent

[![CI](https://github.com/analogproblems/Opulent/actions/workflows/ci.yml/badge.svg)](https://github.com/analogproblems/Opulent/actions/workflows/ci.yml)

A Claude Code plugin that keeps your best model in the seat you talk to, and
pushes the grunt work — editing files, running tests, searching the codebase —
into separate throwaway agent sessions. Your main conversation stays clean.

MIT licensed; house rules in [CONTRIBUTING.md](CONTRIBUTING.md), chiefly the
honesty policy.

## Requirements

**Python 3** on `PATH`, as `python3` or `python`. Both hooks are Python
scripts; without an interpreter they fail on every guarded tool call and at
every session start. Note that the fail-open rule below cannot cover this
case — it is implemented *inside* the interpreter that would not have
started. Preinstalled on macOS and most Linux distributions; on Windows,
install from python.org rather than relying on the Store alias.

Everything else is stock Claude Code — no packages, no daemon, no network.

## Install

Add the marketplace once, then install:

```
/plugin marketplace add analogproblems/Opulent   # or a local /path/to/Opulent
/plugin install opulent@opulent
```

Or try it without installing:

```
claude --plugin-dir /path/to/Opulent
```

After editing commands, agents, hooks, or manifests, run `/reload-plugins` or
restart.

Two timing gotchas worth knowing up front:

- **Enable/disable takes effect at session start, not mid-session.** Enabling
  a plugin inside a running session registers neither its hooks nor its
  agents — the session keeps behaving as if the plugin were absent, with no
  error to tell you so. Start a new session after toggling.
- **Updating is two steps.** `claude plugin marketplace update opulent`
  refreshes only the marketplace cache; the installed copy moves when you
  follow it with `claude plugin update opulent@opulent` (then restart).

### Setting the dials

`OPULENT_OFF`, `OPULENT_ECO` and `OPULENT_LOG` are read from the environment
of the `claude` process itself, which rules out the two places people try
first. Exporting one inside a running session does nothing — the hook is
spawned by the harness and never sees that shell. Putting one in
`~/.claude/settings.json` works, but that file is the control plane, so the
main loop is denied the edit and has to delegate it (which is the design, and
worth knowing before it surprises you).

Per launch:

```bash
OPULENT_ECO=1 claude
```

Persistently, in the `env` block of `~/.claude/settings.json` — hand this to
`opulent:mechanic`, or edit it yourself outside a session:

```json
{ "env": { "OPULENT_ECO": "1" } }
```

`0`, `false`, `no`, `off` and empty all count as unset, so `OPULENT_OFF=0`
means what it looks like.

---

# opulent — deterministic model routing

**The problem.** In a long session, the conversation you're actually having
fills up with things you never needed to read: whole file bodies, test output,
search results. The model you're talking to spends its context on clutter.

**What it does.** Your best coding model — **Opus 5** by default — stays in the
architect seat: the one you talk to, the one that designs, reviews, and
orchestrates.
Everything else happens in a delegated agent with its own disposable context.
The bulk lands there and is thrown away, so the architect's window stays lean
deep into a long session. That's the claim: **context hygiene**.

The secondary bet — that routing execution to cheaper lanes also slows your
quota drain — is plausible but *yours to verify*. The routing log
(`~/.claude/opulent-log.jsonl`) records every delegation and denial, and
`/usage` shows the spend, so you can check what routing actually did rather
than take our word for it.

**How it's enforced.** Not by instructions the model can talk itself out of: a
hook denies every ordinary path to writing code, running tests, or delegating
to catch-all agents from the main loop. See
[What enforcement is — and isn't](#what-enforcement-is--and-isnt) for the
honest boundary.

Top-shelf reasoning models (Fable) sit **outside** this system by default.
Their usage draws disproportionately on the shared weekly pool, so reserve
them — manually, in their own session — for the rare problem the architect
genuinely can't crack.

**Or seat one as the architect.** An official optional mode, for operators
with Fable access: the old rationale assumed Fable would do the *work*, and
under opulent it only leads. Implementation, tests, docs and exploration all
execute in pinned lanes whose bulk is thrown away, so the architect seat draws
few tokens by construction — the model whose usage you most want to conserve
is precisely the one this architecture protects. Per token the draw is still
disproportionate, so the mode stands entirely on the seat staying lean, and
that is measurable rather than assumable: a fresh Fable session states which
model it is, so the transcript records which brain led, and
`~/.claude/opulent-log.jsonl` with `/usage` says whether the seat stayed lean.
A week of Fable-led operation sits behind this. Opus stays the recommended
default.

## Routing table

| Work | Agent | Model |
|---|---|---|
| Architecture, review, conversation, orchestration | main loop | Opus 5 (recommended session model); Fable optionally, same seat |
| Problems Opus can't crack | you, manually | Fable, in its own session — outside this plugin |
| Complex implementation | `opulent:coder` | Opus, effort max |
| Complex implementation, eco mode (`OPULENT_ECO=1`) | `opulent:coder-eco` | Opus, effort xhigh |
| Routine edits, boilerplate | `opulent:mechanic` | Sonnet |
| Tests, builds, linters, typechecks | `opulent:test-runner` | Sonnet (read-only tools) |
| UI verification, screenshots, console errors | `opulent:ui-checker` | Sonnet + browser tools |
| Documentation (READMEs, ADRs, guides, release notes) | `opulent:scribe` | Opus, effort xhigh |
| Locating code and structure — never analysis or judgment | `opulent:scout` | Haiku |

In a Fable-led session the escalation row is moot: the model you would
escalate to already holds the seat.

The tiering principle: **task fit, not cost.** Judgment and complexity go to
Opus lanes (effort max; xhigh for scribe); bounded mechanical execution and
verification go to Sonnet (effort xhigh); locating goes to Haiku, which is
never asked to interpret what it finds. Effort is pinned per lane, not
inherited from the session — deterministic like everything else here.

**Eco mode.** `OPULENT_ECO=1` runs complex implementation
one effort rung down for that session: the session-start policy names
`opulent:coder-eco` as the implementation lane, and the routing hook denies
`opulent:coder` with a redirect to the twin — same Opus model, same charter,
`effort: xhigh` instead of `max`. The cut is coder-only by design: the routing
log shows the rare judgment lanes barely firing, so eco-ing them would save
nothing, while coder is the high-volume Opus spend. Unset, nothing changes —
and the twin stays spawnable either way, since voluntarily spending less is
never a routing violation. `0`, `false`, `no`, `off` and empty all read as
off, for both dials — until 0.11.2 any non-empty value counted as set, which
made `OPULENT_OFF=0` a silent way to disable every denial for a session and
`OPULENT_ECO=0` a way to turn eco on. A `tests/ci_checks.py` assertion holds
[agents/coder-eco.md](agents/coder-eco.md) byte-identical to
[agents/coder.md](agents/coder.md) outside `name`, `description` and `effort`,
so the duplication cannot drift silently.

## How it works

Three built-in Claude Code mechanisms, nothing else:

1. **Agents** ([agents/](agents/)) pin `model:` and `effort:` in frontmatter — deterministic once delegation happens.
2. **A PreToolUse hook** ([hooks/route-models.py](hooks/route-models.py)) guards the control plane and records the rest. Hook payloads include an `agent_id` field only when the call originates inside a subagent, so the hook can tell main-loop work from delegated work. Main-loop edits and test runs are **allowed and logged**; only the control plane is refused. Calls to the built-in `Explore` agent are redirected to `opulent:scout` (plugins can't shadow built-in agents, so the hook redirects instead).
3. **A SessionStart hook** ([hooks/session-start.py](hooks/session-start.py)) injects the routing policy as context, so the model delegates proactively instead of bouncing off denials.

Design details:

- **Fail-open.** Any payload the hook can't parse is allowed. A Claude Code update can never brick your sessions.
- **Command-position matching.** Test tools are only recorded when actually invoked (`pytest -x`, `CI=1 pytest`, `npx jest`, `./gradlew test`, `python -m pytest`) — not when merely mentioned (`echo pytest`, `grep -r pytest .`, `git commit -m 'fix eslint config'`).
- **Bash writes seen too.** Beyond the Edit/Write tools, the hook tokenizes Bash commands (via `shlex`, so quoted strings like `git commit -m "a > b"` never false-positive) and sees file redirects (`>`, `>>`, `>|`, `&>`), `tee`, `cp`/`mv`/`touch`, `patch`, `git apply`, and `sed`/`perl` in-place edits. It reads *every* target in a command, not the first, so a compound that writes `/dev/null` and then `settings.json` is judged on the half that matters.
- **Catch-all delegation denied.** Delegating to `general-purpose` or `claude` would satisfy "delegation" while defeating "routing" (full tools, session model) — the hook denies those in the main loop and points at the lanes. Purpose-defined agents from other plugins are untouched.
- **The control plane, and only it.** Refused from the main loop: anything under a `.claude` directory's `hooks/`, `agents/`, `commands/` or `plugins/`, a `settings*.json` beside them, and any `.env*` — the user's and the project's alike, because both govern the session that is running. A plugin's **source repo** is ordinary code and is freely editable: it changes nothing until it is installed, and treating it as sacred is what made plugin development expensive. Paths are normalized per-platform, so this holds on Windows and macOS, not just Linux.
- **Scratch is quiet.** The system temp dir and `~/.claude/{plans,projects,todos}` are writable and *not* logged — an audit trail of temp files buries the project edits it exists to surface.
- **Escape hatch.** `OPULENT_OFF=1` in the environment disables enforcement for that session, so tuning doesn't require uninstalling. The session-start policy says so too, rather than reciting rules nothing is enforcing.
- **Telemetry.** Main-loop edits (`"event": "edit"`), test runs (`"test"`), delegations (`"delegate"`) and denials (`"deny"`) each append a line to `~/.claude/opulent-log.jsonl` (override with `OPULENT_LOG`), and each session with logged activity behind it opens with a one-line summary (a fresh install has none yet, so the line is simply absent). The record is the point: what the main loop touched stays visible whether or not it was refused. The doctor's own canary write is still denied, but logged as `"event": "probe"` so health checks don't skew denial telemetry; the eco redirect is logged as `"event": "eco"` for the same reason.

## What enforcement is — and isn't

Honesty section. As of 0.9.0 the hook denies far less than it used to, and
that is deliberate. It refuses three things from the main loop: the control
plane (settings, hooks, agent and command definitions, the installed plugin
tree, `.env*`), the built-in `Explore` agent, and the
`general-purpose`/`claude` catch-alls. Everything else — edits, Bash writes,
test runs — is allowed and written to the log.

**Why the retreat.** Until 0.9.0 every main-loop write was denied to force
delegation. Measured against a real session, that cost a subagent round trip
per one-line comment and per status stamp, and the protection was mostly
redundant: the thing worth having was never the refusal, it was knowing what
the main loop touched, and that is a log line. Routing is a judgment the
model can make; the control plane is the one place where a silent change
would remove the ability to notice later, so that is the one place still
refused.

It is **not a security boundary**. A model determined to edit the control
plane from the main loop can still do it (an inline interpreter one-liner, a
script it executes, an exotic utility we didn't pattern-match). We
deliberately stop short of blocking those, because closing every avenue means
blocking Bash itself. Treat the hook as a seatbelt with an audit trail: it
makes the recorded path the path of least resistance and makes writes,
bypasses and denials *visible* — in the transcript and in the routing log —
rather than making bypass impossible.

Two further honest limits. The main-loop/subagent distinction rests on the
`agent_id` field in hook payloads — an observed harness behavior, not a
documented contract, and the hook fails open if it ever breaks. Day to day the
drift alarm is the doctor's canary: a hook that stopped telling main loop from
subagent reports as not enforcing, in your own session. The live e2e that
proves the same thing end to end runs by manual dispatch from the private
companion's CI, fired when the harness or the CLI updates — the event that
would actually break this, rather than a date on a calendar. And lane *choice*
among the opulent agents (coder vs mechanic, scribe vs scout) remains
policy-steered, not hook-enforced — what the hook guarantees is that work
leaves the main loop and lands in a purpose-defined, model-pinned agent.

## Verify it's working

Run **`/opulent:doctor`**. It probes its own installation with real tool
calls: installed version, agents registered, policy injected, enforcement
liveness (a canary write that should bounce), and the telemetry log — then
gives a one-line verdict (LIVE / OFF / PARTIAL / DEAD) with remediation.
"Installed" and "enforcing" are different states, and the difference is
silent; the doctor exists to make it loud.

Run it in a session *started after* the plugin was enabled — a mid-session
enable registers nothing (see the install gotchas), so every probe would
report dead when the fix is simply a fresh session.

Manual spot-checks, if you prefer: ask Claude to edit a file directly — the
tool call should be denied with a message pointing at `opulent:coder` /
`opulent:mechanic`. To confirm an agent's pinned model from the outside,
grep `"model"` in its transcript under
`~/.claude/projects/<project>/<session-id>/subagents/agent-*.jsonl`.

## When you hit usage limits

Usage-limit exhaustion hard-blocks the affected model — there is no automatic
fallback, and no hook fires that tooling could react to.

- **Model-specific cap** (e.g. Opus, the architect): switch the session with
  `/model sonnet` and keep working. The agents keep their pinned models and
  enforcement continues unchanged — the architecture is main-model-agnostic
  by design, so a Sonnet-led session still routes exactly the same way — as
  does a Fable-led one; the agnosticism runs upward as well as down.
- **Shared session/weekly cap**: everything waits for the reset shown in the
  limit message, subagents included. `/usage` shows what's draining the pool,
  and `~/.claude/opulent-log.jsonl` records what routing actually did —
  measure before trusting any savings claim, including ours.

---

## Companion plugin: lens-master (private)

lens-master is a separately-shipped **private** plugin — the steering layer
(which perspective, when) to opulent's enforcement layer (which model, where).
It is not served by this marketplace and is not required: opulent behaves
identically without it.

The two ship from separate repos and neither imports the other, but four
couplings are real, and each one breaks quietly if either side moves.

- **The doctor's probe string.** `/opulent:doctor` confirms lens-master's
  Secret Keeper hook is live by running exactly `git push --dry-run`, and
  expects the danger log to record that command as verdict `probe` rather than
  `deny` — so repeated health checks do not inflate the near-miss record the
  log exists to build. The probe is conditional: with lens-master absent the
  doctor skips it and says so. A skipped probe is never an error and never a
  failed verdict. Recognition on the far side is exact, so anything beyond the
  bare command still logs as `deny`.
- **The routing log.** lens-master's session steering reads opulent's routing
  log at `~/.claude/opulent-log.jsonl` (`OPULENT_LOG` to override) and reports
  how often its own lanes were actually delegated to. That path is a runtime
  contract rather than an implementation detail: change it and the companion
  goes blind. It is a soft read on their side — an absent log is silence, not
  an error — which is exactly why a move would be silent here too.
- **The implementation lanes, reciprocally.** Any new agent lane in this repo
  with unrestricted tools — or a tools allowlist naming `Edit`/`Write` — needs
  a matching entry in lens-master's delegation-bridge `IMPL_LANES` in the same
  release window. A lane it does not know is a lane whose briefs skip the
  contract check silently, which reads as green rather than as a gap. Its CI
  drift-guards that set against this repo's public main, so the failure surfaces
  over there — the wrong place to learn it, and the reason the rule is written
  down on this side too.
- **The live e2e tier runs from over there.** `tests/validate_plugins.py` and
  `tests/e2e_smoke.py` live in this repo, beside what they test, but nothing in
  this repo's CI runs them: they need the `claude` CLI — on `PATH` for
  `validate_plugins.py`, and additionally *authenticated* for `e2e_smoke.py`,
  which opens real sessions — and no
  self-hosted runner serves a public repository. lens-master's CI clones our
  main and runs both, by manual dispatch only — the honest trigger is a CLI or
  harness update on that machine, not a calendar. Renaming or moving either
  script is a change to a workflow in the other repo, and this side's CI stays
  green while it breaks.

---

## Development

```
python3 tests/hook_selftest.py               # routing hook payload cases
python3 tests/ci_checks.py                   # marketplace manifests + session-start JSON
python3 tests/gate_selftest.py               # the gate finds planted terms, and never prints them
python3 tests/gate_corpus_selftest.py        # ...in every corner of the object database
python3 tests/public_gate.py                 # no private residue in the object database
python3 tests/validate_plugins.py            # claude CLI structure validation (needs claude on PATH)
python3 tests/e2e_smoke.py                   # live sessions (needs an AUTHENTICATED claude CLI)
```

Both self-tests take a path override so they can be pointed at an older copy
and watched to fail — `ROUTE_HOOK_PATH=` for `hook_selftest.py`,
`PUBLIC_GATE_PATH=` for `gate_corpus_selftest.py`. A guard case that has never
failed is a guard case nobody has checked, which is how 71 of 120 hook cases
came to be satisfied by a hook that did nothing at all.

`ci_checks.py` and `validate_plugins.py` both derive their member roster from
`marketplace.json` — a member sourced from another repo is skipped with a
notice rather than failing, since its manifest and CI live in its own tree.

## Customize

- Change a lane's model or effort: edit the frontmatter in [agents/](agents/).
- Add/remove recorded test runners: edit `TEST_RE` in [hooks/route-models.py](hooks/route-models.py).
- Change what counts as the control plane: `_CONTROL_SUBDIRS` / `_SETTINGS_RE`; change what stays out of the log: `_SCRATCH_DIRS`, in the same file.
- Disable opulent for a session: `OPULENT_OFF=1`. Run implementation one effort rung down: `OPULENT_ECO=1`. Redirect telemetry: `OPULENT_LOG=<path>`.
