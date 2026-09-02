---
description: Self-diagnose the Opulent installation — is enforcement live, which version, what has it logged?
---

Run Opulent's health check. Perform every probe with real tool calls — never
report an expectation as a result. Finish with a compact table (check /
result / meaning), a one-line verdict, and remediation for anything that
failed.

1. **Version.** Read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json` and
   report its `version`. If that path doesn't resolve, locate the installed
   copy under `~/.claude/plugins/` and flag the anomaly.

2. **Agents registered.** From your own available-agents list: are
   `opulent:coder`, `opulent:coder-max`, `opulent:mechanic`, and
   `opulent:test-runner` present? Name any that are missing. (Implementation is
   a binary choice between the two coder lanes; there is no third. Exploration
   uses the built-in `Explore` agent, and documentation and visual verification
   both stay in the main loop — none of those is an Opulent lane, and none
   needs a check here.)

3. **Policy injected.** Is the "Model routing policy (opulent plugin)" text
   present in your current session context? Yes means the SessionStart hook
   fired for this session.

4. **Enforcement liveness — the decisive probe.** Run the probe YOURSELF, in
   the main loop — never delegate it. Subagents are exempt by design, so a
   delegated canary always succeeds and proves nothing: it creates the file
   and manufactures a false DEAD.
   Run exactly: `touch opulent-doctor-canary`
   - **Denied** with an Opulent routing message → enforcement is LIVE. A
     LIVE verdict must be corroborated in step 5: this denial appends a
     fresh `probe` line to the log, and a LIVE-looking canary with no fresh
     probe line means the log path is broken — or the probe ran in a
     subagent.
   - **Succeeds** → clean up (`rm opulent-doctor-canary`). Enforcement is
     DEAD despite the plugin being installed. Say so plainly; there is no
     dial that legitimately produces this result.

5. **Telemetry.** Tail the routing log — `$OPULENT_LOG` if set, else
   `~/.claude/opulent-log.jsonl`: total lines, counts per event, timestamp of
   the newest entry. The vocabulary: `edit` (a main-loop write, allowed and
   recorded), `test` (a main-loop test run, likewise — one command can log
   both), `delegate`, `deny` (control-plane refusals, plus the catch-all
   redirect), `remove` (rm and destructive git — reset --hard, clean,
   checkout --, restore, stash drop — logged, not denied), `unparsed` (a
   command the parser could not read, so any write in it happened unaudited),
   and `probe` (the doctor's own canary denial). `probe` is its own event for
   one reason: a denial the operator asked for must not inflate the denial
   count. Since 0.11.3 each line carries `sid` (session id) and resolved
   absolute paths, and a fresh install's session-start line reads "No routing
   activity recorded yet".

   Interpret honestly: no file + live enforcement = fresh install, fine; no
   file + recent heavy agent use = enforcement was not running when that
   work happened — the exact silent gap this command exists to catch. Third
   branch: canary denied in step 4 but no fresh `probe` line here =
   `OPULENT_LOG` points somewhere unwritable (missing parent, a directory,
   a read-only mount) and telemetry is being silently discarded — the same
   silent gap wearing a different face. A high `edit` count is not a fault:
   it is the main loop working with the record intact.

Verdict, one line: **LIVE** · **PARTIAL** (say which half works) · **DEAD**
(installed but not enforcing — recommend checking the plugin's enable state
in /plugin, restarting the session so hooks reload, and — for version drift —
BOTH `claude plugin marketplace update opulent` and then
`claude plugin update opulent@opulent`, since the first refreshes only the
marketplace cache and moves nothing on its own; run both from OUTSIDE a
session, or restart immediately after — an in-session update removes the
versioned install directory this session's hooks resolve to, and every
guarded tool call errors until restart).

PARTIAL, concretely: policy injected and/or agents registered but the canary
NOT denied → PARTIAL, SessionStart live and PreToolUse dead. Canary denied
but agents missing → PARTIAL, hooks live and agents absent.

**Mid-session enable warning.** Plugin enable/disable takes effect only at
session start: enabling Opulent mid-session registers neither its hooks nor
its agents, so the session looks and behaves as if the plugin were absent —
no denials, no telemetry, no `opulent:*` agents (verified 2026-07-29: canary
write sailed through while another plugin's session-start hooks enforced
normally). If the plugin was enabled after this session began, every probe
above is expected to fail; the remedy is simply a new session, not
reinstalling. Corollary: if `/opulent:doctor` itself was invocable from the
command list, the plugin WAS enabled at session start — a DEAD verdict then
points at a real hook failure, not enable timing.

Report what you observed, not what you expected. A surprising doctor result
is a finding, not an embarrassment — state it plainly.
