# 💎 Opulent

> **Keep your best model in the architect seat, and push the grunt work into throwaway sessions.**

Welcome to **Opulent**! 👋

If you use Claude Code for long sessions, you already know the problem: routing every single command through your most powerful model burns through tokens at an alarming rate. You end up paying premium token costs just to have your primary model read routine test outputs, execute basic file edits, or search the codebase.

Opulent solves this by intelligently dividing the workload across Anthropic's model family based on their recommended use cases, drastically reducing your token spend.

Your most capable model (Opus 5 or Fable) stays in the architect seat—designing, reviewing, orchestrating, and seeing the UI it asked for with its own eyes. Meanwhile, the high-volume execution—running tests, applying standard code edits—is automatically delegated to Sonnet, and searching goes to Claude Code's own read-only `Explore` agent.

By routing the bulk data to the right tool for the job, Opulent preserves your expensive tokens for complex reasoning and keeps your sessions incredibly efficient.

---

## 📋 Requirements

* **Python 3** on your `PATH` (as `python3` or `python`). 
  * *Note:* Preinstalled on macOS and most Linux distros. On Windows, install from python.org — it ships `python.exe` only, no `python3` — then disable **both** App execution aliases (Settings → Apps → Advanced app settings → App execution aliases) and verify `python3 --version` and `python --version` in a terminal. A missing interpreter means silently **no enforcement**: fail-open can't cover an interpreter that never started.
* Everything else is stock Claude Code! No extra packages, no background daemons, and no network calls.

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

Opulent routes work based on **task fit, not just cost**. Judgment and complexity go to Opus; bounded mechanical execution goes to Sonnet; locating goes to the built-in `Explore` agent. 

Here is exactly where your tasks go:

| Work | Agent | Model & Effort |
| :--- | :--- | :--- |
| **Architecture, review, orchestration, UI verification** | *Main loop (Architect)* | Your session model — set with `/model` (Opus 5 or Fable) |
| **Complex implementation (the default)** | `opulent:coder` | Opus, Effort: xHigh |
| **Implementation touching a named hazard** | `opulent:coder-max` | Opus, Effort: Max |
| **Routine edits, boilerplate** | `opulent:mechanic` | Sonnet, Effort: xHigh |
| **Tests, builds, linters** | `opulent:test-runner` | Sonnet, Effort: xHigh (no edit tools) |
| **Documentation (READMEs, ADRs)** | `opulent:scribe` | Opus, Effort: High |
| **Locating code and structure** | *Built-in `Explore` agent* | Claude Code's own read-only searcher |

*A lane whose definition lists no tools (`opulent:coder`, `opulent:coder-max`, `opulent:mechanic`) inherits all tools.*

**Implementation is a binary choice.** `opulent:coder` at `xhigh` — Anthropic's recommended setting for coding — is the answer for every non-trivial change. The single thing that moves work off it is a **named hazard**: concurrency, auth or crypto, a data migration, money, or a public contract others depend on. That, and only that, is what `opulent:coder-max` is for, along with a resubmission after `opulent:coder` failed review or tests.

**Max is not the safe choice.** Escalation is priced here as a quality risk rather than a bill, because that is what it is: effort above the work returns *worse* code, not safer code, since what it cannot spend on the problem it spends on structure the problem never needed. Guidance that only ever priced over-effort in tokens made max the rational reflex, and the reflex is the failure mode. Feeling hard is not a hazard, and neither is caring about the outcome. The mistake is cheap in one direction only — under-reaching is visible and recoverable, so if coder's output fails review or tests, resubmit to `opulent:coder-max` and say that is why.

**UI verification is deliberately not a lane.** The architect drives the browser itself. A design judgment made from another model's description of a screenshot is a design judgment made blind — the model that decided how the interface should look is the one that needs to see whether it does.

*Note: You can manually escalate problems Opus can't crack to Fable in its own separate session. You can also run Fable in the Architect seat if you have access!*

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

Opulent uses built-in Claude Code hooks (PreToolUse and SessionStart). 

**What it enforces:**
Main-loop edits and test runs are **allowed and logged** — the hook records what the architect touches instead of blocking it. What it *does* deny from the main loop: the **control plane** (any `.claude` directory's hooks, agents, commands, plugins, and the `settings*.json` beside them — the user's and the project's — plus `.env` files, templates like `.env.example` excepted), catch-all agents (`general-purpose`, `claude`), and the routing log itself.

**What it isn't:**
This is a seatbelt with an audit trail, not a flawless security boundary. A determined model *can* bypass it via inline scripts or exotic utilities. The goal is to make the recorded path the path of least resistance: the log (`~/.claude/opulent-log.jsonl` by default) records main-loop edits, test runs, delegations, denials, and removals, session-tagged. Work done inside lanes isn't logged — the record covers the architect's own hands. The log is yours to delete between sessions; the main loop is denied touching it.

*(Bonus: Opulent is designed to **fail-open**. If a Claude Code update breaks a payload the hook can't parse, it allows the action. An update will never brick your sessions.)*

---

## 🩺 Verify It's Working

Run `/opulent:doctor` in your session. 

It probes the installation with real tool calls (checking version, registered agents, injected policies, and enforcement liveness via a canary write) and gives you a one-line verdict (**LIVE / PARTIAL / DEAD**) along with remediation steps. 

*(Remember: run this in a session started AFTER the plugin was enabled!)*

---

## 📝 License

This project is MIT licensed. Version history lives in [`CHANGELOG.md`](CHANGELOG.md). Please see our house rules in `CONTRIBUTING.md`, chiefly the honesty policy.
