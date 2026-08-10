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
   `opulent:coder`, `opulent:mechanic`, `opulent:test-runner`,
   `opulent:ui-checker`, `opulent:scribe`, and `opulent:scout` present?
   Name any that are missing.

3. **Policy injected.** Is the "Model routing policy (opulent plugin)" text
   present in your current session context? Yes means the SessionStart hook
   fired for this session.

4. **Enforcement liveness — the decisive probe.** First run
   `echo "OPULENT_OFF=[$OPULENT_OFF] OPULENT_ECO=[$OPULENT_ECO]"` and report
   both dials. If `OPULENT_OFF` is set, report that enforcement is
   intentionally off for this session and skip the probe.
   Otherwise run exactly: `touch opulent-doctor-canary`
   - **Denied** with an Opulent routing message → enforcement is LIVE.
     Quote the message's lane names — namespaced `opulent:*` names confirm
     a current version is the one enforcing.
   - **Succeeds** → enforcement is DEAD despite the plugin being installed.
     Clean up (`rm opulent-doctor-canary`) and say so plainly.

   `OPULENT_ECO` is a separate dial and changes nothing about this probe. If
   it is set, report eco mode as **ON**, not as a fault: the implementation
   lane for the session is `opulent:coder-eco` (Opus, effort xhigh), and a
   spawn of `opulent:coder` is *expected* to be denied with a redirect to the
   twin — that denial is eco mode working. Confirm `opulent:coder-eco` is in
   your available-agents list while you are there; eco mode with no twin
   registered leaves implementation with nowhere to go.

5. **Telemetry.** Tail the routing log — `$OPULENT_LOG` if set, else
   `~/.claude/opulent-log.jsonl`: total lines, counts per event, timestamp of
   the newest entry. Since 0.9.0 the vocabulary is `edit` (a main-loop write,
   allowed and recorded), `test` (a main-loop test run, likewise), `delegate`,
   `deny` (control-plane refusals, plus the catch-all and Explore redirects),
   `probe`, and — since 0.10.0 — `eco` (the `opulent:coder` redirect under
   `OPULENT_ECO`, given its own event for the same reason `probe` has one: a
   redirect the operator asked for should not inflate the denial count).
   Interpret honestly: no file + live enforcement = fresh
   install, fine; no file + recent heavy agent use = enforcement was not
   running when that work happened — the exact silent gap this command exists
   to catch. A high `edit` count is not a fault: it is the main loop working
   with the record intact, which is what 0.9.0 traded the old denials for.
   Since v0.8.6 the doctor's own canary denial is logged as event "probe" so
   repeated doctor runs do not inflate the denial count; on older versions it
   appears as a plain denial.

6. **Companion probe (only if lens-master agents are registered and the cwd
   is a git repo).** Run `git push --dry-run`. Denied with a Secret Keeper
   message → danger hook live. If it executes, it was a dry run — harmless —
   report the danger hook as not live. Since lens-master 1.11.1 the probe's
   denial appears in the danger log as verdict `probe` rather than `deny`, so
   doctor runs do not inflate that log's denial count either; on older
   versions it logs as a plain deny.

Verdict, one line — append `· ECO` when `OPULENT_ECO` is set, since a session
running one rung down should say so: **LIVE** · **OFF** (by OPULENT_OFF — intentional) ·
**PARTIAL** (say which half works) · **DEAD** (installed but not enforcing —
recommend checking the plugin's enable state in /plugin, restarting the
session so hooks reload, and `claude plugin marketplace update opulent` for
version drift).

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
