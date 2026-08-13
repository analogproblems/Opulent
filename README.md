# 💎 Opulent

> **Keep your best model in the architect seat, and push the grunt work into throwaway sessions.**

Welcome to **Opulent**! 👋

If you use Claude Code for long sessions, you already know the problem: the conversation you're actually having fills up with file bodies, test outputs, and search results you never needed to read. The model you're talking to ends up spending its context window on clutter.

Opulent solves this through strict **context hygiene**. Your best coding model (Opus 5 by default) stays in the architect seat—designing, reviewing, and orchestrating. All the execution—editing files, running tests, searching the codebase—gets pushed into separate, purpose-built agent sessions. The bulk lands there and is thrown away, keeping your main conversation clean and lean deep into your workflow.

---

## 📋 Requirements

* **Python 3** on your `PATH` (as `python3` or `python`). 
  * *Note:* This is preinstalled on macOS and most Linux distros. On Windows, please install directly from python.org rather than relying on the Windows Store alias.
* Everything else is stock Claude Code! No extra packages, no background daemons, and no network calls.

## 📦 Installation

Add the marketplace once, then install:

```bash
/plugin marketplace add analogproblems/Opulent   # or a local /path/to/Opulent
/plugin install opulent@opulent
```

Or, if you want to try it without installing first:

```bash
claude --plugin-dir /path/to/Opulent
```

### ⚠️ Two Quick Timing Gotchas:
1. **Enable/Disable takes effect at session start.** Enabling a plugin mid-session does not register its hooks or agents. Always start a fresh session after toggling!
2. **Updates are a two-step process.** Running `claude plugin marketplace update opulent` only refreshes the cache. To actually update, follow it with `claude plugin update opulent@opulent` (and restart your session).

---

## 🚦 How Routing Works

Opulent routes work based on **task fit, not just cost**. Judgment and complexity go to Opus; bounded mechanical execution goes to Sonnet; locating goes to Haiku. 

Here is exactly where your tasks go:

| Work | Agent | Model & Effort |
| :--- | :--- | :--- |
| **Architecture, review, orchestration** | *Main loop (Architect)* | Opus 5 (or Fable) |
| **Complex implementation** | `opulent:coder` | Opus, Effort: Max |
| **Complex implementation (Eco Mode)** | `opulent:coder-eco` | Opus, Effort: xHigh |
| **Routine edits, boilerplate** | `opulent:mechanic` | Sonnet |
| **Tests, builds, linters** | `opulent:test-runner` | Sonnet (Read-only) |
| **UI verification, console errors** | `opulent:ui-checker` | Sonnet + browser tools |
| **Documentation (READMEs, ADRs)** | `opulent:scribe` | Opus, Effort: xHigh |
| **Locating code and structure** | `opulent:scout` | Haiku |

*Note: You can manually escalate problems Opus can't crack to Fable in its own separate session. You can also run Fable in the Architect seat if you have access!*

---

## 🎛️ Setting the Dials (Eco Mode)

Opulent is configured via environment variables. *Note: Exporting these inside a running session does nothing, as the hooks are spawned by the harness.*

* **Eco Mode (`OPULENT_ECO=1`):** Runs complex implementation one effort rung down. It routes `opulent:coder` tasks to `opulent:coder-eco` (Opus at `xhigh` effort instead of `max`). 
* **Kill Switch (`OPULENT_OFF=1`):** Disables enforcement entirely for that session.
* **Custom Logs (`OPULENT_LOG=<path>`):** Redirects the telemetry log from its default location.

**How to set them:**
Per launch:
```bash
OPULENT_ECO=1 claude
```
Persistently (in `~/.claude/settings.json`):
```json
{ "env": { "OPULENT_ECO": "1" } }
```
*(0, false, no, off, and empty all count as unset).*

---

## 🛡️ Enforcement & Honesty

Opulent uses built-in Claude Code hooks (PreToolUse and SessionStart). 

**What it enforces:**
A hook denies ordinary paths to writing code, running tests, or delegating to catch-all agents directly from the main loop, pointing the model toward the specific lanes above. It explicitly protects the **control plane** (`.claude/` directories, `.env` files) from main-loop edits so changes aren't made silently. 

**What it isn't:**
This is a seatbelt with an audit trail, not a flawless security boundary. A determined model *can* bypass it via inline scripts or exotic utilities. The goal is to make the recorded path the path of least resistance, keeping your project edits visible in `~/.claude/opulent-log.jsonl`. 

*(Bonus: Opulent is designed to **fail-open**. If a Claude Code update breaks a payload the hook can't parse, it allows the action. An update will never brick your sessions.)*

---

## 🩺 Verify It's Working

Run `/opulent:doctor` in your session. 

It probes the installation with real tool calls (checking version, registered agents, injected policies, and enforcement liveness via a canary write) and gives you a one-line verdict (**LIVE / OFF / PARTIAL / DEAD**) along with remediation steps. 

*(Remember: run this in a session started AFTER the plugin was enabled!)*

---

## 📝 License

This project is MIT licensed. Please see our house rules in `CONTRIBUTING.md`, chiefly the honesty policy.
