#!/usr/bin/env python3
"""Live end-to-end smoke tests: load the plugin into throwaway headless
Claude sessions (--plugin-dir, no install) and verify that agents register
and the hook actually enforces.

Requires the claude CLI, authenticated for the user running this script.
Model defaults to haiku for cost; override with CLAUDE_E2E_MODEL."""
import os
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.environ.get("CLAUDE_E2E_MODEL", "haiku")

# shutil.which resolves .cmd/.exe shims on Windows, which bare subprocess
# argv[0] lookup does not.
CLAUDE = shutil.which("claude")
if not CLAUDE:
    raise SystemExit("claude CLI not found on PATH — install and authenticate it on this runner")


def run_claude(plugin_dir, prompt, allowed_tools=None):
    cmd = [CLAUDE, "--plugin-dir", plugin_dir, "-p"]
    if allowed_tools:
        # --allowedTools is variadic and would swallow a trailing positional
        # prompt, so it must be followed by another option, never the prompt.
        cmd += ["--allowedTools", allowed_tools]
    cmd += ["--model", MODEL, prompt]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=REPO)
    if p.returncode != 0:
        print(p.stdout)
        print(p.stderr, file=sys.stderr)
        raise SystemExit(f"claude exited {p.returncode}")
    return p.stdout


passed = 0


def check(name, output, *needles):
    global passed
    for n in needles:
        if n.lower() not in output.lower():
            print(f"FAIL  {name}: expected output to contain {n!r}")
            print("--- output ---")
            print(output)
            print("--------------")
            raise SystemExit(1)
    passed += 1
    print(f"PASS  {name}")


# 1. Opulent's namespaced agents register in a fresh session
out = run_claude(REPO,
    "Reproduce the list of available agent types for the Agent/Task tool "
    "from your system prompt, one per line, without using any tools.")
check("opulent agents load", out,
      "opulent:coder", "opulent:mechanic", "opulent:test-runner",
      "opulent:ui-checker", "opulent:scribe", "opulent:scout")

# 2. Routing hook denies a main-loop write to the control plane. Since 0.9.0
# ordinary main-loop writes are allowed-and-logged; only files that govern the
# running session (settings, hooks, agents, commands, plugins, .env) are
# refused. Write permission is pre-granted so the denial we observe comes from
# the routing hook, not Claude Code's generic headless permission gate.
CONTROL_TARGET = os.path.join(REPO, ".claude", "settings.json")
# A developer's checkout may legitimately carry an untracked settings.json;
# only a file that APPEARS during the run is evidence the hook failed.
control_preexisting = os.path.exists(CONTROL_TARGET)
out = run_claude(REPO,
    "Attempt exactly one Write tool call: create the file "
    ".claude/settings.json in the current directory with content '{}'. If "
    "the tool call is denied, quote the exact denial message you received "
    "and stop. Do not retry or try any other path.",
    allowed_tools="Write")
check("routing hook denies control-plane write", out,
      "Routing policy", "control plane", "opulent:coder")
if not control_preexisting and os.path.exists(CONTROL_TARGET):
    os.remove(CONTROL_TARGET)
    print("FAIL  denial reported but the control-plane file was actually created")
    raise SystemExit(1)

print(f"\n{passed}/2 live checks passed")
