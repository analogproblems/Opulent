# Changelog

This repo serves one plugin. Entries dated before 2026-08-09 were released
from the shared repo opulent and lens-master used to co-inhabit, so the older
ones note the companion release they shipped beside; lens-master's own notes
left with it. That shared history, and every tag before `opulent--v0.11.0`,
lives on in a private archive repo — public history here starts at 0.11.0, and
the earlier versions are not pinnable from this remote.

Versions are pinnable via git tags in the form `{plugin}--v{version}`
(e.g. `opulent--v0.11.0`).

## opulent 0.17.0 — 2026-09-03

**Both implementation lanes step down one rung.** `opulent:coder` moves from
xhigh to high and `opulent:coder-max` from max to xhigh. The relative shape is
unchanged — one default, one escalation a single step above it, reached only by
a named hazard or a failed attempt — but the whole ladder now sits lower.

This puts the default one step below Anthropic's published xhigh recommendation
for coding, which is a departure worth naming rather than burying. The
reasoning is the one this plugin already applies to max: effort above the work
returns worse code, not safer code, because what it cannot spend on the problem
it spends on structure the problem never needed. The published guidance is a
general recommendation; a routing plugin whose entire premise is that most work
does not deserve the top tier is exactly the context where a general
recommendation should be re-examined. The CI pin moves with it and keeps its
job: the departure has to stay a decision somebody made, not drift.

**The Sonnet lanes come down with them**, from xhigh to high, which reverses
a call made two days ago in 0.15.0. That reasoning — with the cheap coder rungs
gone there is no tier below mechanic and test-runner to fall through to — has
not changed and was never the problem. What changed is that only half the
matrix moved: leaving the support lanes at xhigh while the implementation lane
dropped to high left the Sonnet lanes reading as nominally harder-thinking than
the Opus one. That is not incoherent, since effort scales are not comparable
across models and Sonnet-at-xhigh remains far cheaper than Opus-at-high, but it
is confusing on the page, and a routing table that has to be explained before
it can be read is a routing table that will be misread. Everything now sits at
high except the hazard lane.

**The delegation bridge stops being about Workflow.** It was written for
`ultracode` because that was the case in front of us. The real rule is wider:
most agents a session can spawn are not opulent lanes, and nearly all of them
declare `model: inherit` or no model at all — which means they run at the
session's tier. Thirty such agents were installed here against four routed
lanes, so the plugin can never win this by enumerating them.

That default is correct for its author. Someone shipping an agent cannot see
your session and has no business pinning a model into it; `inherit` is the
humble answer. It is also the exact inverse of this plugin's premise, and the
two are only incoherent together — neither is a bug. So the policy now states
the general case before the Workflow one: before spawning anything that is not
a lane, ask what tier the work deserves, because a foreign agent's charter is
rarely worth the tier it silently costs. Workflow keeps its own paragraph for
the reason it always had one — it is the case nothing records.

CI pins `inherit` in the policy text alongside `agentType` and `Workflow`, so
the broadened rule cannot quietly narrow back to the case that prompted it.

## opulent 0.16.0 — 2026-09-01

**Documentation stops being a lane.** `opulent:scribe` is removed, and the
architect writes its own docs. This is the second cut of its kind and it has
the same reason behind it as the first: the model that made the design
decisions is the only one that can say why they went this way rather than the
other. A lane briefed on the outcome produces prose that accurately describes
what the code does while quietly losing why it does it — and "why" is the only
part of a document that the code could not have told you itself.

The lane's quality gate moves into the policy rather than dying with it:
summarize the doc, then summarize the summary, and if the core point does not
survive two generations, restructure until it does. Grounding every claim in
the code, and keeping every command and path copy-pasteable, move across the
same way. Those were the best of the scribe charter, and deleting the lane
without rehoming them would have deleted the discipline along with the
executor.

The charter's other gate did not make the move. It asked for a reread as a
busy reader who sees only the first line of each paragraph and section — and
run against this changelog it passes, which is precisely the problem. It
passes because the prose was written to pass, and what a first-lines-only
reader takes away from an entry is every claim and not one reason. A file
whose whole job is to say *why* cannot be tuned for a reader who skips the
why. The gate also rewards bolding the opening words of every paragraph until
emphasis stops meaning anything, and it fights the payoff-last sentences this
repo's prose actually leans on. What was load-bearing in it — do not bury the
point — the Telephone Game already catches, from the clarity side rather than
the layout side.

Trivial doc edits stay delegated. A typo, a stale path, a version bump — those
are mechanical whatever file they land in, and `opulent:mechanic` still takes
them. The line is not "documents are special", it is that explaining a design
is part of making it.

**Four lanes left**, and the shape is finally legible: two Opus coder lanes
split by hazard, two Sonnet support lanes for edits and verification, search
delegated to a built-in agent, and everything requiring the architect's own
judgment — design, orchestration, documentation, seeing the UI — kept where
that judgment lives.

**Fully decoupled from the lens plugin.** That plugin is being retired, and
this release cuts the last threads to it. The release ritual is the one that
mattered: tagging here required running the companion's lane drift guard
first, so a lane added or removed in this repo could not ship until another
repo's file agreed. Removing `opulent:scribe` tripped exactly that wire — the
guard failed on an exemption whose subject no longer existed — which is a
release blocked by a dependency that was never supposed to exist. The guard is
gone from CONTRIBUTING, and a design constraint replaces it: no tag may wait on
another repo's CI.

The doctor loses its companion probe, step 6, which asked users to test a
second plugin's danger hook from inside this one's health check. The live e2e
tier's description is corrected while we are here — it claimed to run by manual
dispatch from a private companion's CI, which had not been true since that repo
went public; a maintainer runs it by hand, and that is now what it says. The
public gate's stored denylist was already empty and stays empty; only its
explanation is reworded, so nothing there reads as a live dependency.

The delegation bridge keeps its principle and drops its vocabulary. Contracts
still have to be pasted into briefs verbatim, because instructions do not cross
the agent boundary on their own — but the examples no longer name lenses and
oaths, since those were another plugin's words for it.

## opulent 0.15.0 — 2026-09-01

**The matrix collapses to what it was always for.** Four coder rungs, three
session dials, a Haiku scout and a second vendor's lane came off in one pass.
What is left is five agents, one knob, and a routing decision the architect can
make without consulting a table.

**Implementation is a binary choice.** `opulent:coder` at xhigh is the answer;
`opulent:coder-max` is for a named hazard — concurrency, auth or crypto, a data
migration, money, a public contract — or a resubmission after coder failed
review or tests. `coder-high` and `coder-lite` are gone. The ladder was built
to price effort accurately, and it did, but pricing it accurately turned out to
cost a three-question interview before every delegation. The two rungs that
survive are the two that answer different questions; the middle rungs only ever
answered "how confident am I", which is not a routing question.

**`OPULENT_ECO`, `OPULENT_CODEX` and `OPULENT_OFF` are removed.** Setting them
now does nothing. Eco capped a ladder that no longer has a middle; Codex sent
implementation to another vendor, which was interesting and is not what this
plugin is; and `OPULENT_OFF` disabled every denial for a whole session, which
is a large silent hole to carry for a seatbelt. `OPULENT_LOG` stays — it is the
only dial that changes where a record goes rather than whether one exists.

Each dial cost more than its own branch. Eco and Codex each carried a duplicate
implementation-lane line and a duplicate ladder paragraph in session-start,
swapped in by `str.replace`, plus the CI checks that existed solely to catch
those substitutions silently matching nothing. With the dials gone the policy is
one string with no seams, and the checks that guarded the seams went with them.

**The Codex lane is gone entirely** — `bin/opulent-codex`, `/opulent:codex`,
`/opulent:review`, and its case suite. `sol`, `terra` and `review` worked, and
`review`'s habit of verifying every `file:line` it cited was worth having. It
leaves because a routing plugin that also vendors a second vendor's CLI is two
plugins wearing one manifest, not because the lane was bad. `/opulent:review`
goes with it rather than being rebuilt on a Claude lane: a second witness that
shares your vendor, your conversation and your assumptions is not a second
witness, and `/code-review` already covers the same-vendor case.

**Exploration goes to the built-in `Explore` agent** and `opulent:scout` is
gone, which takes Haiku out of the matrix. The hook used to deny `Explore` and
redirect to scout; it now allows it. Scout was a locate-only lane wrapped around
a model Claude Code already dispatches for exactly that job, and the wrapper's
one real contribution — "report WHERE, never WHY" — was a rule the architect
has to apply to any search result regardless of who ran it.

**`opulent:ui-checker` is gone, and UI verification stays in the main loop.**
This is the one removal that is not simplification for its own sake. A design
judgment made from another model's description of a screenshot is a design
judgment made blind; the model that decided how an interface should look is the
one that has to see whether it does. The policy now says so in as many words,
because a lane that merely disappears reads as an oversight and invites the
architect to reach for a catch-all instead.

**Sonnet lanes run at xhigh.** `opulent:mechanic` and `opulent:test-runner`
move from high. With the cheap coder rungs gone there is no longer a tier below
them to fall through to, and a mechanical edit returned wrong is not cheaper
than one returned slowly.

**The delegation bridge learns about Workflow.** `ultracode` and any other
multi-agent fan-out reaches the plugin through a hole nothing can close: a
`Workflow` call is not a `Task` or `Agent` call, so the routing hook never sees
it, and the agents its script spawns are exempt the way every subagent is. The
policy now tells the architect to set `opts.agentType` on each `agent()` call,
and to state `opts.model` and `opts.effort` rather than trust a lane's own pins
to cross that boundary unstated — the tool's documentation says an omitted
model inherits the session's, and does not say what happens when `agentType`
already names a lane that pins one, so the guidance is written to be right
either way. Without it a fan-out inherits the session model uniformly, which
runs `opulent:mechanic` and `opulent:test-runner` at Opus or Fable rates: not a
weaker version of the routing, but its exact inverse. CI now fails if the
paragraph goes missing, since nothing else would notice.

**CI keeps the removals removed.** A new check runs session-start with all
three retired dials exported and fails if the policy changes or if it so much
as mentions one of them; another fails any agent pinning a model outside the
Opus/Sonnet pair, so a Haiku lane cannot quietly return as a third tier nothing
documents.

## opulent 0.14.0 — 2026-08-24

**A Codex lane, folded in from orrery.** `bin/opulent-codex` runs one pinned
`codex exec` and reports what it actually did. Three modes: `sol` takes a
brief you wrote and lets Codex hold the pen, `terra` is the cheap tier for
bounded batch work, and `review` builds its own brief from a diff, runs
read-only, and checks every `file:line` Codex cites against the tree before
you read it — what it cannot verify prints as `UNVERIFIABLE` rather than
disappearing, because a finding that cannot be located is worth seeing and
worth distrusting.

It blocks. That is the design: the run's lifetime is the process's lifetime,
so the architect backgrounds it and the harness owns completion. Orrery
learned that the other way round — a wrapper subagent backgrounded the run and
polled a marker file, the subagent's turn ended, the harness handle and the
watcher died while Codex kept going, and the plugin grew a run registry, claim
files, staleness and orphan detection and a Stop hook to rebuild by hand the
notification the harness already sends. Deleting the wrapper deleted the
problem, and 13,185 lines became 931 before any of it moved here.

**`OPULENT_CODEX` is the dial**, built from the pieces `OPULENT_ECO` already
proved: the routing hook denies a set of lanes with a redirect, and
session-start swaps the implementation line and the ladder paragraph for
their alternates. Two differences, both load-bearing. Eco caps two rungs;
this closes all four, because the point is not a cheaper way to do the same
thing but the work being judged by a model that shares neither the vendor nor
the conversation. And eco redirects to a lane the architect can spawn next,
while this redirects to a command — so the dial does not merely change the
target of delegation, it changes its shape, from one `Agent()` call to a
brief on disk and a backgrounded run.

The matrix stays narrow on purpose. Mechanic, test-runner, ui-checker, scribe
and scout are untouched, and so is the architect: Codex shares none of the
session, so a bounded mechanical edit pays for a full brief to buy nothing,
and a second vendor adds nothing to running a test suite or locating a file.
Luna is not here either — orrery retired that lane on 2026-08-04 against a
benchmark that scored it a measured loss against `opulent:scout`.

The doctor reports the dial and checks the lane is runnable; the activity line
counts `codex` redirects the way it counts `eco` ones; and CI pins the new
constants the way it pins eco's, plus one the eco pair never needed — that
the command the redirect names is a file this plugin ships in `bin/` and is
executable. A lane that is not registered fails loudly at spawn; a command
that is not on PATH fails inside a Bash call and reads like Codex is broken.

Behaviour is covered by `tests/codex_cases.py`: argv construction, exit-code
passthrough, ledger shape, citation checking, and which files a run may be
credited with changing. Twenty-nine checks, none of which reads a sentence.
Verified end to end against codex-cli 0.149.1, both modes, before shipping.

## opulent 0.13.0 — 2026-08-24

**The ladder priced escalation wrong.** Every cue that taught rung
selection costed over-effort in tokens and nothing else — `coder-max`
was for "work where an error costs far more than the extra tokens",
`coder-high` for where "xhigh's depth isn't earning its tokens" — and
nowhere in the plugin did any text say a rung above the work returns
worse code. Under those stated rules escalating is the rational move:
under-reaching is visible and wrong in front of the user, over-reaching
costs only money the user already agreed to spend. So the architect
reached for max by reflex, which is the failure 0.12.0 built the ladder
to avoid. Escalation is now priced as a quality risk, in the agent
descriptions, the session policy, and the README: effort a rung cannot
spend on the problem it spends on structure the problem never needed.

**The criteria are facts now, not adjectives.** "Correctness-critical",
"solid work", "deep exploration" are unfalsifiable from inside the
moment before writing a spec, where everything feels correctness-
critical. The ladder paragraph asks three questions answerable from the
spec itself — can you name every file the change touches, would an
existing test or typecheck catch a wrong answer, does it touch a named
hazard (concurrency, auth or crypto, a data migration, money, a public
contract) — and maps the answers onto rungs. `coder-max` requires one of
exactly two facts, to be named in the brief: a hazard in scope, or a
lower rung that already failed review or tests. Feeling hard is not a
hazard.

**Pick the rung after writing the spec.** The old guidance was applied
while the task was still fuzzy, and fuzziness reads as complexity; the
three questions have no answers until the spec exists. The paragraph now
says so in its first sentence.

**The shared charter says what the extra effort is for.** All four rungs
carry one body and none of them explained what a higher rung buys, so
"more effort" was free to become "more change". Every rung now briefs
that effort buys depth of verification — more surrounding code read,
more edge cases considered, harder self-checking — and never extra
abstraction, extra configurability, or an unasked-for refactor: a change
larger than its spec is a defect, not thoroughness.

Eco mode's capped paragraph carries the same repricing, since the
lite/high choice it still leaves open is exactly the one this release is
about. No behavior change in the routing hook, no new denial path.

**The public gate was guarding secrets that are not secret.** Its premise —
that the companion plugin ships from a private repo whose internals must
not appear here — stopped being true when lens-master was renamed to
lens-library and published. Every term the stored list held (`supersmart`,
the three matcher constants, the danger hook's escape hatch and filename,
the shared-repo paths, the release-note heading, the pre-split tag glob)
now ships in lens-library's own public repo, verified against its
`origin/main` rather than a working tree. So the stored list and the tag
globs are empty, with the reasoning kept in place: the list is the part of
the gate meant to change, and a new private mechanism still means a new
entry in the commit that creates it. The identity-term machinery, which is
the half still doing work, is untouched.

The alternative was a history rewrite to erase `lens-master/tests` from
CONTRIBUTING.md — which would have been destructive for nothing. That
commit is already on a public `origin/main` with a fork, so no force-push
could retract it, and the path it names points into a public repository
under a name that no longer exists.

Two consequences worth naming. An empty stored list left the gate reporting
"clean" over a search for nothing, which is the shape of a check that has
quietly stopped checking; it now says it had nothing to hunt, and says that
the corpus was read. And `gate_corpus_selftest.py` harvested its two
positive controls out of the stored lists, so an empty list would have
taken the suite red — it now plants invented entries into a copy of the
gate, which tests the machinery whether or not a real secret happens to
exist. That is the better coupling: a suite that goes dark the moment there
is nothing to keep secret stops watching exactly when the list is easiest
to break.

**The companion's new name reaches the docs.** CONTRIBUTING.md and the
doctor's companion probe said `lens-master` in six places, including the
drift-guard path and a probe users are told to run by name. All now
lens-library, bar one deliberate historical reference to the 0.12.0 catch,
which happened under the old name.

## opulent 0.12.0 — 2026-08-22

**The coder lane becomes a ladder.** One effort rung per lane was a
single dial pretending to be a spectrum. The coder lane now carries
four rungs — `coder-lite` (medium), `coder-high` (high), `coder`
(xhigh, the new default), `coder-max` (max) — so the architect picks
effort by picking the agent. The deterministic task-type routing is
unchanged; the fuzzy part is bounded to default-with-exceptions, and a
misroute self-corrects by resubmitting one rung up.

Every rung is retuned to Anthropic's current effort guidance: `coder`
drops from max to xhigh (the documented best setting for coding and
agentic work — max risks overthinking), the high rung sits at the
documented sweet spot balancing quality against token efficiency, and
the four support lanes (mechanic, test-runner, ui-checker, scribe) step
from xhigh down to that same rung — the right setting for bounded
verification and non-agentic work. Scout stays effortless; Haiku 4.5
still rejects the parameter.

The eco twin is folded into the ladder as an ordinary rung: `coder-eco`
is renamed `coder-high`, which anyone can spawn in any session, and
OPULENT_ECO is redefined as capping the ladder there. So eco now caps
the ladder rather than swapping one lane: `opulent:coder` and
`opulent:coder-max` are both denied with a redirect to `coder-high`,
while the cheaper rungs stay spawnable — voluntarily spending less is
never a routing violation. The redirect's message is reworded to match:
it now says implementation is "capped at the eco rung" rather than
"runs one effort rung down", which was false for a coder-max caller
falling two. CI's sync check covers the whole ladder rather than a
single twin: all coder variants carry the charter verbatim and may
differ only in name, description, and effort, each pinned to its rung.
Breaking: the `opulent:coder-eco` name is gone — spawn
`opulent:coder-high`.

One pre-existing hole closed by the same review: a spawn payload whose
subagent_type was a list or dict used to raise out of the hook's
set-membership test into the fail-open, allowing the spawn with no log
line — the one Task shape that left no record. It is now coerced to a
string and recorded like any other delegation.

## opulent 0.11.3 — 2026-08-13

**What the second review found.** Six fresh-context lenses over the
freshly-hardened 0.11.2 produced a 76-item inventory and ~70 targeted
mutants; the 20 hook-suite and 11 gate-suite mutation survivors are now
killed. Round one was about holes in denial; this round was mostly about
the honesty of the record.

**The record grew teeth.** Every log line now carries the session id
(`sid`) and resolved absolute paths, so concurrent sessions stay
distinguishable and the detail names real files; `mv` logs `src -> dst`.
A command that writes AND tests logs both events — `pytest > results.txt`
used to log only the edit. Two new events: `unparsed` (a command the
tokenizer could not read — the write, if any, happened unaudited; one
unbalanced apostrophe used to blind the parser silently) and `remove`,
covering `rm` and destructive git (`reset --hard`, `clean`, `checkout --`,
`restore`, `stash drop`) — logged, not denied, because the record was
silent on precisely the hardest-to-undo operations. The log now guards
itself: the main loop may not overwrite or delete its own audit record;
resetting it is the user's call, between sessions. And the session-start
activity line always counts delegations, denials, edits and test runs —
the commonest post-0.9.0 session, edits and tests with no denial, used to
render as silence — while a fresh log prints "No routing activity recorded
yet" with the path.

**The parser learned the accidental shapes.** Writers inside `for`/`if`/
`while` bodies; `cp`/`mv` with a directory destination; `find -exec`;
`xargs cp -t`; the `>&file` redirect; `git am`; `timeout`/`nohup`/
`stdbuf`/`setsid` prefixes; `install`, `ln`, `dd`, `curl -o`, `wget -O`.
The heredoc false positive is fixed — a doc-writing command whose heredoc
mentioned a settings path was denied, with a fabricated audit line — the
patch read-cap now completes a header pair straddling it, and the no-level
strip fan-out is bounded (a crafted 2 MiB patch could stall the hook 14 s).
Each landed test-first with its false-positive twin, per the house rule.
`VERSION_RE` is deleted: it suppressed real test records (`npm test &&
tsc --version` logged nothing), and over-logging is the safe direction.

**Tests a no-op can no longer pass.** The hook suite grew 144 → 297 cases:
the event list is asserted by equality rather than membership (a fabricated
extra event now fails), every line is schema-checked, every denial kind has
its reason text asserted (the Explore redirect could previously name the
wrong lane unnoticed), and each case carries a subprocess timeout — the old
suite, pointed at the 0.11.1 hook, hung forever. Before any of it was
committed, a second adversarial pass over the day's own diff caught three
regressions the new code had introduced — here-strings eaten as heredocs,
`/usr/bin/time -o` unguarded, newline-separated `cd` unpeeled — each landing
back as a red case first; that pass is the last 37 of the 297. The gate suites (16 + 17
cases) gained the plants the 0.11.2 entry claimed: multi-line terms, a
capitalized occurrence, all four refusal paths, `DENY_TAGS`, stash refs —
with one honest correction: git notes were in fact visible to the old gate
(stashes were not), so that entry overstated the blind spot by one ref
family. The e2e checks are rewritten so the injected policy cannot satisfy
them: the agent check relays a nonce through a real `opulent:scout` run,
and the denial check gained an allow-side control — an ordinary write must
be allowed and logged as `edit`.

**The doctor stopped trusting its own shortcuts.** The canary probe must
run in the main loop — a delegated canary is exempt by design, always
succeeds, and manufactured a false DEAD. The dial echo is reported as what
the shell sees, never as authority (the hook reads the harness
environment), and the canary runs regardless. It no longer asks for lane
names the canary message never contained; a LIVE verdict must be
corroborated by a fresh `probe` line in the log tail; and step 5 gained
its third branch — canary denied but no probe line means `OPULENT_LOG`
points somewhere unwritable and telemetry is being silently discarded.
PARTIAL is now defined instead of merely listed.

**README re-grounded in the code.** Enforcement is described as it is:
main-loop edits and test runs allowed and recorded, the denied set listed
exactly (the control plane in both scopes — the user's and the project's
`.claude` — plus Explore, catch-alls, and the log itself), and the record
covering the architect's own hands, not lane work. The dials take effect
at the next session start, the settings.json recipe is named as an edit
the assistant itself will be denied, and the Windows note now saves the
Windows reader: python.org ships no `python3`, both Store aliases must be
disabled, and a missing interpreter is silently zero enforcement.

**Open, named honestly:** whether ui-checker's `tools: mcp__Claude_Browser`
server-name grant resolves to actual browser tools still needs one probe in
an opulent-enabled session; and SessionStart context is verified NOT to
reach subagents in the desktop harness, so lanes never receive the
delegate-everything policy.

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
