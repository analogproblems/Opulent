#!/usr/bin/env python3
"""Shell-agnostic CI checks: every marketplace member's manifest parses as
JSON, agrees with its marketplace entry, and names a version CHANGELOG.md has
actually released; and the session-start hook emits valid JSON. The member
list is derived from marketplace.json, so a plugin added to the marketplace is
checked here with no edit to this file. Runs identically under PowerShell,
cmd, or bash — no pipes or heredocs required."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile

from marketplace_members import MARKETPLACE, REPO, members

with open(os.path.join(REPO, MARKETPLACE)) as f:
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
with open(os.path.join(REPO, CHANGELOG)) as f:
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
    with open(os.path.join(REPO, m.manifest)) as f:
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

# The coder lane is a ladder: one charter, one model, and copies of the file
# that differ only in the effort rung they sit on. Duplication that nothing
# holds in place drifts silently — a rung keeps the charter it was copied from
# only for as long as someone remembers to edit every file. This is that
# someone, for the whole ladder.
ORIGINAL, HIGH_RUNG = "agents/coder.md", "agents/coder-high.md"
LADDER = {"coder-high": "high", "coder-max": "max", "coder-lite": "medium"}
RUNG_FIELDS = {"name", "description", "effort"}


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
    ns = {"__name__": "_hook_under_test"}
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
# The rung every other rung is measured from, pinned rather than merely
# inherited: Anthropic's guidance puts coding and agentic work at xhigh, and a
# default that drifted back to max would move the whole ladder with it.
if front.get("effort") != "xhigh":
    raise SystemExit(
        f"{ORIGINAL}: effort is {front.get('effort')!r}, expected 'xhigh' — "
        f"the ladder's default rung is xhigh, Anthropic's recommended coding "
        f"setting")
# The rungs are checked against THIS body, which makes the sync mutual and
# anchored to nothing: four empty files agree with each other perfectly. So the
# file every rung is measured from is pinned to the charter it carries, and
# "all four gutted" can no longer satisfy the sync.
CHARTER = b"implementation specialist"
if CHARTER not in body:
    raise SystemExit(
        f"{ORIGINAL}: the body never says {CHARTER.decode()!r} — every rung is "
        f"synced to this file, so a charter emptied here would pass the sync "
        f"and leave the whole ladder briefing nobody")
ladder_front = {}
for variant, rung in sorted(LADDER.items()):
    path = f"agents/{variant}.md"
    v_front, v_body = agent_parts(path)
    ladder_front[variant] = v_front
    if v_body != body:
        raise SystemExit(
            f"{path}: body differs from {ORIGINAL} — every rung of the coder "
            f"ladder carries the same charter verbatim and may differ only in "
            f"frontmatter")
    drift = sorted(k for k in set(front) | set(v_front)
                   if front.get(k) != v_front.get(k))
    if set(drift) - RUNG_FIELDS:
        raise SystemExit(
            f"{path}: frontmatter differs from {ORIGINAL} in {', '.join(drift)} — "
            f"only {', '.join(sorted(RUNG_FIELDS))} may differ")
    if v_front.get("name") != variant:
        raise SystemExit(
            f"{path}: name is {v_front.get('name')!r}, expected {variant!r} — "
            f"the routing hook and the policy spell that name out by hand")
    # Permitted to differ is not the same as required to differ. A rung at
    # coder's own effort is byte-identical to it in every way that matters and
    # saves (or buys) nothing — the whole point of the file is where it sits.
    if v_front.get("effort") != rung:
        raise SystemExit(
            f"{path}: effort is {v_front.get('effort')!r}, expected {rung!r} — "
            f"that is the rung this lane exists to occupy")
    # No separate "effort must DIFFER from coder.md" check: the xhigh pin above
    # and the per-rung pin here name different values, so divergence is already
    # guaranteed and a check for it could never fire.
    print(f"ladder rung in sync with {ORIGINAL}: {path} ({', '.join(drift)} differ)")
# Eco caps the ladder at its high rung, and the hook spells that rung's name
# out by hand; if the file it points at were renamed, eco mode would deny the
# coder lane and offer a lane that does not exist. Read from the hook's own
# constant, not retyped here.
eco_twin = constant(routing, "ECO_TWIN", "hooks/route-models.py")
if eco_twin != "opulent:" + ladder_front["coder-high"]["name"]:
    raise SystemExit(
        f"hooks/route-models.py: ECO_TWIN is {eco_twin!r}, but {HIGH_RUNG} declares "
        f"name {ladder_front['coder-high']['name']!r} — the redirect names a lane "
        f"that is not there")
print(f"routing hook redirects to a lane that exists: {eco_twin}")

hook = os.path.join(REPO, "hooks", "session-start.py")

# The eco swap is a str.replace of one exact line, so a reworded CONTEXT turns
# it into a silent no-op. Checked at the source, against the hook's own
# constants: downstream the no-op is nearly invisible, because the eco note
# names the high rung too.
CONTEXT = constant(policy_ns, "CONTEXT", "hooks/session-start.py")
CODER_LINE = constant(policy_ns, "CODER_LINE", "hooks/session-start.py")
if CODER_LINE not in CONTEXT:
    raise SystemExit(
        "hooks/session-start.py: CODER_LINE is not a line of CONTEXT, so the "
        "eco substitution replaces nothing and silently does nothing")
# The paragraph that teaches the ladder is swapped the same way — but CONTEXT
# SPLICES this constant (`""" + LADDER_PARA + """`) rather than repeating its
# text, so today this check cannot fail, and it is weaker than CODER_LINE's
# above for exactly that reason: that line is hand-duplicated and this one is
# not. It stays as a tripwire on the day someone inlines the paragraph for
# readability — from then on the copy is free to drift, and a drifted copy
# leaves eco mode advertising the rungs it is denying.
LADDER_PARA = constant(policy_ns, "LADDER_PARA", "hooks/session-start.py")
if LADDER_PARA not in CONTEXT:
    raise SystemExit(
        "hooks/session-start.py: LADDER_PARA is not part of CONTEXT, so the "
        "eco substitution replaces nothing and silently does nothing")
# Names AND efforts, paired: a paragraph that advertised coder-max as (medium)
# and coder-lite as (max) names every rung and teaches the session to escalate
# downwards. Both halves come from LADDER rather than being retyped here, so
# the pair cannot agree with itself while disagreeing with the files, and a
# rung added to the ladder is required in the paragraph the day it is added.
# The default rung is not in this loop — CODER_LINE pins it, and in this
# paragraph its name and effort are split across a line break.
for variant, rung in sorted(LADDER.items()):
    pair = f"`opulent:{variant}` ({rung})"
    if pair not in LADDER_PARA:
        raise SystemExit(
            f"hooks/session-start.py: LADDER_PARA does not say {pair!r} — the "
            f"paragraph that teaches the ladder names every rung beside the "
            f"default, each at the effort agents/{variant}.md actually runs at")
# What eco substitutes IN has to teach the same ladder, capped: the two rungs
# it denies and the rung it sends them to. A stub would substitute cleanly and
# say nothing. Backticked, because bare `opulent:coder` is a substring of the
# three lanes beside it and would be satisfied by naming none of them.
ECO_LADDER_PARA = constant(policy_ns, "ECO_LADDER_PARA", "hooks/session-start.py")
for lane in ("`opulent:coder`", "`opulent:coder-max`", "`opulent:coder-high`"):
    if lane not in ECO_LADDER_PARA:
        raise SystemExit(
            f"hooks/session-start.py: ECO_LADDER_PARA never names {lane} — the "
            f"capped paragraph must say which rungs eco denies and where it "
            f"sends them")
print("session-start's eco substitutions have something to substitute")

# The lane roster, pinned across every surface that names it. Derived from
# agents/*.md frontmatter, so a renamed or deleted lane fails here instead of
# leaving a policy, a doctor and a README pointing at an agent that is not
# registered — the exact failure the ECO_TWIN block guards, previously
# unguarded for the other six. Names and models are pinned, not prose.
AGENTS = {}
for fn in sorted(os.listdir(os.path.join(REPO, "agents"))):
    if not fn.endswith(".md"):
        continue
    fr, _ = agent_parts(os.path.join("agents", fn))
    if not fr.get("name") or not fr.get("model"):
        raise SystemExit(f"agents/{fn}: frontmatter must carry name and model")
    AGENTS[fr["name"]] = fr["model"].strip().lower()
if len(AGENTS) != 9:
    raise SystemExit(
        f"agents/: expected the nine lane definitions, found {len(AGENTS)}: "
        f"{', '.join(sorted(AGENTS))}")
PRIMARY = sorted(n for n in AGENTS if n not in LADDER)
if len(PRIMARY) != 6:
    raise SystemExit(f"agents/: expected six primary lanes beside the coder "
                     f"ladder variants, found {', '.join(PRIMARY)}")
with open(os.path.join(REPO, "commands", "doctor.md"), encoding="utf-8") as fh:
    doctor_text = fh.read()
with open(os.path.join(REPO, "README.md"), encoding="utf-8") as fh:
    readme_text = fh.read()
# Matched WITH its backticks, which is how all three surfaces render a lane
# name. Bare, `opulent:coder` is a substring of the three other rungs, so the
# default rung could be deleted from any of these documents and go on being
# "found" by the coder-max row sitting beside it.
for name in PRIMARY:
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
      + ", ".join(PRIMARY))

# What eco caps, read from the hook rather than retyped — a constant CI retypes
# is a constant CI cannot vouch for. Here CI reads the hook's own tuple and pins
# the policy to it: eco caps the ladder's default rung and the one above it, and
# nothing else. An entry added would deny a lane the policy still advertises —
# eco denying every exploration is one name away — and an entry removed would
# leave a rung the doctor calls capped spawnable. Every entry is also pinned to
# a registered lane, plugin-qualified: the redirect logs its detail by slicing
# "opulent:" off this name, and that slice's precondition is now CI-enforced.
ECO_LANES = constant(routing, "ECO_LANES", "hooks/route-models.py")
if tuple(ECO_LANES) != ("opulent:coder", "opulent:coder-max"):
    raise SystemExit(
        f"hooks/route-models.py: ECO_LANES is {tuple(ECO_LANES)!r} — eco caps "
        f"the ladder's default rung and the rung above it, and no other lane")
for lane in ECO_LANES:
    if not lane.startswith("opulent:") or lane[len("opulent:"):] not in AGENTS:
        raise SystemExit(
            f"hooks/route-models.py: ECO_LANES names {lane!r}, which is not an "
            f"`opulent:`-qualified lane registered in agents/ — the redirect's "
            f"log detail slices that prefix off and would record a nonsense rung")
print("eco caps exactly the lanes it says it caps: " + ", ".join(ECO_LANES))


def lane_line(context, where):
    """The policy's implementation-lane line. Asserting on the whole document
    is self-satisfying — the eco note names `opulent:coder-high` as well, so a
    substitution that quietly did nothing would still leave the string in the
    text. The lane line is the thing the session actually routes on."""
    for line in context.split("\n"):
        if line.startswith("- Complex implementation"):
            return line
    raise SystemExit(f"{where}: no '- Complex implementation' lane line in the policy")


# Whatever the shell has set, the plain policy is checked without the dial.
plain_env = dict(os.environ)
plain_env.pop("OPULENT_ECO", None)
out = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                     timeout=30, env=plain_env)
if out.returncode != 0:
    print(out.stderr, file=sys.stderr)
    raise SystemExit(f"session-start.py exited {out.returncode}")
payload = json.loads(out.stdout)
context = payload["hookSpecificOutput"]["additionalContext"]
plain_lane = lane_line(context, "session-start")
# Delimited, because `"opulent:coder" in ...` is a substring of all three other
# rungs: an undelimited needle is satisfied by a plain-session lane line
# pointing at `opulent:coder-max`, which is the most expensive rung in the
# cheapest circumstance — the worst failure a cost-routing plugin has. The
# policy renders every lane name in backticks, so between them the string names
# the default rung and nothing else.
if "`opulent:coder`" not in plain_lane:
    raise SystemExit(
        f"session-start: the implementation lane is not the ladder's default "
        f"rung `opulent:coder`: {plain_lane!r}")
# Undelimited on purpose, which is the strict direction for a NEGATIVE check:
# any spelling of the rung eco caps at, in a session that asked for no cap, is
# the failure this is watching for.
if "opulent:coder-high" in plain_lane:
    raise SystemExit(
        f"session-start: OPULENT_ECO is unset but the implementation lane is "
        f"the rung eco caps at: {plain_lane!r}")
print("session-start emits valid JSON with routing policy")

# Under OPULENT_ECO the lane line itself has to name the high rung: a policy
# still pointing at `opulent:coder` would aim the session at the one lane the
# routing hook is denying, and every implementation task would open on a
# refusal.
eco = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                     timeout=30, env=dict(plain_env, OPULENT_ECO="1"))
if eco.returncode != 0:
    print(eco.stderr, file=sys.stderr)
    raise SystemExit(f"session-start.py exited {eco.returncode} under OPULENT_ECO")
eco_context = json.loads(eco.stdout)["hookSpecificOutput"]["additionalContext"]
eco_lane = lane_line(eco_context, "session-start under OPULENT_ECO")
if "`opulent:coder-high`" not in eco_lane:
    raise SystemExit(
        f"session-start: OPULENT_ECO is set but the implementation lane is "
        f"still {eco_lane!r}")
# Eco mode caps the ladder, not one lane, so the whole ladder paragraph is
# swapped for its capped version. Checked in BOTH directions, because either
# half alone is satisfiable by accident: a needle like `opulent:coder-max`
# arrives from ECO_NOTE and from the un-swapped paragraph whether or not the
# substitution ran, so the capped paragraph must be present AND the un-capped
# one absent. Un-capped and surviving is the live failure: the session reads
# "escalate to `opulent:coder-max`" and finds out by being refused.
if ECO_LADDER_PARA not in eco_context:
    raise SystemExit(
        "session-start: OPULENT_ECO is set but the policy does not carry "
        "ECO_LADDER_PARA — the ladder paragraph was never swapped for the "
        "capped version of itself")
if LADDER_PARA in eco_context:
    raise SystemExit(
        "session-start: OPULENT_ECO is set but the un-capped LADDER_PARA is "
        "still in the policy — the session is being taught to escalate to the "
        "rungs the routing hook denies")
print("session-start names the eco lane and swaps in the capped ladder "
      "under OPULENT_ECO")

# Telemetry vocabulary: the session opens with a summary of the routing log,
# and an event type it cannot count is a lane change nobody can audit.
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    fh.write('{"t": "2026-08-06T00:00:00+00:00", "event": "delegate", "detail": "opulent:coder-high"}\n')
    fh.write('{"t": "2026-08-06T00:00:01+00:00", "event": "eco", "detail": "eco:coder"}\n')
    telemetry_log = fh.name
try:
    telem = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                           timeout=30, env=dict(plain_env, OPULENT_LOG=telemetry_log))
    summary = json.loads(telem.stdout)["hookSpecificOutput"]["additionalContext"]
finally:
    os.unlink(telemetry_log)
if "1 eco redirects" not in summary:
    raise SystemExit(
        "session-start: an `eco` event in the routing log is not reported in the "
        "activity summary")
# The redirect has its own event precisely so it stays out of this count.
if "0 denials" not in summary:
    raise SystemExit(
        "session-start: the eco redirect is being counted as a denial — that is "
        "the counter it was given its own event to keep honest")
print("session-start reports eco redirects without inflating the denial count")

# The commonest post-0.9.0 session shape is edits and test runs with no
# denial at all; an activity line that omitted them reported that session as
# silence. Removals and unparsed commands are report-when-seen, like probes.
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    fh.write('{"t": "2026-08-13T00:00:00+00:00", "event": "edit", "detail": "/p/app.py"}\n')
    fh.write('{"t": "2026-08-13T00:00:01+00:00", "event": "test", "detail": "pytest -q"}\n')
    fh.write('{"t": "2026-08-13T00:00:02+00:00", "event": "remove", "detail": "/p/old.py"}\n')
    fh.write('{"t": "2026-08-13T00:00:03+00:00", "event": "unparsed", "detail": "echo x"}\n')
    activity_log = fh.name
try:
    act = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                         timeout=30, env=dict(plain_env, OPULENT_LOG=activity_log))
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

# A fresh install has an empty (or absent) log; the model must still learn
# the log path, or the record is unfindable exactly when it matters most.
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    empty_log = fh.name
try:
    quiet = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                           timeout=30, env=dict(plain_env, OPULENT_LOG=empty_log))
    quiet_ctx = json.loads(quiet.stdout)["hookSpecificOutput"]["additionalContext"]
finally:
    os.unlink(empty_log)
if "No routing activity recorded yet" not in quiet_ctx or empty_log not in quiet_ctx:
    raise SystemExit(
        "session-start: a session with an empty log must still say so and "
        "name the log path")
print("session-start names the log path even before any activity")

# Under OPULENT_OFF the note says "no routing log is being written"; printing
# activity counts (or the no-activity line) directly under it would contradict
# it on the same screen. The policy alone, plus the OFF note, is the contract.
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    fh.write('{"t": "2026-08-13T00:00:00+00:00", "event": "edit", "detail": "/p/app.py"}\n')
    off_log = fh.name
try:
    off = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                         timeout=30,
                         env=dict(plain_env, OPULENT_LOG=off_log, OPULENT_OFF="1"))
    off_ctx = json.loads(off.stdout)["hookSpecificOutput"]["additionalContext"]
finally:
    os.unlink(off_log)
if "Enforcement is OFF" not in off_ctx:
    raise SystemExit("session-start: OPULENT_OFF context is missing the OFF note")
if "routing activity" in off_ctx:
    raise SystemExit(
        "session-start: OPULENT_OFF says no log is written, but an activity "
        "line prints beneath it — the two must not contradict on one screen")
print("session-start suppresses the activity line under OPULENT_OFF")

# The description users read in /plugin comes from the marketplace entry; the
# manifest carries its own copy. Two hand-maintained copies of one sentence
# drift, and the drifted one is whichever copy the reader happens to see.
with open(os.path.join(REPO, ".claude-plugin", "plugin.json")) as f:
    _plug = json.load(f)
with open(os.path.join(REPO, ".claude-plugin", "marketplace.json")) as f:
    _mkt = json.load(f)
for entry in _mkt.get("plugins", []):
    if entry.get("name") == _plug.get("name") and \
            entry.get("description") != _plug.get("description"):
        raise SystemExit(
            f"marketplace description for {_plug.get('name')!r} has drifted "
            f"from plugin.json's — the two must stay one sentence")
print("marketplace and plugin descriptions match")

print("\nall CI checks passed")
