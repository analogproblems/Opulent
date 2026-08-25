---
description: Codex second-witness review of a diff — read-only, with every cited file:line checked to exist before you see it.
argument-hint: "[<rev-range>]"
---

Put Codex on the current work as a second witness: a different vendor's model,
with none of your conversation and none of your assumptions.

One command, backgrounded — the harness re-invokes you when it exits:

```
opulent-codex review <absolute dir> [--range <rev-range>]
```

With no `--range` it reviews the working tree against `HEAD` when the tree is
dirty, and this branch's commits since it left the default branch when it is
clean. `$ARGUMENTS`, if it names a range, becomes `--range`.

The script builds the brief, pins the sandbox read-only, and checks every
`file:line` Codex cites against the tree before printing it. Citations it
could not verify are marked `UNVERIFIABLE` and shown anyway — a finding that
cannot be located is worth seeing and worth distrusting, and dropping it
silently is the one outcome worse than showing a bad one.

Relay the findings with those markers intact. Do not review the diff yourself
alongside it: a second opinion you wrote is the one thing this command cannot
buy.
