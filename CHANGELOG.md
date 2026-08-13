# Changelog

This repo serves one plugin. Entries dated before 2026-08-09 were released
from the shared repo opulent and lens-master used to co-inhabit, so the older
ones note the companion release they shipped beside; lens-master's own notes
left with it. That shared history, and every tag before `opulent--v0.11.0`,
lives on in a private archive repo — public history here starts at 0.11.0, and
the earlier versions are not pinnable from this remote.

Versions are pinnable via git tags in the form `{plugin}--v{version}`
(e.g. `opulent--v0.11.0`).

## opulent 0.11.2 — 2026-08-13

**What the review found.** Five fresh-context lenses over the public state
found 23 defects that reproduce, and the sharpest of them were in the two
things this plugin sells: the record, and the gate.

**The gate scanned the wrong corpus.** `tests/public_gate.py` read `git log
--all -p` while its docstring claimed the object database, and those are not
the same set: `log -p` renders reachable-history *diffs*. It could not see
merge-commit conflict resolutions (`-p` prints no patch for a merge),
unreachable and reflog-held objects, binary blobs, annotated tag messages,
committer identity, or refs outside heads/remotes. This was not theoretical —
the gate certified this very checkout clean while all ten stored terms sat in
its object database, in objects `log` cannot reach. It now enumerates every
object via `cat-file --batch-all-objects`, trees included, because a filename
is residue too. `censor()` was locating matches in a `.lower()` copy and
slicing the original; since `str.lower()` is not length-preserving, a
character like U+0130 ahead of a match slid the mask right until the term
printed **in full**, directly above the line promising it never does — matches
are now found in the string being edited. Terms also split on newlines (a
multi-line CI secret used to match nothing and report clean) and compare in
both Unicode normal forms (an accented name spelled the other way used to
miss). New `tests/gate_corpus_selftest.py` plants residue in each blind spot:
9/9 against this gate, 2/9 against the old one.

**The write guard had holes that cost the audit line as well as the denial.**
`git -C <dir> apply` bypassed the patch guard entirely — the subcommand search
took `-C`'s operand for the subcommand — with no denial *and no log entry*.
`git apply --directory=`, `patch -d` and `patch -o` wrote where the headers
never pointed, and the record named the innocent path. `tee` and `touch`
judged only their first operand; `cp -t`/`mv -t` judged the source, since `-t`
puts the destination first. A prefix carrying a flag (`sudo -u root cp`)
blanked detection of the command behind it. `sed --in-place` was unrecognised.
A `./`-prefixed header under `-p1` lost one component too many. A lone
positional suppressed the `< patch` fallback. The control-plane check was
case-sensitive on the two platforms the README claims it holds for. All
closed, all with cases that fail against the previous hook.

**Dials that lied.** `OPULENT_OFF=0`, `=false`, `=no` and `=off` each disabled
every denial for the session — truthiness on a string — and `OPULENT_ECO=0`
turned eco on. Both now read `0/false/no/off/empty` as off. `OPULENT_OFF`
sessions also got the full policy injected, announcing enforcement that was
not running and logging nothing that could contradict it; the policy now says
when enforcement is off. The activity summary counted quoted substrings
rather than parsing its own JSON, so writing a file named `deny` or `eco`
fabricated a denial and an eco redirect — precisely the number the separate
`probe` and `eco` events exist to keep honest. And a single non-UTF-8 byte in
the log raised through `except OSError` and killed the *entire* policy
injection, silently, while the routing hook kept enforcing against a policy
the model never received.

**Tests that a no-op could pass.** Mutation testing showed a two-line hook
that does nothing passing 71 of 120 cases. `hookEventName` — the discriminator
telling the consumer which event a decision belongs to — was asserted nowhere,
so corrupting it left all 120 green; it is now checked on every case that
produces output. `e2e_smoke.py`'s denial check asserted on the model's
narration using three strings that also appear in the injected policy, so a
model that never attempted the write passed while the hook sat idle; it now
reads the `deny` event out of the routing log, which only the hook can write.
The suite gained 24 cases and both self-tests take a path override, so they
can be pointed at an older copy and watched to fail.

**CI now scans the commit under review, not the merge invented to test it.**
The stricter gate found its first live target immediately: on a
`pull_request` event `actions/checkout` defaults to `refs/pull/N/merge`, a
synthetic commit GitHub authors with the PR author's own account, so it
carries an identity the branch itself does not. Reading committer as well as
author — new in this release — that object fails a branch which is clean.
The merge is a CI artifact, never pushed and never reachable from main, so
the checkout now pins the head SHA and the gate answers the question with a
stable answer. Also bumps `actions/checkout` to v5, clearing the Node 20
deprecation warning.

**Descriptions that had been false since 0.9.0.** Four agent files still told
users "the main loop cannot edit source files" / "cannot run these directly",
which 0.9.0 stopped being true and the README already contradicted. They now
state the routing default. The injected policy said "Never run these
directly" one screen above "make that call yourself"; the first is gone. The
README gained a Requirements section (Python 3 was an undeclared runtime
dependency, and the fail-open rule cannot cover it — it lives inside the
interpreter that would not have started) and a concrete recipe for setting the
dials, which the previous text described only as "in the environment" —
leaving the three places people actually try, one of which is denied by this
plugin's own control-plane guard.

## opulent 0.11.1 — 2026-08-09

**Metadata refresh.** Version bump only, so installed copies re-fetch the
scrubbed plugin metadata. No behavior change.

## opulent 0.11.0 — 2026-08-09

**Standing alone.** lens-master moves to its own private repo; this repo now
serves the opulent plugin only and is being prepared for a public flip. The
selftest job moves to GitHub-hosted runners (a public repo must not run
fork PRs on a personal machine) and is now the whole of this repo's CI: no
self-hosted runner serves a public repository, so the live e2e tier moves out
to the private companion's CI, which clones this repo's main and runs it by
manual dispatch only. The suites themselves stay here, beside what they test.
A public-hygiene gate scans the full object database for private residue
before any visibility change; terms whose text is itself the leak (names,
identities) arrive out of band via `PUBLIC_GATE_PRIVATE_TERMS` and are
reported by location only, never echoed. The companion contracts with
lens-master — the doctor's conditional Secret Keeper probe, the routing-log
read, the reciprocal IMPL_LANES checklist, and now the e2e tier's new home —
are documented in the README instead of assumed by co-residence. Prior history
lives in the private archive; public history starts here.

## opulent 0.10.0 — 2026-08-06

**Eco mode, coder-only.** Set `OPULENT_ECO=1` and the complex-implementation
lane runs one effort rung down: a new `coder-eco` twin — same Opus model, same
charter, `effort: xhigh` instead of `max`. The narrow cut is deliberate: the
routing log shows the rare judgment lanes barely firing, so eco-ing them would
save nothing, while coder is the high-volume Opus spend. With eco set, the
session-start policy names `opulent:coder-eco` as the implementation lane and
the routing hook denies `opulent:coder` with a redirect; with it unset, nothing
changes — and the eco twin stays spawnable either way, since voluntarily
spending less is not a violation. A ci_checks assertion keeps the twin
byte-identical to coder outside name, description, and effort, so the
duplication cannot drift silently. The redirect is telemetered as its own `eco`
event, so the denial count the doctor reports stays honest.

## opulent 0.9.2 — 2026-08-06

- **A Fable-led main loop is now an official optional mode.** Fable left the
  plugin at 0.4.0 because its draw on the shared weekly pool is
  disproportionate — a rationale that assumed Fable would do the *work*. Under
  opulent it doesn't: implementation, tests, docs and exploration execute in
  pinned lanes whose bulk is thrown away, so the architect seat draws few
  tokens by construction. The model whose usage you most want to conserve is
  precisely the one this architecture protects. A week of Fable-led operation
  with the plugin enabled is the evidence behind the change.
- Docs only — no hook, agent, or lane behavior changed, and Opus stays the
  recommended default. The README now presents both modes and marks the manual
  escalation row moot in a Fable-led session (the model you would escalate to
  already holds the seat); the usage-limits playbook notes that main-model
  agnosticism runs upward as well as down; both plugin descriptions stop naming
  Opus as the only possible architect.
- The saving stays checkable rather than asserted. A fresh Fable session states
  which model it is, so the transcript records which brain led the work — and
  `~/.claude/opulent-log.jsonl` with `/usage` remains the arbiter of whether
  the seat actually stayed lean. Measure before trusting the claim, ours
  included.

## opulent 0.9.1 — 2026-08-05

- **A patch could rewrite the control plane; now it cannot.** 0.9.0 narrowed
  enforcement to the control plane, but `patch` and `git apply` reported the
  sentinels `"(patch)"` / `"(git apply)"` — strings that can never match a
  control-plane path — because the files a patch writes are named *inside* it.
  0.8.6 had covered them only incidentally, by denying every main-loop write, so
  narrowing enforcement silently uncovered them. `git apply evil.patch`, with
  `evil.patch` rewriting `.claude/settings.json`, was allowed. The hook now reads
  the patch and judges its real targets.
- Handled: all four invocation spellings (`git apply f`, `patch -p1 f`,
  `patch -i f`, and `patch -p1 < f` — the stdin redirect, whose `<` is its own
  constant so it can point at a patch without ever reading as a *write* target);
  every patch named in one command, not just the last; `---`/`+++` pairs matched
  as pairs so a removed line beginning `--` cannot pose as a header; `/dev/null`
  on either side resolved to the live side, so creates and deletes are named;
  strip levels `-p0`, `-p1`, clustered `-up1` and `--strip=`; and `diff --git`
  headers, which are the *only* target a pure rename or a mode-only change
  carries — including the space-bearing and C-quoted spellings git emits, each
  of which was a working bypass until it was tested.
- Fails open by contract: a patch file that is missing, unreadable, oversized
  (capped at 2 MiB) or not a patch allows the command, as everything else in
  this hook does. It reads the file directly — no subprocess.
- Tests: 74 → 112 cases, fixtures written as real patch files on disk, since a
  string mock of a patch exercises none of the reading. Telemetry cases pin the
  logged path to the real target (`src/app.py`), not `(patch)` and not the
  unstripped `a/src/app.py`.
- Known gap, recorded rather than hidden: the space-separated strip level
  `patch -p 1 < f` reads `1` as the patch file and fails open.

## opulent 0.9.0 — 2026-08-05

- **The main-loop lockout becomes a record.** Edits, Bash writes and test runs
  from the main loop are now **allowed and logged** instead of denied. The
  lockout existed to force delegation, but measured against a real session it
  charged a subagent round trip for a one-line comment and a status stamp,
  while the thing actually worth having — knowing what the main loop touched —
  was never the refusal. It was a log line. New events: `edit` and `test`.
- **The control plane is the one thing still refused**, and it is now defined
  by what governs the *running session*: anything under a `.claude`
  directory's `hooks/`, `agents/`, `commands/` or `plugins/`, a
  `settings*.json` beside them, and any `.env*` — the user's and the
  project's alike. A plugin's **source repo** is explicitly not the control
  plane: it changes nothing until it is installed, and treating it as sacred
  is what made plugin development expensive.
- **Bash writes are read whole.** The tokenizer now returns every write target
  in a command rather than the first, so a compound that writes `/dev/null`
  and then `settings.json` is judged on the half that matters; `sed`/`perl`
  in-place edits report the files they edit instead of a sentinel, which is
  what lets an in-place edit of a settings file be caught as one.
- **Retired:** `OPULENT_ALLOW`, and the project-management allowlist
  (`CLAUDE.md`, `TASKS.md`, `docs/plans/**`, …) it extended. Both existed to
  carve exceptions out of a blanket denial that no longer exists; ordinary
  files need no exception. Scratch paths (system temp,
  `~/.claude/{plans,projects,todos}`) are kept for a different reason — they
  stay *out of the log*, so temp files do not bury the project edits the
  record exists to surface.
- Unchanged: catch-all agents (`general-purpose`, `claude`) and the built-in
  `Explore` are still denied in the main loop — that was routing quality, not
  the lockout. `OPULENT_OFF=1`, fail-open, and the doctor's `probe`-logged
  canary behave as before. The selftest covers the new contract in 74 cases.

## opulent 0.8.6 — 2026-07-30

- Doctor's canary denial now logs as a `probe` event, not a plain `deny`:
  the doctor deliberately trips the PreToolUse hook every run to confirm
  enforcement is live, and counting that self-check as a denial inflated
  the telemetry it's supposed to make trustworthy. The write is still
  denied — only the log event changes. Session-start's activity summary
  now counts probes separately so they don't read as denials either.

## opulent 0.8.5 — 2026-07-29

- Scribe promoted to Opus: substantive documentation is judgment work —
  deciding what is true and what matters — and was mis-tiered as bounded
  execution. Mechanic stays on Sonnet: when exact instructions determine
  the output, executor intelligence is not the bottleneck.
- Main-loop allowlist for project-management files: CLAUDE.md,
  CLAUDE.local.md, TASKS.md, TODO.md, PLAN.md, docs/plans/**, and
  .claude/plans/** are the architect's own working state — delegating
  their updates was dictation through a middleman. Extensible via
  OPULENT_ALLOW (colon-separated globs). The control plane stays
  delegated by design: .claude/settings*, agent/command/hook definitions,
  and .env* — the layer that constrains the main loop must not be
  casually editable by it, and every touch of it leaves a delegate event
  in the telemetry log.

## opulent 0.8.4 — 2026-07-29

- Delegation bridge now covers skills from other plugins: when a skill's steps
  instruct direct edits, test runs, or a general-purpose agent spawn, the
  architect translates each step into a brief for the matching opulent lane,
  carrying the skill's contract text (TDD discipline, review checklist, and so
  on) verbatim — the skill's process survives; only the executor changes. Born
  from asking how Opulent would coexist with process plugins like Superpowers,
  whose imperative skills otherwise bounce off the PreToolUse hook step by step.

## opulent 0.8.3 — 2026-07-29

- Doctor learns the enable-timing failure mode: plugin enable/disable takes
  effect only at session start — a mid-session enable registers neither hooks
  nor agents, leaving the session silently unrouted. Found by running the
  doctor's probes in exactly such a session (canary write succeeded while a
  session-start-enabled plugin's hooks enforced normally); this also closed
  the "800k tokens, zero telemetry" field mystery — the plugin was enabled
  and disabled within one session, so it was never actually running.

## opulent 0.8.2 — 2026-07-27

- New `/opulent:doctor` command: self-diagnoses the installation with real
  probes — version, agents registered, policy injected, enforcement liveness
  (canary write that should bounce), telemetry log — and gives a one-line
  verdict with remediation. Born from a real incident: a session ran with
  agents visible but enforcement disabled, and nothing said so. "Installed"
  and "enforcing" are different states; the doctor makes the difference loud.

## opulent 0.8.1 — 2026-07-26

- Windows CI caught a v0.8.0 regression the same hour it shipped (the
  de-tautologized fixtures working as intended): POSIX-literal `/tmp` and
  `/dev/null` strings in Bash commands were mangled by Windows `normpath`
  and lost their exemption. They're now checked before normalization, on
  every platform.
- Repo prepared for open-source viewing: LICENSE (MIT), CONTRIBUTING.md
  (the honesty policy, the dev loop, release conventions), CI badge.

## opulent 0.8.0 — 2026-07-26

*(released jointly with lens-master 1.9.0)*

**The self-audit release.** Every change below originates from the system's
inaugural self-audit: two fresh-context Opus agents (an Opposing Counsel and
a Pre-mortem) given the repo and nothing else. Their verified findings:

*Correctness*
- Path exemptions are now platform-safe (`os.path` normalization + the real
  system temp dir) — previously plans/memory/scratch writes were **denied on
  Windows** while the Windows CI passed, because the tests built fixtures
  with the same hardcoded slashes as the code. Fixtures de-tautologized.
- The routing loophole is closed: main-loop delegation to `general-purpose`
  or `claude` (full tools, session model — delegation without routing) is
  now denied. Purpose-defined agents from other plugins are untouched.
- The `~/.claude` exemption no longer contains the enforcer: only
  `plans/`, `projects/`, and `todos/` are writable — not `plugins/`,
  `settings.json`, or `CLAUDE.md`.
- Bash write coverage extends to `cp`/`mv`/`touch`, `patch`, `git apply`,
  and the `>|` / `&>` redirect forms.

*Ergonomics*
- `tsc --version`, `npm run build-docs`, `yarn lint-staged`, and
  `make test-data` no longer cost a delegation round-trip (word-end guards +
  a `--version/--help` exception); `npm run test:unit` still denies.
- `OPULENT_OFF=1` disables enforcement per-session — a dial, not a binary.

*Measurement*
- Every denial and delegation logs one line to `~/.claude/opulent-log.jsonl`
  (`OPULENT_LOG` to override); sessions open with an activity summary.
- Weekly scheduled live e2e run — the `agent_id` contract now has an expiry
  alarm. `claude plugin validate` joins the e2e job.
- README repositioned: context hygiene is the claim; quota savings is the
  hypothesis the log lets you test.

## opulent 0.7.0 — 2026-07-26

*(released jointly with lens-master 1.8.6)*

**The honesty pass.**

- Routing hook now denies the lazy Bash write-paths in the main loop:
  `>`/`>>` redirects (including `2>` and heredoc-into-redirect), `tee`, and
  `sed`/`perl` in-place edits. Detection tokenizes commands with `shlex`, so
  quoted strings (`git commit -m "a > b"`) cannot false-positive. Targets
  under `/tmp/`, `/dev/`, and `~/.claude/` stay exempt; unparseable commands
  fail open. Self-test grows 25 → 40 cases.
- README replaces the "physically cannot write code" overclaim with a
  dedicated *What enforcement is — and isn't* section: a seatbelt with an
  audit trail, not a security boundary.

## opulent 0.6.3 — 2026-07-26

*(released jointly with lens-master 1.8.5)*

- Hook commands gain a `python3 || python` fallback. Found by the first live
  e2e CI run: on Windows, `python3` doesn't exist, so every hook silently
  failed and enforcement fell through to ordinary permissions.

*(Between these releases: CI landed — hook self-tests on every push, plus a
gated Claude-driven live e2e tier, both pinned to a self-hosted runner via
the `opulent-ci` label.)*

## opulent 0.6.2 — 2026-07-26

- Haiku 4.5 docs audit. Result: design already aligned; no behavioral
  seatbelt shipped (no documented evidence to ground one). Scout's
  frontmatter gains a guard comment: Haiku 4.5 rejects the `effort`
  parameter, so the one lane without an effort pin must stay that way.

## opulent 0.6.1 — 2026-07-26

*(released jointly with lens-master 1.8.4)*

**Model-calibration seatbelts**, both grounded in Anthropic's documented
behavioral shifts:

- Opus 5 (architect): assumptions-and-scope paragraph in the session policy —
  silent assumptions must be stated in one line as they're acted on; scope
  stays as asked; completion claims require verification.
- Sonnet 5 (test-runner): coverage-first reporting — Sonnet 5 obeys severity
  filters too faithfully, so the lane now labels confidence and severity and
  never self-filters.

## opulent 0.6.0 — 2026-07-26

*(released jointly with lens-master 1.8.3)*

- Project renamed **Fabeulous → Opulent** (Fable exited the system at 0.4.0,
  so the name stopped being true; Opulent names the doctrine — leaning on
  Opus 5's abundance). Plugin name, marketplace, agent namespace
  (`opulent:*`), hook messages, docs, and GitHub repo all renamed; old URLs
  redirect.

## opulent 0.5.2 — 2026-07-26

*(released jointly with lens-master 1.8.2)*

- All Sonnet 5 lanes pinned at `effort: xhigh` (previously inherited from the
  session). Effort is now deterministic per lane, like model choice.

## opulent 0.5.1 — 2026-07-26

*(released jointly with lens-master 1.8.1)*

- The Opus 5 lanes pinned at `effort: max` — on this side of the split, `coder`.

## opulent 0.5.0 — 2026-07-26

*(released jointly with lens-master 1.8.0)*

**The task-fit doctrine** — tier by suitability, not cost:

- Scout hard-restricted to locating (WHERE/WHAT, never WHY/WHETHER);
  interpretation belongs to the architect or an Opus lane.

## opulent 0.4.0 — 2026-07-26

- **Opus 5 takes the architect seat.** Fable exits the plugin entirely —
  reserved for manual escalation in its own session. Limits playbook falls
  back Opus → Sonnet. Session policy gains the escalation rule: admit when a
  problem exceeds reach instead of flailing.

## opulent 0.3.0 — 2026-07-18

- New `scribe` agent (Sonnet): substantive documentation with Telephone Game
  and Hostile Skimmer quality gates built in.
- README gains the usage-limits playbook (no automatic fallback exists;
  model-cap → switch session model, shared-cap → wait).

## opulent 0.2.0 — 2026-07-18

*(released jointly with lens-master 1.7.0)*

Initial public commit of the marketplace:

- **opulent** (then *fabeulous*): deterministic model routing — pinned-model
  agents (coder/mechanic/test-runner/ui-checker/scout), a PreToolUse hook
  denying main-loop edits and test runs (via the `agent_id` payload field),
  and a SessionStart hook injecting the routing policy.
