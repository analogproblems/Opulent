#!/usr/bin/env python3
"""Live end-to-end smoke tests: load the plugin into throwaway headless
Claude sessions (--plugin-dir, no install) and verify that a registered
agent actually runs and that the hook actually enforces — both proven by
evidence only the real thing can produce, never by the model's narration.

Requires the claude CLI, authenticated for the user running this script.
Model defaults to haiku for cost; override with CLAUDE_E2E_MODEL."""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.environ.get("CLAUDE_E2E_MODEL", "haiku")

# shutil.which resolves .cmd/.exe shims on Windows, which bare subprocess
# argv[0] lookup does not.
CLAUDE = shutil.which("claude")
if not CLAUDE:
    raise SystemExit("claude CLI not found on PATH — install and authenticate it on this runner")


def scratch_dir():
    """A throwaway directory, removed on exit — the same mkdtemp + atexit
    pattern as the other suites. This file used to be the one suite that
    leaked its temp dir."""
    d = tempfile.mkdtemp(prefix="opulent-e2e-")
    atexit.register(shutil.rmtree, d, True)
    return d


def run_claude(plugin_dir, prompt, allowed_tools=None, log=None, cwd=None):
    cmd = [CLAUDE, "--plugin-dir", plugin_dir, "-p"]
    if allowed_tools:
        # --allowedTools is variadic and would swallow a trailing positional
        # prompt, so it must be followed by another option, never the prompt.
        cmd += ["--allowedTools", allowed_tools]
    cmd += ["--model", MODEL, prompt]
    env = dict(os.environ)
    if log:
        # Point the routing log at a scratch file so this run's telemetry can
        # be read back as evidence, without appending test noise to the
        # operator's real log.
        env["OPULENT_LOG"] = log
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                       cwd=cwd or REPO, env=env)
    if p.returncode != 0:
        print(p.stdout)
        print(p.stderr, file=sys.stderr)
        raise SystemExit(f"claude exited {p.returncode}")
    return p.stdout


def read_events(log):
    """Every parseable line of a routing log. Tolerant on purpose: the hook
    is free to grow fields (a session id, resolved absolute paths) and event
    kinds (remove, unparsed) without breaking this suite — every assertion
    below filters for the one event it needs and substring-matches a
    basename, never a whole path or a whole line."""
    events = []
    try:
        with open(log, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return events


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


# 1. A registered opulent agent actually runs. The previous version asked the
# model to recite its agent roster and grepped for the lane names — but every
# one of them appears verbatim in the policy this plugin injects into that same
# session, so a session with ZERO registered agents passed by quoting its own
# instructions back. The needle is now a per-run nonce planted in a file in
# the session's scratch cwd: the injected policy cannot contain it, so only a
# subagent that really spawned and really read the file can relay it. And the
# `delegate` event naming the lane can only be written by the routing hook —
# narration can claim a spawn; the log line proves one was dispatched.
work = scratch_dir()
NONCE = os.urandom(16).hex()
with open(os.path.join(work, "nonce.txt"), "w", encoding="utf-8") as fh:
    fh.write(NONCE + "\n")
AGENT_LOG = os.path.join(scratch_dir(), "routing.jsonl")
out = run_claude(REPO,
    "Use your subagent dispatch tool (Task or Agent) to spawn the agent type "
    "opulent:test-runner with exactly this task: 'Read the file nonce.txt in "
    "the current working directory and reply with its exact contents.' Then "
    "repeat the exact string the agent returned as your final answer. Do "
    "not read the file yourself. If the spawn fails or that agent type does "
    "not exist, reply exactly SPAWN FAILED and stop.",
    allowed_tools="Task,Agent,Read", log=AGENT_LOG, cwd=work)
check("opulent:test-runner relays a nonce only a real agent run can produce",
      out, NONCE)
events = read_events(AGENT_LOG)
delegated = [e for e in events
             if e.get("event") == "delegate"
             and "opulent:test-runner" in json.dumps(e)]
if delegated:
    passed += 1
    print("PASS  routing hook records the delegation "
          f"(logged: {delegated[0].get('detail')})")
else:
    print("FAIL  routing hook records the delegation: no `delegate` event "
          "naming opulent:test-runner was logged, so the hook did not see "
          "the spawn")
    print("--- session output ---")
    print(out)
    print("--- routing log ---")
    print(events or "(empty)")
    raise SystemExit(1)

# 2. Routing hook denies a main-loop write to the control plane — and allows
# an ordinary write in the same session. Since 0.9.0 ordinary main-loop
# writes are allowed-and-logged; only files that govern the running session
# (settings, hooks, agents, commands, plugins, .env) are refused. Write
# permission is pre-granted so the denial we observe comes from the routing
# hook, not Claude Code's generic headless permission gate.
CONTROL_TARGET = os.path.join(REPO, ".claude", "settings.json")
ORDINARY = os.path.join(REPO, "e2e-ordinary.txt")
# A developer's checkout may legitimately carry an untracked settings.json;
# only a file that APPEARS during the run is evidence the hook failed. The
# ordinary write lands in the repo checkout rather than a temp dir on
# purpose: system-temp paths are scratch to the hook — allowed and
# deliberately unlogged — so a temp-dir control could never produce the
# `edit` event this check exists to read. Both files are removed below.
control_preexisting = os.path.exists(CONTROL_TARGET)
ordinary_preexisting = os.path.exists(ORDINARY)
# Telemetry, not narration, is the evidence. The previous version asserted
# that the session TEXT contained "Routing policy", "control plane" and
# "opulent:coder" — but all three of those strings are in the policy this
# plugin injects into that same session, so a model that declined to attempt
# the write and merely recited its instructions passed the check with the
# PreToolUse hook never invoked. It was also hostage to the model's phrasing:
# a run where the hook fired correctly and the model paraphrased the denial
# failed a green plugin. A `deny` line naming this path can only be written by
# the hook, and only when it actually ran.
LOG = os.path.join(scratch_dir(), "routing.jsonl")
out = run_claude(REPO,
    "Make exactly two Write tool calls, in this order, and never retry a "
    "call. First: create the file e2e-ordinary.txt in the current directory "
    "with content 'ordinary'. Second: create the file .claude/settings.json "
    "in the current directory with content '{}'. If a call is denied, quote "
    "the exact denial message you received and continue.",
    allowed_tools="Write", log=LOG)

events = read_events(LOG)
denied = [e for e in events
          if e.get("event") == "deny"
          and "settings.json" in str(e.get("detail", ""))]
if denied:
    passed += 1
    print("PASS  routing hook denies control-plane write "
          f"(logged: {denied[0].get('detail')})")
else:
    print("FAIL  routing hook denies control-plane write: no `deny` event "
          "naming settings.json was logged, so the hook did not fire")
    print("--- session output ---")
    print(out)
    print("--- routing log ---")
    print(events or "(empty)")
    raise SystemExit(1)
if not control_preexisting and os.path.exists(CONTROL_TARGET):
    os.remove(CONTROL_TARGET)
    print("FAIL  denial reported but the control-plane file was actually created")
    raise SystemExit(1)

# The allow-side control. A hook that denied EVERYTHING would sail through
# the denial check above exactly as well as a healthy one — the check only
# proves the hook can say no, not that it ever says yes. The same session's
# ordinary write must therefore appear in the log as an `edit` event, and
# must NOT appear as a `deny`. Matched on the basename as a substring: the
# hook may record the raw spelling or a resolved absolute path, and either
# carries the basename.
ordinary_edits = [e for e in events
                  if e.get("event") == "edit"
                  and "e2e-ordinary.txt" in str(e.get("detail", ""))]
ordinary_denies = [e for e in events
                   if e.get("event") == "deny"
                   and "e2e-ordinary.txt" in str(e.get("detail", ""))]
if not ordinary_preexisting and os.path.exists(ORDINARY):
    os.remove(ORDINARY)
if ordinary_edits and not ordinary_denies:
    passed += 1
    print("PASS  ordinary write allowed and recorded "
          f"(logged: {ordinary_edits[0].get('detail')})")
else:
    if ordinary_denies:
        print("FAIL  ordinary write allowed and recorded: a `deny` event "
              "names e2e-ordinary.txt — the hook denies more than the "
              "control plane")
    else:
        print("FAIL  ordinary write allowed and recorded: no `edit` event "
              "names e2e-ordinary.txt, so the write was never recorded "
              "(or never attempted)")
    print("--- session output ---")
    print(out)
    print("--- routing log ---")
    print(events or "(empty)")
    raise SystemExit(1)

print(f"\n{passed}/4 live checks passed")
