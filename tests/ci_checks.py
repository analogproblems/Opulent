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
    if logged[0][0] > ver:
        raise SystemExit(
            f"{CHANGELOG}: newest {m.name} entry is {logged[0][1]}, ahead of "
            f"{manifest['version']} in {m.manifest} — the manifest was not bumped")
    print(f"released in {CHANGELOG}: {m.name} {manifest['version']}")

# The eco twin is a deliberate copy: same model, same charter, one effort rung
# down. Duplication that nothing holds in place drifts silently — the twin
# keeps the charter it was copied from only for as long as someone remembers
# to edit both files. This is that someone.
ORIGINAL, TWIN = "agents/coder.md", "agents/coder-eco.md"
TWIN_FIELDS = {"name", "description", "effort"}


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
twin_front, twin_body = agent_parts(TWIN)
if twin_body != body:
    raise SystemExit(
        f"{TWIN}: body differs from {ORIGINAL} — the eco twin carries the same "
        f"charter verbatim and may differ only in frontmatter")
drift = sorted(k for k in set(front) | set(twin_front)
               if front.get(k) != twin_front.get(k))
if set(drift) - TWIN_FIELDS:
    raise SystemExit(
        f"{TWIN}: frontmatter differs from {ORIGINAL} in {', '.join(drift)} — "
        f"only {', '.join(sorted(TWIN_FIELDS))} may differ")
if twin_front.get("name") != "coder-eco":
    raise SystemExit(
        f"{TWIN}: name is {twin_front.get('name')!r}, expected 'coder-eco' — "
        f"the routing hook redirects to that name by hand")
# Permitted to differ is not the same as required to differ. A twin at
# effort: max is byte-identical to coder in every way that matters and saves
# nothing — the whole point of the file is the rung it sits on.
if twin_front.get("effort") != "xhigh":
    raise SystemExit(
        f"{TWIN}: effort is {twin_front.get('effort')!r}, expected 'xhigh' — "
        f"the eco twin is the coder charter one rung down")
if "effort" not in drift:
    raise SystemExit(
        f"{TWIN}: effort is identical to {ORIGINAL} ({front.get('effort')!r}) — "
        f"a twin that spends the same is not an eco lane")
# The hook redirects to a name it spells out by hand; if the file it points at
# were renamed, eco mode would deny the coder lane and offer a lane that does
# not exist. Read from the hook's own constant, not retyped here.
eco_twin = constant(routing, "ECO_TWIN", "hooks/route-models.py")
if eco_twin != "opulent:" + twin_front["name"]:
    raise SystemExit(
        f"hooks/route-models.py: ECO_TWIN is {eco_twin!r}, but {TWIN} declares "
        f"name {twin_front['name']!r} — the redirect names a lane that is not there")
print(f"eco twin in sync with {ORIGINAL}: {TWIN} ({', '.join(drift)} differ)")
print(f"routing hook redirects to a lane that exists: {eco_twin}")

hook = os.path.join(REPO, "hooks", "session-start.py")

# The eco swap is a str.replace of one exact line, so a reworded CONTEXT turns
# it into a silent no-op. Checked at the source, against the hook's own
# constants: downstream the no-op is nearly invisible, because the eco note
# names the twin too.
CONTEXT = constant(policy_ns, "CONTEXT", "hooks/session-start.py")
CODER_LINE = constant(policy_ns, "CODER_LINE", "hooks/session-start.py")
if CODER_LINE not in CONTEXT:
    raise SystemExit(
        "hooks/session-start.py: CODER_LINE is not a line of CONTEXT, so the "
        "eco substitution replaces nothing and silently does nothing")
print("session-start's eco substitution has something to substitute")


def lane_line(context, where):
    """The policy's implementation-lane line. Asserting on the whole document
    is self-satisfying — the eco note names `opulent:coder-eco` as well, so a
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
# `"opulent:coder" in ...` is vacuous on its own — it is a substring of
# `opulent:coder-eco`. The pair is what makes the plain policy plain.
if "opulent:coder" not in plain_lane:
    raise SystemExit(f"session-start: lane line names no coder lane: {plain_lane!r}")
if "opulent:coder-eco" in plain_lane:
    raise SystemExit(
        f"session-start: OPULENT_ECO is unset but the implementation lane is "
        f"the eco twin: {plain_lane!r}")
print("session-start emits valid JSON with routing policy")

# Under OPULENT_ECO the lane line itself has to name the twin: a policy still
# pointing at `opulent:coder` would aim the session at the one lane the
# routing hook is denying, and every implementation task would open on a
# refusal.
eco = subprocess.run([sys.executable, hook], capture_output=True, text=True,
                     timeout=30, env=dict(plain_env, OPULENT_ECO="1"))
if eco.returncode != 0:
    print(eco.stderr, file=sys.stderr)
    raise SystemExit(f"session-start.py exited {eco.returncode} under OPULENT_ECO")
eco_context = json.loads(eco.stdout)["hookSpecificOutput"]["additionalContext"]
eco_lane = lane_line(eco_context, "session-start under OPULENT_ECO")
if "opulent:coder-eco" not in eco_lane:
    raise SystemExit(
        f"session-start: OPULENT_ECO is set but the implementation lane is "
        f"still {eco_lane!r}")
print("session-start names the eco lane under OPULENT_ECO")

# Telemetry vocabulary: the session opens with a summary of the routing log,
# and an event type it cannot count is a lane change nobody can audit.
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
    fh.write('{"t": "2026-08-06T00:00:00+00:00", "event": "delegate", "detail": "opulent:coder-eco"}\n')
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

print("\nall CI checks passed")
