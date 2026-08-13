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

4. **Enforcement liveness — the decisive probe.** Run the probe YOURSELF, in
   the main loop — never delegate it. Subagents are exempt by design, so a
   delegated canary always succeeds and proves nothing: it creates the file
   and manufactures a false DEAD. First run
   `echo "OPULENT_OFF=[$OPULENT_OFF] OPULENT_ECO=[$OPULENT_ECO]"` and report
   both dials — as what the Bash shell sees, never as authority: the hook
   reads the harness environment, which can differ (launcher vs shell rc).
   Even if the echo shows `OPULENT_OFF` set, run the canary; the denial, or
   its absence, is the authority.
   Run exactly: `touch opulent-doctor-canary`
   - **Denied** with an Opulent routing message → enforcement is LIVE. A
     LIVE verdict must be corroborated in step 5: this denial appends a
     fresh `probe` line to the log, and a LIVE-looking canary with no fresh
     probe line means the log path is broken — or the probe ran in a
     subagent.
   - **Succeeds** → clean up (`rm opulent-doctor-canary`). If the harness
     truly has `OPULENT_OFF` set, this is enforcement intentionally OFF
     (the injected policy carries an OFF note in that case); otherwise
     enforcement is DEAD despite the plugin being installed. Say which,
     plainly.

   `OPULENT_ECO` is a separate dial and changes nothing about this probe. If
   it is set, report eco mode as **ON**, not as a fault: the implementation
   lane for the session is `opulent:coder-eco` (Opus, effort xhigh), and a
   spawn of `opulent:coder` is *expected* to be denied with a redirect to the
   twin — that denial is eco mode working. Confirm `opulent:coder-eco` is in
   your available-agents list while you are there; eco mode with no twin
   registered leaves implementation with nowhere to go.

5. **Telemetry.** Tail the routing log — `$OPULENT_LOG` if set, else
   `~/.claude/opulent-log.jsonl`: total lines, counts per event, timestamp of
   the newest entry. The vocabulary: `edit` (a main-loop write, allowed and
   recorded), `test` (a main-loop test run, likewise — one command can log
   both), `delegate`, `deny` (control-plane refusals, plus the catch-all and
   Explore redirects), `remove` (rm and destructive git — reset --hard,
   clean, checkout --, restore, stash drop — logged, not denied), `unparsed`
   (a command the parser could not read, so any write in it happened
   unaudited), `probe` (the doctor's own canary denial), and `eco` (the
   `opulent:coder` redirect under `OPULENT_ECO`). `probe` and `eco` are
   their own events for one shared reason: a denial the operator asked for
   must not inflate the denial count. Since 0.11.3 each line carries `sid`
   (session id) and resolved absolute paths, and a fresh install's
   session-start line reads "No routing activity recorded yet".
   Interpret honestly: no file + live enforcement = fresh install, fine; no
   file + recent heavy agent use = enforcement was not running when that
   work happened — the exact silent gap this command exists to catch. Third
   branch: canary denied in step 4 but no fresh `probe` line here =
   `OPULENT_LOG` points somewhere unwritable (missing parent, a directory,
   a read-only mount) and telemetry is being silently discarded — the same
   silent gap wearing a different face. A high `edit` count is not a fault:
   it is the main loop working with the record intact.

6. **Companion probe.** If you also run the lens-master plugin — skip on
   sight otherwise — and only when its agents are registered AND
   `git remote` prints something (a dry run still contacts the remote and
   can hang on a credential prompt, so a remoteless repo skips too): run
   `git push --dry-run`. Denied with a Secret Keeper message → danger hook
   live (that denial logs as verdict `probe` in the danger log, keeping its
   denial count honest too). If it executes, it was a dry run — harmless —
   report the danger hook as not live.

Verdict, one line — append `· ECO` when `OPULENT_ECO` is set, since a session
running one rung down should say so: **LIVE** · **OFF** (by OPULENT_OFF — intentional) ·
**PARTIAL** (say which half works) · **DEAD** (installed but not enforcing —
recommend checking the plugin's enable state in /plugin, restarting the
session so hooks reload, and — for version drift — BOTH
`claude plugin marketplace update opulent` and then
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
