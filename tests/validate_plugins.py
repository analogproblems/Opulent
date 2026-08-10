#!/usr/bin/env python3
"""Runs `claude plugin validate` over the marketplace manifest and every
member whose source is in this tree. The roster comes from marketplace.json,
so a new member is validated without editing CI.

Members sourced from another repo are skipped with a notice — their manifests
are not in this tree, and validating them is their own repo's CI job.

Requires the claude CLI, on PATH for the user running this script."""
import os
import shutil
import subprocess
import sys

from marketplace_members import MARKETPLACE, REPO, members

# shutil.which resolves .cmd/.exe shims on Windows, which bare subprocess
# argv[0] lookup does not.
CLAUDE = shutil.which("claude")
if not CLAUDE:
    raise SystemExit("claude CLI not found on PATH — install it on this runner")


def validate(rel):
    # Manifest paths, not directories: `validate <repo root>` resolves to the
    # marketplace manifest, so the root plugin's own plugin.json would never
    # be seen if directories were passed.
    cmd = [CLAUDE, "plugin", "validate", os.path.join(REPO, rel)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=REPO)
    if p.returncode != 0:
        print(p.stdout)
        print(p.stderr, file=sys.stderr)
        raise SystemExit(f"claude plugin validate failed: {rel}")
    print(f"validated: {rel}")


validate(MARKETPLACE)
validated = 1

for m in members():
    if m.manifest is None:
        print(f"skipped: {m.name} — source {m.where} lives in another repo")
        continue
    validate(m.manifest)
    validated += 1

print(f"\n{validated} manifests validated")
