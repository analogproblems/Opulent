---
description: Send a task to Codex on the Sol lane — you write the brief, one backgrounded command runs it.
argument-hint: "<task>"
---

Dispatch `$ARGUMENTS` to Codex. You write the brief; `opulent-codex` does
everything else and reports what actually happened.

1. **Write a self-contained brief** to your scratchpad. Codex shares none of
   this conversation, so the brief carries the absolute working directory, the
   goal, the constraints, the acceptance checks, and any contract or lens text
   pasted verbatim. A brief with a hole in it produces a run you cannot verify.

2. **Run one command, backgrounded**, because Sol runs routinely exceed the
   foreground Bash timeout. The harness re-invokes you when it exits:

   ```
   opulent-codex sol <absolute dir> <brief path>
   ```

   Add `--sandbox read-only` for a look-don't-touch run, `--network` if it
   genuinely needs the network, `--timeout SECS` to bound it. Do not assemble
   a `codex` command yourself: the model, effort and sandbox pins live in that
   script, and a hand-built invocation is one nobody configured and nothing
   logged.

3. **Relay the result block it prints** — outcome, files changed, exit code,
   session id, and Codex's final message. Every line of it is measured rather
   than claimed, so pass it on as it stands. A non-zero exit or an empty diff
   after an edit brief is a failure; report it as one and let the user decide
   what happens next.

You are dispatching, not implementing. Do not answer the task yourself, even
once it turns out to be small — what is being asked for is a *Codex* answer,
and a result you reached yourself has neither the provenance nor the ledger
line that was the point of sending it.
