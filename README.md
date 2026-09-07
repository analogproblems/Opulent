# 💎 Opulent

> **Keep your best model in the architect seat, and push the grunt work into throwaway sessions.**

Welcome to **Opulent**! 👋

If you use Claude Code for long sessions, you already know the problem: routing every single command through your most powerful model burns through tokens at an alarming rate. You end up paying premium token costs just to have your primary model read routine test outputs, execute basic file edits, or search the codebase.

Opulent solves this by intelligently dividing the workload across Anthropic's model family based on their recommended use cases, drastically reducing your token spend.

Your most capable model (Opus 5 or Fable) stays in the architect seat—designing, reviewing, orchestrating, documenting its own decisions, and seeing the UI it asked for with its own eyes. Meanwhile, the high-volume execution—running tests, applying standard code edits—is automatically delegated to Sonnet, and searching goes to Claude Code's own read-only `Explore` agent.

By routing the bulk data to the right tool for the job, Opulent preserves your expensive tokens for complex reasoning and keeps your sessions incredibly efficient.

---

## 📋 Requirements

* **Python 3** on your `PATH`, reachable as **either** `python3` **or** `python` — the hooks try them in that order, so one of the two is enough. 
  * *Note:* Preinstalled on macOS and most Linux distros. On Windows, install from python.org — it ships `python.exe` only, no `python3`. The Microsoft Store's `python3` alias is a **stub** that fails fast without running anything, and the hooks fall through to `python` when it does, so the alias is a nuisance rather than a breakage. (Disabling both App execution aliases — Settings → Apps → Advanced app settings → App execution aliases — still makes for a quieter terminal.) A *missing* interpreter is the real hazard: silently **no enforcement**, because fail-open cannot cover an interpreter that never started.
* Everything else is stock Claude Code! No extra packages, no background daemons, and no network calls.
* The hook self-tests run on **Linux, Windows and macOS** in CI, on every push and every pull request — the hook's whole job is reading paths, and paths are where the platforms disagree.

## 📦 Installation

Add the marketplace once, then install:

```text
/plugin marketplace add analogproblems/Opulent   # or a local /path/to/Opulent
/plugin install opulent@opulent
```

*(Those two are slash commands — type them inside Claude Code, not in your shell.)*

Or, if you want to try it without installing first:

```bash
claude --plugin-dir /path/to/Opulent
```

### ⚠️ Three Quick Timing Gotchas:
1. **Enable/Disable takes effect at session start.** Enabling a plugin mid-session does not register its hooks or agents. Always start a fresh session after toggling!
2. **Updates are a two-step process.** Running `claude plugin marketplace update opulent` only refreshes the cache. To actually update, follow it with `claude plugin update opulent@opulent` (and restart your session).
3. **Update from outside a session.** Running `claude plugin update` inside a session removes the versioned install directory the running session's hooks resolve to, so every guarded tool call errors until restart. Update from a plain terminal, or restart immediately after.

---

## 🚦 How Routing Works

Opulent routes work based on **task fit, not just cost**. Judgment and complexity stay with the architect or go to Opus lanes; bounded mechanical execution goes to Sonnet; locating goes to the built-in `Explore` agent. 

Here is exactly where your tasks go:

| Work | Agent | Model & Effort |
| :--- | :--- | :--- |
| **Architecture, orchestration, docs, UI verification** | *Main loop (Architect)* | Your session model — set with `/model` (Opus 5 or Fable) |
| **All complex implementation** | `opulent:coder` | Opus, Effort: xHigh |
| **Routine edits, boilerplate** | `opulent:mechanic` | Sonnet, Effort: xHigh |
| **Tests, builds, linters** | `opulent:test-runner` | Sonnet, Effort: High (no edit tools) |
| **Code review before merge** | `opulent:reviewer` | Opus, Effort: High (edit tools for its memory only) |
| **Locating code and structure** | *Built-in `Explore` agent* | Claude Code's own read-only searcher |

*A lane whose definition lists no tools (`opulent:coder`, `opulent:mechanic`) inherits all tools. `opulent:test-runner` lists read-only tools on purpose. `opulent:reviewer` lists the same four, and the harness adds Write and Edit because it keeps a project memory; its charter confines them to that memory directory.*

**Implementation isn't a choice.** `opulent:coder` at `xhigh` — Anthropic's recommended setting for coding — takes every non-trivial change. There is no rung above it and nothing to escalate to, which means there is no routing decision left to get wrong.

**Hazards moved from routing to briefing.** Earlier versions escalated concurrency, auth or crypto, data migrations, money and public contracts to a `max`-effort second lane. That lane is gone, but the list isn't — it now tells you when a brief has to be written carefully rather than which agent to spawn. Name the hazard, say what must not break, and name the check that would catch it if it did; the lane can't ask you a follow-up question, so a hazard you didn't mention is one it doesn't know about. If its output fails review, the answer is a better brief or your own hands — not a bigger lane.

**Review is a lane, and it does not fix.** `opulent:reviewer` runs on Opus at `high` with Read, Grep, Glob and a read-only Bash — plus the Write and Edit the harness grants for its project memory, which its charter confines to that directory — because a reviewer that fixes stops reporting. Its charter is the test-runner's stance turned on a diff: report every finding, labelled by confidence, and let the architect filter. It also checks the two things ad-hoc reviewers usually skip — whether the brief's named hazard has a check in the diff that would actually fail, and whether a red-then-green claim is real. Debugging is deliberately *not* a lane: `opulent:test-runner` diagnoses, the architect decides, `opulent:coder` fixes with the diagnosis in its brief.

**Two jobs are deliberately not lanes.** The architect keeps both, for the same reason.

*UI verification* — the architect drives the browser itself. A design judgment made from another model's description of a screenshot is a design judgment made blind; the model that decided how the interface should look is the one that needs to see whether it does.

*Documentation* — the architect writes its own. It made the design decisions, so it's the only one that can say why they went this way rather than the other. Hand the job to a lane briefed on the outcome and you get prose that accurately describes what the code does while quietly losing why it does it. (Typos, stale paths and version bumps are mechanical, and still go to `opulent:mechanic`.)

*Note: You can manually escalate problems Opus can't crack to Fable in its own separate session. You can also run Fable in the Architect seat if you have access!*

---

## 🚀 Fan-outs, ultracode, and other plugins' agents

Most agents you can spawn aren't Opulent lanes — other plugins ship their own, and a workflow script gets a generic one. Nearly all of them declare `model: inherit` or no model at all, which means **they run at your session's tier**. That's the right default for an author who can't see your session, and the wrong outcome inside one. It's also the one place Opulent's routing can't reach by itself, so it's worth two minutes of your time.

**The catch.** A `Workflow` call isn't a `Task` or an `Agent` call, so Opulent's hook never sees it — and the helpers that script spawns are exempt the way every subagent is. Left alone, each one simply copies your *session* model. On an Opus session that means the mechanical edits and the test suite run on Opus too. That isn't a weaker version of the routing; it's the exact inverse of it, and it's the one way to make Opulent cost you money instead of saving it.

**The fix.** Opulent's injected policy now tells your architect to name the lane on every job, rather than leaving the field blank. So a fan-out step should look like this:

```js
agent("update the config files", {
  agentType: "opulent:mechanic",
  model: "sonnet",
  effort: "xhigh"
})
```

...instead of a bare `agent("update the config files")`. Naming the lane is what hands the job that lane's charter and tool restrictions; spelling out the model and effort alongside it is cheap insurance, since the docs don't quite say whether a lane's own pins survive that boundary unstated.

**Being straight with you:** this one is guidance, not enforcement. Nothing can see inside a running workflow, so if your architect forgets to name a lane, there's no denial and no log line — it just quietly costs more. It's the only part of Opulent that works because the model reads the policy and agrees with it, rather than because something checks. Worth eyeballing the script on your first big fan-out.

---

## 🧵 pr-lane (opt-in; phase 1 records)

Some projects ship every change as one reviewed PR per unit — one implementation lane in an isolated worktree off the base branch, a test that is red before the change and green after, a review before the PR opens, a compile of the merged tree when the base has moved, every CI leg green, then a merge. Opulent 0.25.0 makes that process survive a session. Create `.claude/pr-lane.json` in a project and three things happen:

* **The policy grows a block** describing the loop and a **brief contract** (marker line `PR-LANE CONTRACT v1`) that the architect pastes verbatim into every implementation brief. The contract is filled from the config: base branch, step-zero / check / test / lint commands, the shared-machine lock directory and build target, the commit identity and trailer, the PR footer, who merges.
* **The routing hook keeps a ledger** at `.claude/pr-lane/ledger.jsonl`, appending one line per observed event: `coded` when `opulent:coder` or `opulent:mechanic` returns from a brief that carried the marker, `reviewed` (with SAFE / NOT SAFE) when the configured review provider returns, `pr_opened` / `ci` / `merged` when it sees `gh pr create`, `gh pr checks` settle, or `gh pr merge` go past. Recorded when the hook sees the call return, like the routing log — a `gh pr merge` whose output reports an error, or one that only armed `--auto`, is not recorded — and never inferred. The architect may append two events itself, `unit_defined` and `handed_off`.
* **`/opulent:pr-lane` renders it** — one line per unit with its latest event, verdict, PR, CI, branch and SHA, then what is blocked on what. The session-start summary line comes from the same renderer, so a new session knows where every unit stands without a plan file.

**What phase 1 does not do, so absence is never read as a verdict:** it does not deny `gh pr merge` or a push to the base branch, does not gate the end of a turn, does not sweep issues, does not arm auto-merge, and does not remove worktrees. Those are phases 2 and 3. It denies exactly one new thing, and does so whether or not a project opted in: a main-loop write to `.claude/pr-lane.json`, because that file is configuration like `settings.json` and the write that creates it is the one to deny. Without the config the two hooks are byte-identical to 0.24.0 — `tests/ci_checks.py` asserts it against the 0.24.0 script.

Two honest limits of a record built from observation: a review spawned without a `unit:` line in its brief renders as `(unattached)`; a unit implemented from a brief that lacked the marker is simply not in the ledger. Both are gaps in the record, not claims about the work.

A config, every key optional except `schema`. `${SCRATCHPAD}` expands to `CLAUDE_SCRATCHPAD_DIR`, `CLAUDE_SCRATCHPAD` or `OPULENT_SCRATCHPAD` if one is set, else the system temp directory — so a build lock defaults to machine-wide, which is what a shared lock wants:

```json
{
  "schema": "pr-lane/1",
  "base": "main",
  "commands": { "step_zero": "scripts/web-build.ps1",
                "check": "cargo check --all-targets",
                "test":  "cargo test",
                "lint":  "cargo clippy --all-targets -- -D warnings" },
  "shared_machine": { "lock_dir": "${SCRATCHPAD}/build-lock",
                      "target_dir": "C:/src/project/target", "max_lanes_building": 2 },
  "git": { "user": "Your Org", "email": "hello@example.com",
           "trailer": "Co-Authored-By: Claude <noreply@anthropic.com>",
           "never_commit": [".claude/agent-memory/**"] },
  "pr": { "merge": "architect", "method": "squash",
          "footer": "🤖 Generated with [Claude Code](https://claude.com/claude-code)" },
  "review": { "provider": "opulent:reviewer" },
  "hazards": ["concurrency", "auth", "crypto", "migration", "money", "public-contract"]
}
```

`pr.merge` is `architect`, `user` or `auto` (`auto` is accepted and does nothing yet); a brief's `hazard:` line names one of `hazards` or `none`, and a hazard PR is merged by the user whatever `pr.merge` says.

---

## 🎛️ Configuration

There is one knob, and most people never touch it.

* **Custom Logs (`OPULENT_LOG=<path>`):** Redirects the telemetry log from its default location, `~/.claude/opulent-log.jsonl`. Set it to `/dev/null` to keep no record at all.

*Note: The hook reads this from the environment Claude Code was launched with — exporting it inside a running session does nothing, and a change takes effect at the next session start.*

Per launch:
```bash
OPULENT_LOG=/tmp/opulent.jsonl claude
```
Persistently (in `~/.claude/settings.json`):
```json
{ "env": { "OPULENT_LOG": "/tmp/opulent.jsonl" } }
```

One heads-up: if you ask the assistant to make that `settings.json` edit for you, the hook will deny it — settings files are the control plane, so the change gets redirected to a lane. That's the design working; make the edit yourself in an editor if you prefer.

*Versions before 0.15.0 also shipped `OPULENT_ECO`, `OPULENT_CODEX`, and `OPULENT_OFF`. All three are gone; setting them now does nothing.*

---

## 🛡️ Enforcement & Honesty

Opulent uses built-in Claude Code hooks: `SessionStart` injects the policy, `PreToolUse` decides, and `PostToolUse` records. 

**What it enforces:**
Main-loop edits and test runs are **allowed and logged** — the hook records what the architect touches instead of blocking it, and it records them *after they have run*, so a call that some other plugin's hook refused never shows up as if it happened. What it *does* deny from the main loop: the **control plane** (any `.claude` directory's hooks, agents, commands and plugins — except `plugins/data/`, which is plugin state — the `settings*.json` beside them and another plugin's hook config such as `hookkit.json`, the user's and the project's, plus `.env` files, templates like `.env.example` excepted), catch-all agents (`general-purpose`, `claude`), and the routing log itself.

On Windows the PowerShell tool is guarded too, at text level: a command whose text names a control-plane path — as one literal, or as `.claude` and a control-plane name appearing together in a write-shaped command — is denied, and a write-shaped command the guard cannot read is recorded as `unparsed`. There is no PowerShell parser: a path built from a variable assigned in an earlier command is beyond it, exactly as it is beyond the Bash guard — and so is any other spelling only a parser could see. This is the seatbelt described below, not a boundary; the log says `unparsed` instead of pretending.

**What it isn't:**
This is a seatbelt with an audit trail, not a flawless security boundary. A determined model *can* bypass it via inline scripts or exotic utilities. The goal is to make the recorded path the path of least resistance: the log (`~/.claude/opulent-log.jsonl` by default) records main-loop edits, test runs, delegations, denials, and removals, session-tagged — outcomes, not attempts: everything but a denial is written once the tool has succeeded. Work done inside lanes isn't logged, and neither is anything inside a multi-agent workflow (see above) — the record covers the architect's own hands. The log is yours to delete between sessions; the main loop is denied touching it.

*(Bonus: Opulent is designed to **fail-open**. If a Claude Code update breaks a payload the hook can't parse, it allows the action. An update will never brick your sessions.)*

---

## 🩺 Verify It's Working

Run `/opulent:doctor` in your session. 

It probes the installation with real tool calls (checking version, registered agents, injected policies, and enforcement liveness via a canary write) and gives you a one-line verdict (**LIVE / PARTIAL / DEAD**) along with remediation steps. 

*(Remember: run this in a session started AFTER the plugin was enabled!)*

---

## 📝 License

This project is MIT licensed. Version history lives in [`CHANGELOG.md`](CHANGELOG.md). Please see our house rules in `CONTRIBUTING.md`, chiefly the honesty policy.
