#!/usr/bin/env python3
"""Shell-agnostic CI checks: every marketplace member's manifest parses as
JSON, agrees with its marketplace entry, and names a version CHANGELOG.md has
actually released; and the session-start hook emits valid JSON. The member
list is derived from marketplace.json, so a plugin added to the marketplace is
checked here with no edit to this file. Runs identically under PowerShell,
cmd, or bash — no pipes or heredocs required."""
import contextlib
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from marketplace_members import MARKETPLACE, REPO, members

# These scripts print em dashes, arrows and the odd accented fixture, and the
# console they print to is not always UTF-8: a Windows terminal defaults to
# cp1252, where an unencodable character raises UnicodeEncodeError and takes
# the whole run with it — a suite that dies over a dash has told you nothing
# about the code. errors="replace" so a console that truly cannot render a
# character prints a placeholder instead of failing. Guarded, because
# reconfigure() arrived in 3.7 and a wrapped stdout may not have it at all.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

with open(os.path.join(REPO, MARKETPLACE), encoding="utf-8") as f:
    json.load(f)
print(f"valid JSON: {MARKETPLACE}")

CHANGELOG = "CHANGELOG.md"


def dotted(raw, where):
    """A dotted-integer version as a comparable tuple. Anything else is loud:
    a version CI cannot compare is a version CI cannot vouch for."""
    try:
        return tuple(int(n) for n in raw.split("."))
    except (AttributeError, ValueError):
        raise SystemExit(f"{where}: {raw!r} is not a dotted-integer version")


# One plugin, one changelog, newest release first. A heading names the plugin
# and the version it shipped:
#   ## opulent 0.11.0 — 2026-08-09
# Only "## " lines count; the prose below them names things freely — including
# the note on older entries recording which companion release shipped beside
# them, which is prose precisely so it is not a heading. A heading that pairs
# two plugins is the shape this repo retired when it stopped serving two: it no
# longer parses as a version, and dying on one is the point, since a heading CI
# cannot read is a release nobody can look up.
releases = []  # (plugin, version) per heading, newest first
with open(os.path.join(REPO, CHANGELOG), encoding="utf-8") as f:
    for line in f:
        if not line.startswith("## "):
            continue
        bits = line[3:].split(" — ")[0].split(None, 1)
        if len(bits) == 2:
            releases.append((bits[0], bits[1].strip()))

# members() raises on any entry CI cannot validate — missing fields, an
# unrecognised source form, an in-tree source with no manifest behind it.
for m in members():
    if m.manifest is None:
        # Its manifest lives in another repo, so only the entry itself was
        # checked here; the plugin's own CI covers the rest.
        print(f"external member, tree checks skipped: {m.name} <- {m.where}")
        continue
    with open(os.path.join(REPO, m.manifest), encoding="utf-8") as f:
        manifest = json.load(f)
    if manifest.get("name") != m.name:
        raise SystemExit(
            f"{m.manifest}: plugin name {manifest.get('name')!r} does not match "
            f"marketplace entry {m.name!r}")
    print(f"valid JSON: {m.manifest} (member {m.name})")

    # A version the changelog never announced is a version nobody can read the
    # release notes for; a changelog ahead of the manifest is a bump that only
    # half happened. Every heading for this member is parsed, so a malformed
    # one is caught even when a good entry exists further down.
    if not manifest.get("version"):
        raise SystemExit(f"{m.manifest}: no version field")
    ver = dotted(manifest["version"], m.manifest)
    logged = [(dotted(v, CHANGELOG), v) for plugin, v in releases if plugin == m.name]
    if not any(v == ver for v, _ in logged):
        raise SystemExit(
            f"{CHANGELOG}: no release entry for {m.name} {manifest['version']} "
            f"(the version in {m.manifest}) — a shipped version needs a heading")
    # The FIRST heading is the one a reader takes for the current release, so
    # it must equal the manifest AND be the maximum present — "first by
    # document order" alone would bless a new entry filed under the old ones.
    if logged[0][0] != ver:
        raise SystemExit(
            f"{CHANGELOG}: first {m.name} heading is {logged[0][1]}, but "
            f"{m.manifest} says {manifest['version']} — the shipped version "
            f"must lead the changelog")
    if logged[0][0] != max(v for v, _ in logged):
        raise SystemExit(
            f"{CHANGELOG}: first {m.name} heading {logged[0][1]} is not the "
            f"highest version present — entries must be newest-first")
    print(f"released in {CHANGELOG}: {m.name} {manifest['version']}")

# Implementation is one file since 0.21.0. The charter-sync machinery that used
# to hold a second copy in step went with the copy; what remains is the pair of
# pins on the surviving file — the effort it runs at, and the charter its body
# has to actually carry.
ORIGINAL = "agents/coder.md"


def agent_parts(path):
    """(frontmatter fields, body) of an agent definition. Read as bytes, so
    "identical" means identical — line endings and trailing newline included."""
    try:
        with open(os.path.join(REPO, path), "rb") as fh:
            lines = fh.read().split(b"\n")
    except OSError as exc:
        raise SystemExit(f"{path}: cannot read agent definition ({exc.strerror})")
    if not lines or lines[0].strip() != b"---":
        raise SystemExit(f"{path}: no --- frontmatter block")
    end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == b"---"), None)
    if end is None:
        raise SystemExit(f"{path}: frontmatter block is never closed")
    front = {}
    for line in lines[1:end]:
        key, sep, value = line.decode("utf-8").partition(":")
        if sep:
            front[key.strip()] = value.strip()
    return front, b"\n".join(lines[end + 1:])


def hook_namespace(relpath, stdin=""):
    """A hook's module namespace, without letting it run the session: stdout
    captured, stdin stubbed so nothing can block on a read, and the sys.exit()
    every hook ends with swallowed. Reading a hook's own constants is what
    makes a check about the hook rather than about a copy of its text — a
    constant CI retypes is a constant CI cannot vouch for."""
    path = os.path.join(REPO, relpath)
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    # __file__ is set because a module executed from a file has one, and since
    # 0.25.0 the hooks use it to find their sibling pr_lane.py. Without it the
    # exec'd copy would silently take the "no pr-lane module" branch and every
    # check below would pass for a reason that is not the code's.
    ns = {"__name__": "_hook_under_test", "__file__": path}
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compile(source, path, "exec"), ns)
    except SystemExit:
        pass  # every hook ends in allow()/deny(), which is a sys.exit
    finally:
        sys.stdin = real_stdin
    return ns


def constant(ns, name, relpath):
    if name not in ns:
        raise SystemExit(f"{relpath}: no {name} constant — this check reads the "
                         f"hook's own constants and cannot find that one")
    return ns[name]


routing = hook_namespace("hooks/route-models.py")
policy_ns = hook_namespace("hooks/session-start.py")

front, body = agent_parts(ORIGINAL)
# The default, pinned rather than merely inherited: Anthropic's guidance puts
# coding and agentic work at xhigh, and a default that drifted up to max would
# undo the one distinction this plugin still draws about implementation. 0.17.0
# tried a step below this and 0.18.0 put it back the same day — the pin is the
# reason that round trip is legible instead of invisible.
if front.get("effort") != "xhigh":
    raise SystemExit(
        f"{ORIGINAL}: effort is {front.get('effort')!r}, expected 'xhigh' — "
        f"the default implementation lane is xhigh, Anthropic's recommended "
        f"coding setting")
# A lane whose body says nothing briefs nobody, and nothing else in this file
# would notice: every other check reads frontmatter. This is the one assertion
# that the charter is still in there.
CHARTER = b"implementation specialist"
if CHARTER not in body:
    raise SystemExit(
        f"{ORIGINAL}: the body never says {CHARTER.decode()!r} — the only "
        f"implementation lane would brief nobody")
print(f"charter intact: {ORIGINAL}")
hook = os.path.join(REPO, "hooks", "session-start.py")

# The lane roster, pinned across every surface that names it. Derived from
# agents/*.md frontmatter, so a renamed or deleted lane fails here instead of
# leaving a policy, a doctor and a README pointing at an agent that is not
# registered. Names and models are pinned, not prose.
AGENTS = {}
for fn in sorted(os.listdir(os.path.join(REPO, "agents"))):
    if not fn.endswith(".md"):
        continue
    fr, _ = agent_parts(os.path.join("agents", fn))
    if not fr.get("name") or not fr.get("model"):
        raise SystemExit(f"agents/{fn}: frontmatter must carry name and model")
    AGENTS[fr["name"]] = fr["model"].strip().lower()
if len(AGENTS) != 4:
    raise SystemExit(
        f"agents/: expected the four lane definitions, found {len(AGENTS)}: "
        f"{', '.join(sorted(AGENTS))}")
# Haiku left with the scout lane in 0.15.0, and a lane that quietly reappeared
# on it would be a third tier the policy never mentions and the README never
# lists. Opus and Sonnet are the whole matrix now: two Opus judgment lanes
# (coder, reviewer) and two Sonnet execution lanes (mechanic, test-runner),
# with documentation and UI verification kept by the architect rather than
# delegated at all.
stray = sorted(n for n, m in AGENTS.items() if m not in ("opus", "sonnet"))
if stray:
    raise SystemExit(
        f"agents/: {', '.join(stray)} pin a model outside the Opus/Sonnet "
        f"matrix — the policy tiers work across those two and nothing else")
CONTEXT = constant(policy_ns, "CONTEXT", "hooks/session-start.py")
with open(os.path.join(REPO, "commands", "doctor.md"), encoding="utf-8") as fh:
    doctor_text = fh.read()
with open(os.path.join(REPO, "README.md"), encoding="utf-8") as fh:
    readme_text = fh.read()
# Matched WITH its backticks, which is how all three surfaces render a lane
# name. The delimiters outlived the lane that made them load-bearing —
# `opulent:coder` was a substring of `opulent:coder-max` until 0.21.0 — and
# they stay, because the next lane sharing a prefix would reopen that hole.
for name in sorted(AGENTS):
    lane = "`opulent:" + name + "`"
    for where, text in (("hooks/session-start.py CONTEXT", CONTEXT),
                        ("commands/doctor.md", doctor_text),
                        ("README.md", readme_text)):
        if lane not in text:
            raise SystemExit(f"{where}: lane {lane} is registered in agents/ "
                             f"but never named here")
for name, model in sorted(AGENTS.items()):
    lane = "`opulent:" + name + "`"
    rows = [l for l in readme_text.splitlines() if lane in l and "|" in l]
    if not rows:
        raise SystemExit(f"README.md: no routing-table row names {lane}")
    for row in rows:
        if model not in row.lower():
            raise SystemExit(
                f"README.md: the {lane} row does not say {model} — the table "
                f"and agents/{name}.md disagree on the model: {row!r}")
print("lane roster pinned across agents/, session-start, doctor.md, README: "
      + ", ".join(sorted(AGENTS)))

# Exploration has no opulent lane, so nothing above pins it: the roster check
# only sees lanes that exist. Without this, deleting the scout lane could
# silently leave the policy telling sessions to search with nothing at all.
if "`Explore`" not in CONTEXT:
    raise SystemExit(
        "hooks/session-start.py: CONTEXT never names the built-in `Explore` "
        "agent — exploration is routed there since 0.15.0, and a policy that "
        "names no searcher leaves the architect grepping by hand")

# The Workflow bridge, pinned for the same reason and more urgently: a Workflow
# call is not a Task/Agent call, so route-models.py never sees it, and the
# agents its script spawns are exempt outright. This paragraph is the ONLY
# thing routing a fan-out into opulent lanes. Deleted or reworded away, every
# ultracode run silently spends the session model on work the Sonnet lanes
# exist to take — and nothing anywhere would report it.
for needle in ("agentType", "Workflow", "inherit"):
    if needle not in CONTEXT:
        raise SystemExit(
            f"hooks/session-start.py: CONTEXT never says {needle!r} — the "
            f"delegation bridge is the only mechanism routing workflow agents "
            f"into opulent lanes, because the hook cannot see inside a "
            f"Workflow call at all")
print("the policy carries the Workflow delegation bridge")


def lane_line(context, where):
    """The policy's implementation-lane line — the thing the session actually
    routes on. Asserting on the whole document is self-satisfying, since every
    lane name appears somewhere in the prose either way."""
    for line in context.split("\n"):
        if line.startswith("- Complex implementation"):
            return line
    raise SystemExit(f"{where}: no '- Complex implementation' lane line in the policy")


out = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                     timeout=30, env=dict(os.environ))
if out.returncode != 0:
    print(out.stderr, file=sys.stderr)
    raise SystemExit(f"session-start.py exited {out.returncode}")
payload = json.loads(out.stdout)
context = payload["hookSpecificOutput"]["additionalContext"]
plain_lane = lane_line(context, "session-start")
if "`opulent:coder`" not in plain_lane:
    raise SystemExit(
        f"session-start: the implementation lane is not `opulent:coder`: "
        f"{plain_lane!r}")
print("session-start emits valid JSON with routing policy")

# The dials retired in 0.15.0 stay retired. A session that still had one of
# them exported would otherwise get a different policy than the one this repo
# documents, and the failure is silent in exactly the direction that matters:
# OPULENT_OFF used to disable every denial for the whole session.
RETIRED = ("OPULENT_ECO", "OPULENT_CODEX", "OPULENT_OFF")
dialled = subprocess.run(
    [sys.executable, hook], capture_output=True, text=True, timeout=30,
    env=dict(os.environ, **{name: "1" for name in RETIRED}))
if dialled.returncode != 0:
    print(dialled.stderr, file=sys.stderr)
    raise SystemExit(f"session-start.py exited {dialled.returncode} with the retired dials set")
dialled_ctx = json.loads(dialled.stdout)["hookSpecificOutput"]["additionalContext"]
if lane_line(dialled_ctx, "session-start with retired dials") != plain_lane:
    raise SystemExit(
        f"session-start: setting {', '.join(RETIRED)} changed the implementation "
        f"lane — those dials were removed in 0.15.0 and must do nothing")
for name in RETIRED:
    if name in dialled_ctx:
        raise SystemExit(
            f"session-start: the policy still mentions {name}, a dial removed "
            f"in 0.15.0 — the session is being taught a knob that is not there")
print("the dials retired in 0.15.0 do nothing: " + ", ".join(RETIRED))

# The commonest session shape is edits and test runs with no denial at all; an
# activity line that omitted them reported that session as silence. Removals
# and unparsed commands are report-when-seen, like probes.
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    fh.write('{"t": "2026-08-13T00:00:00+00:00", "event": "edit", "detail": "/p/app.py"}\n')
    fh.write('{"t": "2026-08-13T00:00:01+00:00", "event": "test", "detail": "pytest -q"}\n')
    fh.write('{"t": "2026-08-13T00:00:02+00:00", "event": "remove", "detail": "/p/old.py"}\n')
    fh.write('{"t": "2026-08-13T00:00:03+00:00", "event": "unparsed", "detail": "echo x"}\n')
    activity_log = fh.name
try:
    act = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                         timeout=30, env=dict(os.environ, OPULENT_LOG=activity_log))
    act_summary = json.loads(act.stdout)["hookSpecificOutput"]["additionalContext"]
finally:
    os.unlink(activity_log)
for needle in ("1 edits", "1 test runs", "0 delegations", "0 denials",
               "1 removals", "1 unparsed commands"):
    if needle not in act_summary:
        raise SystemExit(
            f"session-start: activity line does not report {needle!r} for a "
            f"log holding exactly that — the record's staple events must be "
            f"counted out loud")
print("session-start counts edits, test runs, removals and unparsed commands")

# The probe has its own event precisely so it stays out of the denial count.
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    fh.write('{"t": "2026-08-06T00:00:00+00:00", "event": "delegate", "detail": "opulent:coder"}\n')
    fh.write('{"t": "2026-08-06T00:00:01+00:00", "event": "probe", "detail": "canary:/p/x"}\n')
    probe_log = fh.name
try:
    telem = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                           timeout=30, env=dict(os.environ, OPULENT_LOG=probe_log))
    summary = json.loads(telem.stdout)["hookSpecificOutput"]["additionalContext"]
finally:
    os.unlink(probe_log)
if "1 probes" not in summary:
    raise SystemExit(
        "session-start: a `probe` event in the routing log is not reported in "
        "the activity line")
if "0 denials" not in summary:
    raise SystemExit(
        "session-start: the doctor's canary probe is being counted as a denial "
        "— that is the counter it was given its own event to keep honest")
print("session-start reports probes without inflating the denial count")

# A fresh install has an empty (or absent) log; the model must still learn
# the log path, or the record is unfindable exactly when it matters most.
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    empty_log = fh.name
try:
    quiet = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                           timeout=30, env=dict(os.environ, OPULENT_LOG=empty_log))
    quiet_ctx = json.loads(quiet.stdout)["hookSpecificOutput"]["additionalContext"]
finally:
    os.unlink(empty_log)
if "No routing activity recorded yet" not in quiet_ctx or empty_log not in quiet_ctx:
    raise SystemExit(
        "session-start: a session with an empty log must still say so and "
        "name the log path")
print("session-start names the log path even before any activity")

# --- pr-lane (0.25.0), opt-in and inert until opted into --------------------
#
# The property everything else rests on: in a project with no
# `.claude/pr-lane.json`, this hook emits what 0.24.0 emitted, byte for byte.
# Asserted against the real 0.24.0 file rather than against a description of
# it — the baseline is read out of the object database and RUN, so a policy
# edit that happens to keep the line count cannot pass for "unchanged".
PR_LANE_BASELINE = "13316c0"     # the last commit before pr-lane existed
pr_ns = hook_namespace(os.path.join("hooks", "pr_lane.py"))
MARKER = constant(pr_ns, "MARKER", "hooks/pr_lane.py")


def session_context(cwd, hook_path=None):
    """additionalContext from one run of the session-start hook, in `cwd`.

    OPULENT_LOG is pointed at the null device and CLAUDE_PROJECT_DIR is
    cleared, so two runs a second apart are comparable: with a real log the
    activity line moves under the check, and with an inherited project dir the
    result would depend on whose machine CI is standing in for."""
    env = dict(os.environ, OPULENT_LOG=os.devnull)
    env.pop("CLAUDE_PROJECT_DIR", None)
    out = subprocess.run([sys.executable, hook_path or hook], capture_output=True,
                         text=True, timeout=30, cwd=cwd, env=env)
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        raise SystemExit(f"session-start.py exited {out.returncode} in {cwd}")
    return json.loads(out.stdout)["hookSpecificOutput"]["additionalContext"]


def pr_lane_project(config=None):
    """A throwaway project directory, with `.claude/pr-lane.json` in it when
    `config` is given."""
    root = tempfile.mkdtemp(prefix="opulent-prlane-")
    if config is not None:
        os.makedirs(os.path.join(root, ".claude"))
        with open(os.path.join(root, ".claude", "pr-lane.json"), "w",
                  encoding="utf-8") as fh:
            fh.write(config)
    return root


VALID_CONFIG = json.dumps({
    "schema": "pr-lane/1",
    "base": "main",
    "commands": {"step_zero": "scripts/build.sh", "check": "cargo check",
                 "test": "cargo test", "lint": "cargo clippy -- -D warnings"},
    "shared_machine": {"lock_dir": "${SCRATCHPAD}/build-lock",
                       "target_dir": "/src/target", "max_lanes_building": 2},
    "git": {"trailer": "Co-Authored-By: Someone <someone@example.com>",
            "user": "Someone", "email": "someone@example.com",
            "never_commit": [".claude/agent-memory/**"]},
    "pr": {"footer": "Generated with Claude Code", "merge": "architect",
           "method": "squash"},
    "review": {"provider": "opulent:reviewer"},
    "hazards": ["concurrency", "auth", "crypto", "migration", "money",
                "public-contract"],
}, indent=2)

_none_project = pr_lane_project()
_cfg_project = pr_lane_project(VALID_CONFIG)
_bad_project = pr_lane_project("{ this is not json")
try:
    plain = session_context(_none_project)
    baseline = subprocess.run(
        ["git", "show", f"{PR_LANE_BASELINE}:hooks/session-start.py"],
        capture_output=True, cwd=REPO)
    if baseline.returncode == 0 and baseline.stdout:
        with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False) as fh:
            fh.write(baseline.stdout)
            baseline_hook = fh.name
        try:
            was = session_context(_none_project, baseline_hook)
        finally:
            os.unlink(baseline_hook)
        if plain != was:
            raise SystemExit(
                "session-start: with no .claude/pr-lane.json the output is no "
                f"longer {PR_LANE_BASELINE}'s (0.24.0) — the opt-in is not "
                "opt-in. First difference at character "
                f"{next((i for i, (a, b) in enumerate(zip(plain, was)) if a != b), min(len(plain), len(was)))}")
        print(f"session-start with no pr-lane config is byte-identical to "
              f"{PR_LANE_BASELINE} (0.24.0)")
    else:
        # A shallow clone has no such object. CI checks out with fetch-depth 0
        # for the public gate, so this is the contributor's local case, and the
        # structural check below still runs — it is never nothing.
        print(f"SKIP  0.24.0 baseline comparison: {PR_LANE_BASELINE} is not in "
              f"this checkout's object database")
    # True whatever git can reach: the block contributes ZERO bytes, so the
    # policy text ends where the telemetry line does and the marker is nowhere
    # in it.
    if MARKER in plain or "pr-lane" in plain:
        raise SystemExit(
            "session-start: a project with no .claude/pr-lane.json is being "
            "told about pr-lane — the module must be silent until opted into")

    # With the config, the block is APPENDED: the 0.24.0 text is still a
    # prefix, and everything new is inside a bounded budget.
    withcfg = session_context(_cfg_project)
    if not withcfg.startswith(plain):
        raise SystemExit(
            "session-start: the pr-lane block did not APPEND — the routing "
            "policy is no longer a prefix of the output, so opting in changed "
            "what a session is told about routing")
    block = withcfg[len(plain):]
    lines = block.strip("\n").split("\n")
    if len(lines) > 40:
        raise SystemExit(
            f"session-start: the pr-lane block is {len(lines)} lines, over the "
            f"40-line budget — it shares a context window with the routing "
            f"policy, and there is no rung above 'the model stopped reading'")
    if MARKER not in block:
        raise SystemExit(
            f"session-start: the pr-lane block never carries {MARKER!r} — the "
            f"contract is the one thing a brief has to be able to paste")
    for needle in ("cargo test", "origin/main", "opulent:reviewer",
                   ".claude/agent-memory/**"):
        if needle not in block:
            raise SystemExit(
                f"session-start: the pr-lane block never says {needle!r} — the "
                f"contract's fields come from the config, and a field that "
                f"does not arrive is a lane briefed on this repo's defaults")
    if "${SCRATCHPAD}" in block:
        raise SystemExit(
            "session-start: ${SCRATCHPAD} reached the brief unexpanded — the "
            "lane would take a lock in a directory literally named that")
    print(f"session-start appends the pr-lane block ({len(lines)} lines) when "
          f"the config is present")

    # An invalid config costs the session exactly ONE line, and never the
    # policy. This is the fail-open case: a typo in a JSON file must not be
    # able to turn the routing policy off.
    broken = session_context(_bad_project)
    if not broken.startswith(plain):
        raise SystemExit(
            "session-start: an unparseable pr-lane config changed the routing "
            "policy — the one thing a malformed config must never do")
    extra_lines = [l for l in broken[len(plain):].strip("\n").split("\n") if l]
    if len(extra_lines) != 1 or "pr-lane" not in extra_lines[0]:
        raise SystemExit(
            f"session-start: an unparseable pr-lane config added "
            f"{len(extra_lines)} lines, expected exactly one naming the parse "
            f"error: {extra_lines!r}")
    print("session-start reports an unparseable pr-lane config in one line")
finally:
    for _root in (_none_project, _cfg_project, _bad_project):
        shutil.rmtree(_root, True)

# The loader never raises, whatever is in the file — the property the whole
# fail-open rests on, asserted directly rather than through the hook, because
# the hook's own blanket except would hide a raise here as an allow.
_load = constant(pr_ns, "load", "hooks/pr_lane.py")
_defaults = constant(pr_ns, "DEFAULTS", "hooks/pr_lane.py")
for _junk, _why in (("{ not json", "malformed JSON"),
                    ("[1, 2, 3]", "a list at the top level"),
                    ('{"base": "main"}', "no schema key"),
                    ('{"schema": "pr-lane/99"}', "a schema from the future"),
                    ('{"schema": "pr-lane/1", "pr": 7}', "a section of the wrong type")):
    _root = pr_lane_project(_junk)
    try:
        cfg = _load(_root)
    except Exception as exc:      # the bare catch IS the assertion here
        raise SystemExit(f"hooks/pr_lane.py: load() raised on {_why}: {exc!r}")
    finally:
        shutil.rmtree(_root, True)
    if cfg.data.get("base") != _defaults["base"]:
        raise SystemExit(
            f"hooks/pr_lane.py: load() lost its defaults on {_why} — a config "
            f"it cannot believe must degrade to the defaults, not to nothing")
    if not (cfg.error or cfg.warnings):
        raise SystemExit(
            f"hooks/pr_lane.py: load() accepted {_why} in silence — an ignored "
            f"file the user believes is in force is worse than no file")
print("hooks/pr_lane.py: the config loader degrades to defaults and never raises")

# The renderer, over a fixture ledger. Both forms are pinned: the one line
# session start shows, and the full report /opulent:pr-lane prints.
_summary = constant(pr_ns, "summary", "hooks/pr_lane.py")
_report = constant(pr_ns, "report", "hooks/pr_lane.py")
NOW = datetime.datetime(2026, 9, 7, 12, 0, tzinfo=datetime.timezone.utc)


def at(days):
    return (NOW - datetime.timedelta(days=days)).isoformat(timespec="seconds")


LEDGER_FIXTURE = [
    {"t": at(3), "unit": "w4-a", "event": "unit_defined", "by": "model"},
    {"t": at(2), "unit": "w4-a", "event": "coded", "by": "hook",
     "branch": "feat/w4-a", "sha": "abc1234"},
    {"t": at(2), "unit": "w4-b", "event": "coded", "by": "hook"},
    {"t": at(1), "unit": "w4-b", "event": "reviewed", "by": "hook",
     "verdict": "NOT SAFE"},
    {"t": at(1), "unit": "w4-c", "event": "pr_opened", "by": "hook", "pr": 74},
    {"t": at(1), "unit": "w4-d", "event": "merged", "by": "hook", "pr": 73},
    # Merged nine days ago: on disk, out of the summary. The count has to drop
    # with it, or the line names three units and counts four.
    {"t": at(9), "unit": "w4-old", "event": "merged", "by": "hook", "pr": 70},
]
WANT_SUMMARY = ("pr-lane: 4 units — coded w4-a · reviewed w4-b · "
                "open PRs #74 · merged #73 (last 7 days)")
got_summary = _summary(LEDGER_FIXTURE, now=NOW)
if got_summary != WANT_SUMMARY:
    raise SystemExit(f"hooks/pr_lane.py: the ledger summary rendered\n  "
                     f"{got_summary!r}\nexpected\n  {WANT_SUMMARY!r}")
if _summary([], now=NOW) != "pr-lane: ledger empty":
    raise SystemExit("hooks/pr_lane.py: an empty ledger must render "
                     "'pr-lane: ledger empty', not a zero-count line")
_root = pr_lane_project(VALID_CONFIG)
try:
    os.makedirs(os.path.join(_root, ".claude", "pr-lane"))
    with open(os.path.join(_root, ".claude", "pr-lane", "ledger.jsonl"), "w",
              encoding="utf-8") as fh:
        for rec in LEDGER_FIXTURE:
            fh.write(json.dumps(rec) + "\n")
        fh.write("{ torn line\n")       # a hand-edited line is not a record
        fh.write("\n")
    full = _report(_root, now=NOW)
finally:
    shutil.rmtree(_root, True)
for needle in ("w4-a", "coded, no review recorded", "NOT SAFE",
               "no CI verdict recorded", WANT_SUMMARY, "parsed"):
    if needle not in full:
        raise SystemExit(
            f"hooks/pr_lane.py: the full report never says {needle!r} — "
            f"/opulent:pr-lane exists to say which units are blocked and on "
            f"what:\n{full}")
print("hooks/pr_lane.py: the ledger renderer pins both forms over a fixture")

# A command may not name a lane that does not exist: `/opulent:pr-lane` is a
# surface like the policy and the doctor, and a lane named there but missing
# from agents/ is a delegation the session cannot make.
PR_LANE_CMD = "commands/pr-lane.md"
with open(os.path.join(REPO, "commands", "pr-lane.md"), encoding="utf-8") as fh:
    pr_lane_cmd = fh.read()
if not pr_lane_cmd.startswith("---\ndescription:"):
    raise SystemExit(f"{PR_LANE_CMD}: no description frontmatter — a command "
                     f"without one is unlistable")
for named in sorted(set(re.findall(r"`opulent:([\w.-]+)`", pr_lane_cmd))):
    if named not in AGENTS:
        raise SystemExit(
            f"{PR_LANE_CMD}: names lane `opulent:{named}`, which is not "
            f"registered in agents/ — the roster is {', '.join(sorted(AGENTS))}")
print(f"{PR_LANE_CMD} names no lane outside the roster")

# The hook CONFIG, pinned — because nothing else in this repo goes through it.
# hook_selftest.py runs route-models.py directly, so hooks.json can lose an
# entry, misspell an event or drift its matcher and every suite stays green
# while the harness quietly stops calling the hook at all. The PostToolUse
# entry is the one that would fail invisibly: denials keep working, the doctor
# canary still reports LIVE, and the only symptom is a record that never grows
# again — which is precisely the silent gap this plugin exists to close.
MATCHER = "Edit|Write|NotebookEdit|MultiEdit|Bash|PowerShell|Task|Agent"
HOOKS_JSON = os.path.join("hooks", "hooks.json")
with open(os.path.join(REPO, HOOKS_JSON), encoding="utf-8") as f:
    hooks_cfg = json.load(f).get("hooks") or {}


def sole_entry(event):
    """The one matcher entry registered for `event`, and its one command.
    Arity is asserted, not indexed past: a second entry appended beside the
    first is a second invocation of the same hook, and "the first one looks
    right" is how that goes unnoticed."""
    entries = hooks_cfg.get(event)
    if not isinstance(entries, list) or len(entries) != 1:
        raise SystemExit(
            f"{HOOKS_JSON}: {event} must register exactly one entry, found "
            f"{len(entries) if isinstance(entries, list) else entries!r}")
    commands = [h.get("command") for h in entries[0].get("hooks") or []]
    if len(commands) != 1 or not commands[0]:
        raise SystemExit(
            f"{HOOKS_JSON}: {event} must invoke exactly one command, found "
            f"{commands!r}")
    return entries[0], commands[0]


pre_entry, pre_cmd = sole_entry("PreToolUse")
post_entry, post_cmd = sole_entry("PostToolUse")
for _event, _entry in (("PreToolUse", pre_entry), ("PostToolUse", post_entry)):
    if _entry.get("matcher") != MATCHER:
        raise SystemExit(
            f"{HOOKS_JSON}: the {_event} matcher is {_entry.get('matcher')!r}, "
            f"expected {MATCHER!r} — the two events must watch the same tools, "
            f"or a call gets decided on one and recorded on neither")
if pre_cmd != post_cmd:
    raise SystemExit(
        f"{HOOKS_JSON}: PreToolUse and PostToolUse invoke different commands — "
        f"one script serves both halves of a call, and a divergence here is two "
        f"hooks wearing one name:\n  pre:  {pre_cmd}\n  post: {post_cmd}")
if "hooks/route-models.py" not in pre_cmd:
    raise SystemExit(
        f"{HOOKS_JSON}: the tool-use events do not invoke hooks/route-models.py: "
        f"{pre_cmd!r}")
if "hooks/session-start.py" not in sole_entry("SessionStart")[1]:
    raise SystemExit(
        f"{HOOKS_JSON}: SessionStart does not invoke hooks/session-start.py")

# ... and the split those two entries exist to serve, driven for real. The
# config can be perfect while the script ignores the event name, which would
# put the record back on PreToolUse where a denial from another plugin's hook
# turns every line into a phantom.
ROUTE = os.path.join(REPO, "hooks", "route-models.py")
# Anchored at HOME rather than at REPO: the hook does not record writes under
# the system temp dir, and CI checked out into one would otherwise "prove" the
# recorder silent by feeding it a scratch path.
EDITED = os.path.join(os.path.expanduser("~"), "opulent-ci-probe", "app.py")


def route_lines(event):
    """(stdout, log entries) from one run of the routing hook on `event`."""
    body = {"hook_event_name": event, "tool_name": "Edit",
            "tool_input": {"file_path": EDITED},
            "cwd": os.path.dirname(EDITED)}
    if event == "PostToolUse":
        body["tool_response"] = {"success": True}
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
        route_log = fh.name
    try:
        proc = subprocess.run(
            [sys.executable, ROUTE], input=json.dumps(body), capture_output=True,
            text=True, timeout=30, env=dict(os.environ, OPULENT_LOG=route_log))
        if proc.returncode != 0:
            raise SystemExit(
                f"hooks/route-models.py exited {proc.returncode} on {event}: "
                f"{proc.stderr.strip()}")
        with open(route_log, encoding="utf-8") as fh:
            entries = [json.loads(line) for line in fh if line.strip()]
    finally:
        os.unlink(route_log)
    return proc.stdout.strip(), entries


post_out, post_entries = route_lines("PostToolUse")
if post_out:
    raise SystemExit(
        f"hooks/route-models.py: PostToolUse produced output — the recording "
        f"half decides nothing and must stay silent: {post_out!r}")
if [e.get("event") for e in post_entries] != ["edit"]:
    raise SystemExit(
        f"hooks/route-models.py: an ordinary edit at PostToolUse recorded "
        f"{[e.get('event') for e in post_entries] or 'nothing'}, expected one "
        f"`edit` line — the record lives on this event and nowhere else")
pre_out, pre_entries = route_lines("PreToolUse")
if pre_entries:
    raise SystemExit(
        f"hooks/route-models.py: the same edit at PreToolUse recorded "
        f"{[e.get('event') for e in pre_entries]} — the deciding half writes a "
        f"line only when it is the one refusing, or the log counts attempts "
        f"another plugin's hook was still free to deny")
print("hooks.json: PreToolUse decides, PostToolUse records")

# The description users read in /plugin comes from the marketplace entry; the
# manifest carries its own copy. Two hand-maintained copies of one sentence
# drift, and the drifted one is whichever copy the reader happens to see.
with open(os.path.join(REPO, ".claude-plugin", "plugin.json"), encoding="utf-8") as f:
    _plug = json.load(f)
with open(os.path.join(REPO, ".claude-plugin", "marketplace.json"), encoding="utf-8") as f:
    _mkt = json.load(f)
for entry in _mkt.get("plugins", []):
    if entry.get("name") == _plug.get("name") and \
            entry.get("description") != _plug.get("description"):
        raise SystemExit(
            f"marketplace description for {_plug.get('name')!r} has drifted "
            f"from plugin.json's — the two must stay one sentence")
print("marketplace and plugin descriptions match")

print("\nall CI checks passed")
