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

# Implementation is two files carrying one charter, differing only in the
# effort they run at. Duplication that nothing holds in place drifts silently —
# the variant keeps the charter it was copied from only for as long as someone
# remembers to edit both files. This is that someone.
ORIGINAL = "agents/coder.md"
VARIANTS = {"coder-max": "xhigh"}
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
# The default, pinned rather than merely inherited. Anthropic's published
# guidance puts coding at xhigh; this plugin deliberately sits one step below
# it as of 0.17.0, on the same reasoning the policy gives for not defaulting to
# max — effort above the work returns worse code. The pin exists so that
# departure stays a decision somebody made, rather than drift.
if front.get("effort") != "high":
    raise SystemExit(
        f"{ORIGINAL}: effort is {front.get('effort')!r}, expected 'high' — "
        f"the default implementation lane sits one step below Anthropic's "
        f"published xhigh coding recommendation, deliberately, since 0.17.0")
# The variant is checked against THIS body, which makes the sync mutual and
# anchored to nothing: two empty files agree with each other perfectly. So the
# file the variant is measured from is pinned to the charter it carries, and
# "both gutted" can no longer satisfy the sync.
CHARTER = b"implementation specialist"
if CHARTER not in body:
    raise SystemExit(
        f"{ORIGINAL}: the body never says {CHARTER.decode()!r} — the variant is "
        f"synced to this file, so a charter emptied here would pass the sync "
        f"and leave both lanes briefing nobody")
for variant, rung in sorted(VARIANTS.items()):
    path = f"agents/{variant}.md"
    v_front, v_body = agent_parts(path)
    if v_body != body:
        raise SystemExit(
            f"{path}: body differs from {ORIGINAL} — both implementation lanes "
            f"carry the same charter verbatim and may differ only in frontmatter")
    drift = sorted(k for k in set(front) | set(v_front)
                   if front.get(k) != v_front.get(k))
    if set(drift) - RUNG_FIELDS:
        raise SystemExit(
            f"{path}: frontmatter differs from {ORIGINAL} in {', '.join(drift)} — "
            f"only {', '.join(sorted(RUNG_FIELDS))} may differ")
    if v_front.get("name") != variant:
        raise SystemExit(
            f"{path}: name is {v_front.get('name')!r}, expected {variant!r} — "
            f"the policy spells that name out by hand")
    # Permitted to differ is not the same as required to differ. A variant at
    # coder's own effort is byte-identical to it in every way that matters and
    # buys nothing — the whole point of the file is the effort it sits at.
    if v_front.get("effort") != rung:
        raise SystemExit(
            f"{path}: effort is {v_front.get('effort')!r}, expected {rung!r} — "
            f"that is the effort this lane exists to occupy")
    print(f"charter in sync with {ORIGINAL}: {path} ({', '.join(drift)} differ)")

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
# lists. Opus and Sonnet are the whole matrix now: two Opus coder lanes and two
# Sonnet support lanes, with documentation and UI verification kept by the
# architect rather than delegated at all.
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
# name. Bare, `opulent:coder` is a substring of `opulent:coder-max`, so the
# default lane could be deleted from any of these documents and go on being
# "found" by the coder-max row sitting beside it.
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
# Delimited, because `"opulent:coder" in ...` is a substring of coder-max: an
# undelimited needle is satisfied by a lane line pointing at `opulent:coder-max`,
# which is the most expensive lane in the cheapest circumstance — the worst
# failure a cost-routing plugin has.
if "`opulent:coder`" not in plain_lane:
    raise SystemExit(
        f"session-start: the implementation lane is not `opulent:coder`: "
        f"{plain_lane!r}")
if "opulent:coder-max" in plain_lane:
    raise SystemExit(
        f"session-start: the default implementation lane is the hazard lane: "
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
