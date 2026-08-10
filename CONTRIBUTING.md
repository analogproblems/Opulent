# Contributing

Small project, strong opinions. The opinions:

## The honesty policy

Every claim in the docs must be backed by the code, and every calibration
line must trace to evidence — Anthropic's documented model behavior, a
measured result, or a verified finding. If you can't cite it, don't ship it.
"No change needed" is a legitimate audit outcome; speculative seatbelts are
not. When code and README disagree, fixing the README to match reality is a
valid and welcome PR.

## Development loop

```
python3 tests/hook_selftest.py                      # routing hook payload cases
python3 tests/ci_checks.py                          # marketplace manifests + session-start JSON
python3 tests/gate_selftest.py                      # the gate finds planted terms, and never prints them
python3 tests/public_gate.py                        # no private residue in the object database
python3 tests/validate_plugins.py                   # claude CLI structure validation (needs claude on PATH)
```

Both `ci_checks.py` and `validate_plugins.py` derive their member roster from
`marketplace.json`, so a member sourced from another repo is skipped with a
notice instead of failing — its manifest and CI live in its own tree.

Hook changes need test cases — both the deny you're adding and the
false-positive you're *not* adding (quoted strings, `--version` lookups,
sibling script names). The first four suites run on every push and every
pull request, on GitHub-hosted runners — which is the whole of this repo's CI,
because no self-hosted runner serves a public repository. The live end-to-end
tier (`tests/e2e_smoke.py`) drives real throwaway Claude sessions against an
authenticated `claude` CLI, and that CLI lives on a personal machine, so the
tier is not part of this repo's CI at all: the private companion repo runs it
by manual dispatch, from a checkout of our main. The scripts stay here, beside
the thing they test — run them yourself if you have an authenticated CLI.
Nothing you can open a PR against needs them.

## Releases

Bump `version` in `.claude-plugin/plugin.json` (this is what triggers
marketplace update detection — a version-less change never reaches installed
users), add a CHANGELOG entry that says *why*, and tag with
`claude plugin tag <path> --push` (`{plugin}--v{version}`).

Adding an implementation lane (unrestricted-tools agent)? lens-master's
IMPL_LANES must learn it in the same release window — its drift guard will
fail against our main until it does.

## Design constraints worth knowing before you propose things

- **Fail-open is sacred.** A hook that can brick a session on a parse error
  will not be merged. Unknown payload shapes allow; errors allow. This governs
  hooks, not CI: `tests/public_gate.py` fails *closed* by design, because a
  scan that could not read the object database has not cleared it.
- **Enforcement is a seatbelt, not a wall** — see the README's "What
  enforcement is — and isn't". PRs that chase perfect enforcement by
  blocking ever-more Bash will lose to the ergonomics they cost.
- **The plugins must stay independently installable.** opulent must not
  require lens-master, or vice versa.
- **Prompts are code.** Agent definitions carry contracts (coverage-first
  reporting, locate-only scout); dilute them and the tests won't catch it, but
  a fresh-context review will.
