#!/usr/bin/env python3
"""pr-lane, phase 1: the config, the brief contract, the ledger, the renderer.

Opt-in, and inert until opted in. Everything here is reached only after
`<project>/.claude/pr-lane.json` has been found on disk, so a project without
that file gets the 0.24.0 hooks byte for byte — no policy text, no ledger
lines, no new denials. That property is pinned by the suites, and it is why
this is a separate module rather than another constant in session-start.py:
a constant appended to CONTEXT cannot be absent, and this has to be.

Fail-open, like the hooks that import it. A malformed config, an unwritable
ledger directory, an agent report in a shape nobody anticipated — each of
them degrades to "no pr-lane" and none of them raises. The worst thing this
file could do is cost a session its routing policy, so every entry point is
wrapped and every parser returns None rather than guessing.

Nothing here decides anything. The routing hook still denies exactly what it
denied before plus the config file itself; the ledger is a record, and a
record that could refuse a call would be a gate wearing a record's name.

Also runnable — `python pr_lane.py [project-dir]` prints the full report,
which is what commands/pr-lane.md invokes.
"""
import copy
import datetime
import json
import os
import re
import sys
import tempfile

SCHEMA = "pr-lane/1"
# The marker line. A brief that carries it was written from the contract, and
# that is the only thing separating a pr-lane unit from any other delegation:
# the hook records `coded` off this string and nothing else.
MARKER = "PR-LANE CONTRACT v1"
CONFIG_NAME = "pr-lane.json"
LEDGER_NAME = "ledger.jsonl"
CLAUDE_DIR = ".claude"
LEDGER_DIR = "pr-lane"

# The event vocabulary, which is the LEDGER's and never the routing log's. The
# two files stay separate on purpose: the routing log answers "what did the
# main loop touch", the ledger answers "where is each unit", and a shared file
# would make either question unanswerable without filtering the other's rows.
EVENTS = ("unit_defined", "coded", "reviewed", "pr_opened", "ci", "merged",
          "handed_off")

# Lanes whose return can mean "this unit is coded". The reviewer is not here:
# it is read from `review.provider`, because that key exists to be swapped.
CODING_LANES = ("opulent:coder", "opulent:mechanic")

MERGE_MODES = ("architect", "user", "auto")
MERGE_METHODS = ("squash", "rebase", "merge")

# Every key optional except `schema`. A section the file omits renders as
# "(not configured)" in the contract rather than as a plausible-looking
# default: a lane told to run a check nobody configured would run the wrong
# one, and an empty slot it can see is cheaper than a guess it cannot.
DEFAULTS = {
    "base": "main",
    "commands": {"step_zero": "", "check": "", "test": "", "lint": ""},
    "shared_machine": {"lock_dir": "", "target_dir": "",
                       "max_lanes_building": 2},
    "git": {"trailer": "", "user": "", "email": "", "never_commit": []},
    "pr": {"footer": "", "merge": "architect", "method": "squash"},
    "review": {"provider": "opulent:reviewer"},
    "hazards": ["concurrency", "auth", "crypto", "migration", "money",
                "public-contract"],
}

_UNSET = "(not configured)"
_SUMMARY_DAYS = 7


# --------------------------------------------------------------------------
# paths


def project_dir(cwd=None):
    """The project root for config and ledger lookups.

    CLAUDE_PROJECT_DIR when the harness exports one, else the payload's own
    `cwd` — the same two sources the routing hook resolves write targets
    against. Note what this is NOT: route-models.py never derives a project
    root at all, because its control-plane rule is path-shaped ("any .claude
    directory") and needs none. This is the first thing in the plugin that
    does, so it says out loud where it looked."""
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    base = env or cwd or os.getcwd()
    try:
        return os.path.normpath(str(base))
    except Exception:
        return os.getcwd()


def config_path(project):
    return os.path.join(project, CLAUDE_DIR, CONFIG_NAME)


def ledger_path(project):
    return os.path.join(project, CLAUDE_DIR, LEDGER_DIR, LEDGER_NAME)


def scratchpad():
    """`${SCRATCHPAD}`'s expansion: the session scratchpad if the environment
    names one, else the system temp dir.

    None of these variables is a documented harness contract, which is exactly
    why the fallback is unconditional rather than an error — a session that
    exports none still gets a usable lock directory, under the temp dir the
    scratchpad lives beneath anyway."""
    for name in ("CLAUDE_SCRATCHPAD_DIR", "CLAUDE_SCRATCHPAD",
                 "OPULENT_SCRATCHPAD"):
        value = os.environ.get(name)
        if value:
            return value
    return tempfile.gettempdir()


# --------------------------------------------------------------------------
# config


class Config(object):
    """A loaded config. `present` is "the file is there", `error` is "and it
    could not be believed" — the two are independent, and the policy block
    keys off both: absent means silence, invalid means one warning line and
    no block at all."""

    __slots__ = ("present", "path", "data", "warnings", "error")

    def __init__(self, present, path, data, warnings, error):
        self.present = present
        self.path = path
        self.data = data
        self.warnings = warnings
        self.error = error

    @property
    def ok(self):
        return self.present and not self.error

    def section(self, name):
        value = self.data.get(name)
        return value if isinstance(value, dict) else {}

    def get(self, section, key, default=""):
        value = self.section(section).get(key, default)
        return default if value is None else value


def _expand(value):
    """`${SCRATCHPAD}` in any string the config carries. Applied everywhere
    rather than only to `lock_dir`: a target_dir or a command can want the
    same directory, and a token that expands in one field and not its
    neighbour is a trap, not a feature."""
    if isinstance(value, str) and "${SCRATCHPAD}" in value:
        return value.replace("${SCRATCHPAD}", scratchpad())
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _expand(v)) for k, v in value.items())
    return value


def _merge(defaults, raw, warnings):
    """Defaults, overlaid with whatever the file got right. A section of the
    wrong type is a warning and the default, never a raise: the config is
    hand-written, and a typo in `git` must not cost the contract its `check`
    command."""
    out = {}
    for key, fallback in defaults.items():
        value = raw.get(key, None)
        if value is None:
            out[key] = fallback if not isinstance(fallback, (dict, list)) \
                else (dict(fallback) if isinstance(fallback, dict)
                      else list(fallback))
            continue
        if isinstance(fallback, dict):
            if not isinstance(value, dict):
                warnings.append("%s is not an object; using defaults" % key)
                out[key] = dict(fallback)
                continue
            merged = dict(fallback)
            for k, v in value.items():
                if k not in fallback:
                    warnings.append("unknown key %s.%s ignored" % (key, k))
                    continue
                merged[k] = v
            out[key] = merged
        elif isinstance(fallback, list):
            if not isinstance(value, list):
                warnings.append("%s is not a list; using defaults" % key)
                value = list(fallback)
            out[key] = value
        else:
            out[key] = value
    for key in raw:
        if key not in defaults and key != "schema":
            warnings.append("unknown key %s ignored" % key)
    return out


def load(project):
    """The config for a project. One function, shared by both hooks and the
    command, and it never raises."""
    path = config_path(project)
    try:
        if not os.path.isfile(path):
            return Config(False, path, copy.deepcopy(DEFAULTS), [], None)
    except Exception:
        return Config(False, path, copy.deepcopy(DEFAULTS), [], None)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as exc:
        return Config(True, path, copy.deepcopy(DEFAULTS), [],
                      "%s: %s" % (type(exc).__name__, exc))
    if not isinstance(raw, dict):
        return Config(True, path, copy.deepcopy(DEFAULTS), [],
                      "top level is %s, expected an object"
                      % type(raw).__name__)
    schema = raw.get("schema")
    if schema != SCHEMA:
        # A schema this release does not know is not interpreted, for the
        # reason a newer config file is never read by an older reader: the
        # keys may have moved under it, and a best-effort read of a document
        # written for someone else is how a lane gets briefed with the wrong
        # commands.
        return Config(True, path, copy.deepcopy(DEFAULTS), [],
                      "schema is %r, expected %r" % (schema, SCHEMA))
    warnings = []
    data = _expand(_merge(DEFAULTS, raw, warnings))
    merge = data["pr"].get("merge")
    if merge not in MERGE_MODES:
        warnings.append("pr.merge %r is not one of %s; using %r"
                        % (merge, "/".join(MERGE_MODES), DEFAULTS["pr"]["merge"]))
        data["pr"]["merge"] = DEFAULTS["pr"]["merge"]
    method = data["pr"].get("method")
    if method not in MERGE_METHODS:
        warnings.append("pr.method %r is not one of %s; using %r"
                        % (method, "/".join(MERGE_METHODS),
                           DEFAULTS["pr"]["method"]))
        data["pr"]["method"] = DEFAULTS["pr"]["method"]
    return Config(True, path, data, warnings, None)


def warning_line(cfg):
    """At most ONE line, ever — for an unreadable file and for a readable one
    with junk in it alike. The policy block has a line budget, and a config
    with six unknown keys must not spend it."""
    if cfg.error:
        return "pr-lane: %s could not be read (%s) — the module is off for " \
               "this session." % (cfg.path, cfg.error)
    if cfg.warnings:
        return "pr-lane: config warnings — " + "; ".join(cfg.warnings)
    return ""


# --------------------------------------------------------------------------
# the brief contract


def _field(value, fallback=_UNSET):
    if value is None:
        return fallback
    if isinstance(value, (list, tuple)):
        rendered = ", ".join(str(v) for v in value if str(v).strip())
        return rendered or fallback
    text = str(value).strip()
    return text or fallback


def contract(cfg, unit="<unit-id>", hazard="<name|none>"):
    """The text that is pasted VERBATIM into an implementation brief.

    Angle-bracket fields come from the config; `<unit-id>`, `<hazard>`,
    `<who>` and `<crate>` stay as placeholders because no config key names
    them — they are per-unit, and filling them with a plausible value here is
    the one way this text could lie to a lane."""
    base = _field(cfg.data.get("base"), DEFAULTS["base"])
    return "\n".join([
        MARKER,
        "- unit: %s   hazard: %s   branch: feat/%s off origin/%s"
        % (unit, hazard, unit, base),
        "- Work only in the isolated worktree you were given. Never switch branches in the main tree.",
        "  Never push %s. Never open the PR yourself. Never commit %s."
        % (base, _field(cfg.get("git", "never_commit"), "nothing in particular")),
        "- Step zero in a fresh worktree: %s. Then, in order: %s → focused tests → the full"
        % (_field(cfg.get("commands", "step_zero")),
           _field(cfg.get("commands", "check"))),
        "  suite once (%s) → %s. Fix failures; never disable a test."
        % (_field(cfg.get("commands", "test")),
           _field(cfg.get("commands", "lint"))),
        "- Red-then-green: write the regression test first, run it against the unchanged code, and",
        "  record the exact failing assertion (or compile error) for the PR body. A guard that is green",
        "  on %s pastes ONE deliberate mutation going red instead." % base,
        '- Shared machine: take the build lock in ONE call (`mkdir "%s" && echo "<who> $$ <branch> $(date)" > "%s/owner"`),'
        % (_field(cfg.get("shared_machine", "lock_dir")),
           _field(cfg.get("shared_machine", "lock_dir"))),
        '  poll with bounded `sleep 3` loops, release with `rm -f "%s/owner" && rmdir "%s"`'
        % (_field(cfg.get("shared_machine", "lock_dir")),
           _field(cfg.get("shared_machine", "lock_dir"))),
        "  and verify it is gone; CARGO_TARGET_DIR=%s; `cargo clean -p <crate>` per batch; kill"
        % _field(cfg.get("shared_machine", "target_dir")),
        "  smoke servers by PID; copy binaries out before smoke runs; lane-prefixed scratch files.",
        '- Commit: `git -c user.name="%s" -c user.email="%s" commit`, message `TYPE(scope): summary`'
        % (_field(cfg.get("git", "user")), _field(cfg.get("git", "email"))),
        "  + body + trailer `%s`; push the branch with the first (red) commit already pushed."
        % _field(cfg.get("git", "trailer")),
        "- Report: branch + head SHA; files changed (one line each); the red-then-green evidence verbatim;",
        "  test/lint counts; every deviation from the brief and why; notes for the reviewer.",
    ])


def policy_block(project, now=None):
    """The text session-start.py appends — and the empty string is the whole
    point of the function. No config, no block, no separator, no newline: the
    0.24.0 output, byte for byte."""
    cfg = load(project)
    if not cfg.present:
        return ""
    warn = warning_line(cfg)
    if cfg.error:
        return "\n\n" + warn
    lines = [
        "# pr-lane (opulent plugin, opt-in)",
        "",
        "`%s/%s` is present, so this project's changes go through the PR lane. Phase 1 RECORDS:"
        % (CLAUDE_DIR, CONFIG_NAME),
        "it denies nothing but that config file, and the ledger below is a log, not a gate.",
        "",
        "Per unit: brief `opulent:coder` in an isolated worktree on `feat/<unit>` off `origin/%s` ->"
        % _field(cfg.data.get("base"), DEFAULTS["base"]),
        "red-then-green -> `%s` -> PR (body: Why · What · Tests (red-then-green) ·"
        % _field(cfg.get("review", "provider"), DEFAULTS["review"]["provider"]),
        "Verified / not verified · footer) -> merge-compile check if the base moved -> every CI leg",
        "green -> merged per `%s` (%s). One unit = one worktree = one branch = one PR; never"
        % (_field(cfg.get("pr", "merge"), "architect"),
           _field(cfg.get("pr", "method"), "squash")),
        "stacked; parallel units only when their file sets are disjoint, at most %s building at"
        % _field(cfg.get("shared_machine", "max_lanes_building"), "2"),
        "once. Remove the worktree after the merge.",
        "",
        "Every brief carries `hazard: none`, or one name from:",
        "%s. A hazard PR is labelled `hazard` and the USER"
        % _field(cfg.data.get("hazards"), "(none configured)"),
        "merges it whatever the setting above says. Never commit %s."
        % _field(cfg.get("git", "never_commit"), "nothing in particular"),
        "Documentation and browser verification stay with you, per the routing policy above.",
        "",
        "Paste this contract VERBATIM into every implementation brief; the marker line is how a "
        "reader knows it was.",
        "",
        contract(cfg),
        "",
        summary(read(project), now=now),
    ]
    if warn:
        lines.append(warn)
    return "\n\n" + "\n".join(lines)


# --------------------------------------------------------------------------
# ledger


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds")


def append(project, fields):
    """One JSON object, one line, append-only. Returns whether it landed;
    callers ignore that, because a ledger that cannot be written is a ledger
    that records nothing, not a session that fails.

    `fields`, not `record` — the module-level record() is the caller, and a
    parameter wearing its name reads like recursion to everyone but the
    interpreter."""
    path = ledger_path(project)
    try:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        entry = {"t": fields.get("t") or _now_iso()}
        for key in ("sid", "unit", "event", "by", "branch", "sha", "pr",
                    "verdict", "note"):
            value = fields.get(key)
            if value not in (None, ""):
                entry[key] = value
        with open(path, "a", encoding="utf-8") as fh:
            # One write() per line, as the routing log does it, so two
            # sessions appending at once cannot tear each other's records.
            fh.write(json.dumps(entry) + "\n")
        return True
    except Exception:
        return False


def read(project):
    """Every parseable line, in file order. A torn or hand-edited line is not
    a record and is skipped in silence — the same reading the session-start
    telemetry gives the routing log."""
    try:
        with open(ledger_path(project), encoding="utf-8",
                  errors="replace") as fh:
            lines = fh.readlines()
    except Exception:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def _age_days(entry, now):
    """Days since a record's timestamp, or None when it carries none this can
    read. None means "do not hide it": a record whose age is unknown is shown,
    because the alternative is a unit that silently vanishes."""
    raw = entry.get("t")
    if not isinstance(raw, str):
        return None
    try:
        stamp = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=datetime.timezone.utc)
    return (now - stamp).total_seconds() / 86400.0


def _units(entries):
    """Records grouped by unit, in first-seen order. File order is the truth:
    a hand-appended line carrying a stale timestamp still happened last, and
    sorting by `t` would let it change the past."""
    groups = {}
    order = []
    for entry in entries:
        unit = entry.get("unit")
        unit = str(unit) if unit not in (None, "") else "(unattached)"
        if unit not in groups:
            groups[unit] = []
            order.append(unit)
        groups[unit].append(entry)
    return [(unit, groups[unit]) for unit in order]


def _state(records):
    """The latest state of one unit: its last event, plus the last PR number,
    verdict, branch and SHA anyone recorded for it."""
    state = {"event": None, "pr": None, "verdict": None, "branch": None,
             "sha": None, "ci": None, "last": None}
    for entry in records:
        event = entry.get("event")
        if event in EVENTS:
            state["event"] = event
            state["last"] = entry
        if event == "ci":
            state["ci"] = entry.get("verdict")
        if event == "reviewed":
            state["verdict"] = entry.get("verdict")
        if event == "merged":
            state["merged"] = True
        for key in ("pr", "branch", "sha"):
            if entry.get(key) not in (None, ""):
                state[key] = entry.get(key)
    return state


def _pr_label(state, unit):
    return "#%s" % state["pr"] if state["pr"] else unit


def summary(entries, now=None):
    """The one line session start renders (§3.6 of the spec).

    `<n> units` counts what the line SHOWS: a unit merged more than seven days
    ago is dropped from the count as well as from the sections, because a
    number larger than the names beside it is a number nobody can check. The
    records stay on disk either way — this hides, it never prunes."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    shown = []
    for unit, records in _units(entries):
        state = _state(records)
        if state.get("merged"):
            age = _age_days(state["last"], now)
            if age is not None and age > _SUMMARY_DAYS:
                continue
        shown.append((unit, state))
    if not shown:
        return "pr-lane: ledger empty"
    coded = [u for u, s in shown if s["event"] == "coded"]
    reviewed = [u for u, s in shown if s["event"] == "reviewed"]
    open_prs = [_pr_label(s, u) for u, s in shown
                if s["pr"] and not s.get("merged")]
    merged = [_pr_label(s, u) for u, s in shown if s.get("merged")]
    parts = []
    if coded:
        parts.append("coded " + ", ".join(coded))
    if reviewed:
        parts.append("reviewed " + ", ".join(reviewed))
    if open_prs:
        parts.append("open PRs " + ", ".join(open_prs))
    if merged:
        parts.append("merged %s (last %d days)"
                     % (", ".join(merged), _SUMMARY_DAYS))
    line = "pr-lane: %d unit%s" % (len(shown), "" if len(shown) == 1 else "s")
    if parts:
        line += " — " + " · ".join(parts)
    return line


def _blocked(unit, state):
    """Why a unit is not moving, in the spec's four shapes. None when it is."""
    event = state["event"]
    if state.get("merged"):
        return None
    if state["verdict"] == "NOT SAFE":
        return "review came back NOT SAFE"
    if event == "coded":
        return "coded, no review recorded"
    if state["pr"] and state["ci"] is None:
        return "PR %s open, no CI verdict recorded" % _pr_label(state, unit)
    if state["ci"] == "fail":
        return "CI failed"
    if event == "handed_off":
        return "handed off, waiting on the user"
    return None


def report(project, now=None):
    """The full form `/opulent:pr-lane` prints: one line per unit, then what
    is blocked and on what, then the config's own state."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    cfg = load(project)
    entries = read(project)
    lines = ["pr-lane: %s" % project]
    if not cfg.present:
        lines.append("config: %s is absent — the module is off for this "
                     "project." % config_path(project))
        return "\n".join(lines)
    if cfg.error:
        lines.append("config: %s did NOT parse (%s) — the module is off for "
                     "this session." % (cfg.path, cfg.error))
        return "\n".join(lines)
    lines.append("config: %s parsed (schema %s, base %s, merge %s/%s, review %s)"
                 % (cfg.path, SCHEMA, cfg.data.get("base"),
                    cfg.get("pr", "merge"), cfg.get("pr", "method"),
                    cfg.get("review", "provider")))
    warn = warning_line(cfg)
    if warn:
        lines.append(warn)
    lines.append("ledger: %s — %d record%s"
                 % (ledger_path(project), len(entries),
                    "" if len(entries) == 1 else "s"))
    blocked = []
    for unit, records in _units(entries):
        state = _state(records)
        bits = [state["event"] or "no event"]
        if state["verdict"]:
            bits.append("review %s" % state["verdict"])
        if state["pr"]:
            bits.append("PR #%s" % state["pr"])
        if state["ci"]:
            bits.append("CI %s" % state["ci"])
        if state["branch"]:
            bits.append(state["branch"])
        if state["sha"]:
            bits.append(str(state["sha"])[:12])
        lines.append("  %-24s %s" % (unit, " - ".join(bits)))
        why = _blocked(unit, state)
        if why:
            blocked.append("  %-24s %s" % (unit, why))
    if blocked:
        lines.append("blocked:")
        lines.extend(blocked)
    lines.append(summary(entries, now=now))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# PostToolUse recorders
#
# Text in, records out. Every parser below returns None when it cannot read
# its input, and every caller omits the field rather than filling it: a
# branch, a SHA or a PR number the ledger invented would be worse than the
# blank it replaced, because the whole point of the file is to be believed.

_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_UNIT_LINE = re.compile(r"^\s*[-*]?\s*unit:\s*([A-Za-z0-9][\w.\-/]{0,63})",
                        re.M)
_BRANCH = re.compile(r"\bfeat/([A-Za-z0-9][\w.\-]{0,63})")
_SHA = re.compile(r"\b(?:sha|SHA|commit)\b[^\n0-9a-f]{0,20}([0-9a-f]{7,40})\b")
_PR_URL = re.compile(r"/pull/(\d+)")
_PR_ARG = re.compile(r"\bpr\s+(?:merge|checks|view|edit)\s+#?(\d+)")
_PENDING = re.compile(r"\b(pending|queued|in_progress|in progress)\b", re.I)
_FAILING = re.compile(r"\b(fail|failed|failing|failure|failures)\b", re.I)
# Bound every text this reads. An agent report can be tens of thousands of
# characters and a `gh` run can print a wall of check rows; the fields parsed
# out of either live in the first few hundred lines, and an unbounded regex
# pass over a hostile-sized string is the one way a recorder could cost a
# session real time.
_TEXT_LIMIT = 64 * 1024


def _unquoted(text):
    """Quoted spans blanked, the way the routing hook reads a command before
    matching a tool name in it: `echo "gh pr create"` announces nothing."""
    return _QUOTED.sub(" ", text or "")


def response_text(payload):
    """Whatever text a PostToolUse payload carries back from the tool.

    The harness shape is not pinned anywhere in this repo — `tool_response`
    is the field the selftest's own fixtures send, `tool_result` is the other
    spelling the brief named — so this walks whichever arrived and collects
    every string it finds under the keys a result uses. Shape-agnostic on
    purpose: a recorder that knew one shape would go silently blind the day
    the harness sent another, and silence is the failure mode a ledger cannot
    afford."""
    found = []

    def walk(node, depth):
        if depth > 6 or len("".join(found)) > _TEXT_LIMIT:
            return
        if isinstance(node, str):
            found.append(node)
        elif isinstance(node, dict):
            hit = False
            for key in ("text", "stdout", "stderr", "output", "content",
                        "result", "response", "message", "data"):
                if key in node:
                    hit = True
                    walk(node[key], depth + 1)
            if not hit:
                # A shape none of those names describes still has its text
                # somewhere, and reading too much here costs nothing: the
                # marker that decides whether anything is recorded at all is
                # read from the PROMPT, never from this.
                for value in node.values():
                    walk(value, depth + 1)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item, depth + 1)

    for field in ("tool_response", "tool_result"):
        if field in (payload or {}):
            walk(payload.get(field), 0)
    return "\n".join(found)[:_TEXT_LIMIT]


def prompt_text(tool_input):
    """The brief a Task/Agent call was given. `prompt` is the field the
    marker rides in; `description` is joined because a short call sometimes
    carries the whole ask there, and joining two strings cannot produce a
    marker neither of them held."""
    if not isinstance(tool_input, dict):
        return ""
    parts = []
    for key in ("prompt", "description"):
        value = tool_input.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)[:_TEXT_LIMIT]


def unit_from_text(text):
    match = _UNIT_LINE.search(text or "")
    return match.group(1) if match else None


def branch_from_text(text):
    match = _BRANCH.search(text or "")
    return "feat/" + match.group(1) if match else None


def unit_from_branch(text):
    match = _BRANCH.search(text or "")
    return match.group(1) if match else None


def sha_from_text(text):
    match = _SHA.search(text or "")
    return match.group(1) if match else None


def pr_from_text(text):
    match = _PR_URL.search(text or "")
    if match:
        return int(match.group(1))
    match = _PR_ARG.search(text or "")
    return int(match.group(1)) if match else None


def review_verdict(text):
    """SAFE / NOT SAFE / unknown, read off the report's LAST line — which is
    where agents/reviewer.md puts it. NOT SAFE is tested first because SAFE is
    a substring of it, and getting that order wrong turns every rejection into
    an approval."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return "unknown"
    last = lines[-1].upper()
    if "NOT SAFE" in last:
        return "NOT SAFE"
    if "SAFE" in last:
        return "SAFE"
    return "unknown"


def ci_verdict(text):
    """pass/fail for a settled `gh pr checks`, or None while anything is still
    running. Textual, like TEST_RE in the routing hook: there is no API call
    here, and a record that guessed at a run still in flight would be read as
    a result."""
    if not text or _PENDING.search(text):
        return None
    return "fail" if _FAILING.search(text) else "pass"


def record(payload, tool, tool_input, cwd, project=None, cfg=None):
    """The routing hook's PostToolUse entry point. Records at most one ledger
    line per tool call, and only for a project that opted in. Never raises,
    never denies, never touches the routing log."""
    try:
        project = project or project_dir(cwd)
        cfg = cfg or load(project)
        if not cfg.ok:
            return None
        sid = str((payload or {}).get("session_id") or "")[:8]
        entry = None
        if tool in ("Task", "Agent"):
            entry = _record_agent(payload, tool_input, cfg)
        elif tool in ("Bash", "PowerShell"):
            entry = _record_shell(payload, tool_input)
        if not entry:
            return None
        entry["by"] = "hook"
        if sid:
            entry["sid"] = sid
        append(project, entry)
        return entry
    except Exception:
        return None


def _record_agent(payload, tool_input, cfg):
    lane = (tool_input or {}).get("subagent_type") or ""
    if not isinstance(lane, str):
        lane = str(lane)
    prompt = prompt_text(tool_input)
    report_text = response_text(payload)
    provider = str(cfg.get("review", "provider",
                           DEFAULTS["review"]["provider"]))
    if lane == provider:
        return {"event": "reviewed", "unit": unit_from_text(prompt),
                "verdict": review_verdict(report_text)}
    if lane in CODING_LANES and MARKER in prompt:
        # Branch and SHA come from the lane's own report, which the contract
        # requires it to state; absent, the fields are omitted. The prompt is
        # the fallback for the branch only, because the brief NAMES the
        # branch the lane was given — it does not know the SHA in advance.
        return {"event": "coded", "unit": unit_from_text(prompt),
                "branch": branch_from_text(report_text)
                or branch_from_text(prompt),
                "sha": sha_from_text(report_text)}
    return None


def _record_shell(payload, tool_input):
    cmd = (tool_input or {}).get("command") or ""
    if not isinstance(cmd, str):
        cmd = str(cmd)
    cmd = cmd[:_TEXT_LIMIT]
    probe = " ".join(_unquoted(cmd).split())
    out = response_text(payload)
    if "gh pr create" in probe:
        return {"event": "pr_opened", "unit": unit_from_branch(cmd),
                "branch": branch_from_text(cmd),
                "pr": pr_from_text(out) or pr_from_text(cmd)}
    if "gh pr merge" in probe:
        return {"event": "merged", "unit": unit_from_branch(cmd),
                "pr": pr_from_text(cmd) or pr_from_text(out)}
    if "gh pr checks" in probe:
        verdict = ci_verdict(out)
        if verdict is None:
            return None        # still running: there is nothing to record yet
        return {"event": "ci", "unit": unit_from_branch(cmd),
                "pr": pr_from_text(cmd) or pr_from_text(out),
                "verdict": verdict}
    return None


if __name__ == "__main__":
    # An EMPTY argument is not an argument: a caller that passes
    # "${CLAUDE_PROJECT_DIR}" through a shell gets "" rather than nothing
    # when the variable is unset, and "" is not a project directory.
    _project = (sys.argv[1] if len(sys.argv) > 1 else "") or project_dir()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    print(report(_project))
