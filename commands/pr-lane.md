---
description: Render the pr-lane ledger — where each unit stands, what is blocked on what, and whether the config parsed.
---

Report the state of this project's PR lane. **Read-only**: this command renders
what the ledger already says. It opens nothing, merges nothing, sweeps nothing
and edits nothing — if it tells you a unit is blocked, acting on that is a
separate decision you make afterwards.

1. **Render.** Run exactly, in the project directory:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/hooks/pr_lane.py" || python "${CLAUDE_PLUGIN_ROOT}/hooks/pr_lane.py"
   ```

   The `python3 … || python …` shape is the same fallback `hooks.json` uses:
   on Windows the Store `python3` alias is a stub that fails, and `python` is
   the real interpreter. The script takes an optional project directory; with
   none it uses `CLAUDE_PROJECT_DIR`, else the working directory.

2. **Report what came back, unedited.** The output already carries the four
   things this command exists to say:
   - whether `.claude/pr-lane.json` is absent, unparseable, or parsed (and
     with which base, merge mode and review provider);
   - the ledger path and how many records it holds;
   - one line per unit: latest event, review verdict, PR, CI, branch, SHA;
   - a `blocked:` section — coded with no review, review came back NOT SAFE,
     a PR open with no CI verdict, CI failed, or handed off to the user — and
     the summary line session start renders.

3. **Add nothing the ledger does not say.** If a unit shows no branch or no
   SHA, that field was never recorded, and it is not yours to infer from the
   repository. Say "not recorded". The ledger's value is that everything in it
   was observed; a plausible reconstruction beside those facts destroys the
   only property it has.

4. **If the config is absent**, say so and stop: the module is off for this
   project, and nothing else in this command applies. Creating the config is
   the user's call, and the routing hook denies writing it from the main loop
   in any case — it is configuration, like `settings.json`. The ledger is not:
   `.claude/pr-lane/ledger.jsonl` is the one file under `.claude/pr-lane/` you
   may append to, which is how a unit gets a `unit_defined` or `handed_off`
   record. Append a single JSON object on one line — `{"t","sid","unit",
   "event","by":"model"}` plus any of `branch`, `sha`, `pr`, `verdict`,
   `note` — and never rewrite a line that is already there.

**What phase 1 does not do**, so nobody reads absence as a verdict: it does not
deny `gh pr merge` or a push to the base branch, does not gate the session's
end, does not sweep issues, does not clean up worktrees, and does not open or
merge anything. The hook records `coded`, `reviewed`, `pr_opened`, `ci` and
`merged` when it sees them go past — and only when a brief carried the
`PR-LANE CONTRACT v1` marker, for `coded`. A unit that was implemented without
that marker is simply not in the ledger; that is a gap in the record, not a
claim that the work did not happen.
