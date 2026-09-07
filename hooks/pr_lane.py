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
# A unit whose last record is older than this is not in flight any more,
# whatever its last event was. It stays on disk and stays in the full report
# (tagged `(stale)`); it leaves the one-line summary, which is a status line
# for work that is moving.
_STALE_DAYS = 30
# How many names one summary part will list before it counts the rest. The
# line shares a context window with the routing policy, and forty unit ids
# spent on one part is the whole budget.
_SUMMARY_NAMES = 6
# The rendered policy block's line budget. It shares a context window with
# the routing policy above it, and there is no rung above "the model stopped
# reading".
_BLOCK_LINES = 48
# The rendered policy block's byte budget. The 48-line budget above pins
# bounds the wrong dimension on its own: a two-hundred-unit summary is one
# 2 KB line and passes it.
_BLOCK_BYTES = 4 * 1024
_TRUNCATED = ("pr-lane: the block hit its %d KiB budget and was cut here."
              % (_BLOCK_BYTES // 1024))
# How much of the ledger one render reads, in lines — the same posture
# session-start.py's `_recent_activity` takes toward the routing log's 500.
_READ_LINES = 2000


# --------------------------------------------------------------------------
# paths


# Git Bash spells `C:\Users\x` as `/c/Users/x`, and normpath turns that into
# `\c\Users\x` — a path equal to nothing, so the config lookup misses and the
# whole module is silently off in exactly the shell this project is driven
# from. route-models._msys_drive is the source of truth for this mapping and
# carries the full rationale; this is a copy rather than an import because
# route-models imports THIS module, and the cycle would cost the hook its
# recorder. POSIX has no such convention, hence the platform guard.
_MSYS_DRIVE_RE = re.compile(r"^/([A-Za-z])/")


def _msys_drive(p):
    if sys.platform != "win32":
        return p
    m = _MSYS_DRIVE_RE.match(p)
    return m.group(1).upper() + ":\\" + p[3:] if m else p


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
        return os.path.normpath(_msys_drive(str(base)))
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
    """`${SCRATCHPAD}` in any string the config carries, and every string
    flattened to ONE line.

    Expansion is applied everywhere rather than only to `lock_dir`: a
    target_dir or a command can want the same directory, and a token that
    expands in one field and not its neighbour is a trap, not a feature.

    The flattening is the same kind of rule: a config value is one line by
    definition — every field this file renders sits inside a line of the
    contract — so a value carrying newlines does not get to add lines to a
    block that has a budget, or to open a line of its own where a reader
    would take it for the block's own text."""
    if isinstance(value, str):
        if "\n" in value or "\r" in value:
            value = " ".join(value.split("\n"))
            value = " ".join(value.split("\r"))
        if "${SCRATCHPAD}" in value:
            return value.replace("${SCRATCHPAD}", scratchpad())
        return value
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
    provider = data["review"].get("provider")
    if isinstance(provider, str) and provider in CODING_LANES:
        # A coding lane named as the review provider does not merely mislabel
        # one record: the recorder tests the provider FIRST, so every coder
        # return would be filed as a review and `coded` would be unreachable
        # for the whole session. Treated as unset — the default provider —
        # like an out-of-range pr.merge above, and said out loud.
        warnings.append("review.provider %r is a coding lane, which would "
                        "make `coded` unrecordable; using %r"
                        % (provider, DEFAULTS["review"]["provider"]))
        data["review"]["provider"] = DEFAULTS["review"]["provider"]
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


def _budget(text, limit=_BLOCK_BYTES):
    """`text` clipped to a byte budget, on a line boundary, saying so.

    Bytes rather than lines because the config's own values are in here and
    nothing bounds their length: one `never_commit` list is one line however
    many kilobytes it is. Clipping loses the tail — the summary — rather than
    the contract, which is the half a brief has to be able to paste."""
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    room = max(0, limit - len(_TRUNCATED.encode("utf-8")) - 1)
    clipped = raw[:room].decode("utf-8", "ignore")
    head, sep, _tail = clipped.rpartition("\n")
    return (head if sep else clipped) + "\n" + _TRUNCATED


def policy_block(project, now=None):
    """The text session-start.py appends — and the empty string is the whole
    point of the function. No config, no block, no separator, no newline: the
    0.24.0 output, byte for byte."""
    cfg = load(project)
    if not cfg.present:
        return ""
    warn = warning_line(cfg)
    if cfg.error:
        return _budget("\n\n" + warn)
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
        "Review ladder — recorded, never enforced: one full review per unit; a second only if the first",
        "came back NOT SAFE, and only on the delta; never a third. After that, run the reviewer's own probe",
        "cases yourself, let CI decide, merge or hand off, and put what is left in the PR body. A review",
        "brief carries the unit's `unit:` line so the ledger can count its rounds; the ledger shows what",
        "you did, and that record is the whole mechanism.",
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
    return _budget("\n\n" + "\n".join(lines))


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
        # newline="\n" because the command that renders this file invites the
        # architect to append to it with `>>`, which writes LF on every
        # platform: without the pin, Windows would give the hook's own lines
        # CRLF and the file would carry two spellings of one record type.
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            # One write() per line, as the routing log does it, so two
            # sessions appending at once cannot tear each other's records.
            fh.write(json.dumps(entry) + "\n")
        return True
    except Exception:
        return False


def read(project):
    """The last _READ_LINES parseable lines, in file order. A torn or
    hand-edited line is not a record and is skipped in silence — the same
    reading the session-start telemetry gives the routing log.

    Bounded for the same reason that telemetry reads 500: this runs at every
    session start, the file only grows, and a year of units is a file nobody
    wants read into memory to render one line. Old records stay on disk; they
    stop being rendered long before this bound, at _STALE_DAYS."""
    try:
        with open(ledger_path(project), encoding="utf-8",
                  errors="replace") as fh:
            lines = fh.readlines()[-_READ_LINES:]
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
    sorting by `t` would let it change the past.

    A record with a PR number and no unit is JOINED to whichever unit another
    record gave that same PR. `gh pr checks 74` and `gh pr merge 74` name no
    branch, so the recorder cannot know their unit from the command — and
    without the join, the unit that reached CI and merged still rendered as
    `coded, no review recorded` while its own merge sat in a separate bucket:
    one PR, counted twice, in two states, one of them wrong.

    Records the join cannot reach are bucketed BY PR (`(unattached #74)`),
    never all together. The single-bucket version let one PR's `merged`
    overwrite another PR's failing CI, which is the one way this file could
    erase a red result rather than merely fail to attribute it. Only a record
    with neither unit nor PR falls into the shared `(unattached)`."""
    by_pr = {}
    for entry in entries:
        unit, pr = entry.get("unit"), entry.get("pr")
        if unit not in (None, "") and pr not in (None, ""):
            by_pr.setdefault(str(pr), str(unit))
    groups = {}
    order = []
    for entry in entries:
        unit, pr = entry.get("unit"), entry.get("pr")
        if unit not in (None, ""):
            unit = str(unit)
        elif pr in (None, ""):
            unit = "(unattached)"
        elif str(pr) in by_pr:
            unit = by_pr[str(pr)]
            entry = dict(entry, unit=unit)   # a copy: the caller's list stands
        else:
            unit = "(unattached #%s)" % pr
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


def _unit_age(state, now):
    """Days since this unit's last recorded event, or None when nothing it
    can read says. None means "do not hide it"."""
    last = state.get("last")
    return _age_days(last, now) if last else None


def _names(items):
    """A comma-joined name list, bounded, counting what it left out. A
    summary that lists two hundred units is not a summary of them."""
    if len(items) <= _SUMMARY_NAMES:
        return ", ".join(items)
    return "%s … (+%d)" % (", ".join(items[:_SUMMARY_NAMES]),
                           len(items) - _SUMMARY_NAMES)


def summary(entries, now=None):
    """The one line session start renders (§3.6 of the spec).

    `<n> units` counts what the line SHOWS: a unit merged more than seven days
    ago — or one nothing has touched in a month, merged or not — is dropped
    from the count as well as from the sections, because a number larger than
    the names beside it is a number nobody can check. The records stay on disk
    either way, and the full report still shows them: this hides, it never
    prunes."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    shown = []
    for unit, records in _units(entries):
        state = _state(records)
        age = _unit_age(state, now)
        if age is not None and age > _STALE_DAYS:
            continue
        if state.get("merged") and age is not None and age > _SUMMARY_DAYS:
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
        parts.append("coded " + _names(coded))
    if reviewed:
        parts.append("reviewed " + _names(reviewed))
    if open_prs:
        parts.append("open PRs " + _names(open_prs))
    if merged:
        parts.append("merged %s (last %d days)"
                     % (_names(merged), _SUMMARY_DAYS))
    line = "pr-lane: %d unit%s" % (len(shown), "" if len(shown) == 1 else "s")
    if parts:
        line += " — " + " · ".join(parts)
    return line


def _blocked(unit, state):
    """Why a unit is not moving, in six shapes. None when it is.

    `unit_defined` is deliberately not one of them: a unit somebody named and
    has not started is a plan, and a plan is not a blockage."""
    event = state["event"]
    if state.get("merged"):
        return None
    if state["verdict"] == "NOT SAFE":
        return "review came back NOT SAFE"
    if event == "coded":
        return "coded, no review recorded"
    if event == "reviewed" and state["verdict"] == "SAFE" and not state["pr"]:
        # The gap the four-shape version left open, and the expensive one:
        # a unit that passed review and never got its PR opened reads as
        # finished work in every other line of this file.
        return "reviewed SAFE, no PR opened"
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
        age = _unit_age(state, now)
        if age is not None and age > _STALE_DAYS:
            # Out of the summary, still in the report — the full form is where
            # you go to find the unit the one-liner stopped mentioning, so it
            # says why rather than dropping it too.
            bits.append("(stale)")
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
# Anchored words, on the report's last line only. "UNSAFE" has no word
# boundary before SAFE and so matches neither pattern — the substring reading
# these replaced called it an approval.
_NOT_SAFE = re.compile(r"\bNOT\s+SAFE\b")
_SAFE = re.compile(r"(?<!UN)\bSAFE\b")
# A `gh pr checks` row is `name<TAB>status<TAB>duration<TAB>url`, and only the
# STATUS column is a verdict. Scanned as whole text, a job named `fail-fast`
# or a URL ending in `/failures` made every green run red.
_CI_PASS = ("pass", "success", "skipping", "skipped")
_CI_FAIL = ("fail", "failure", "error", "cancelled")
_CI_PENDING = ("pending", "queued", "in_progress", "in progress", "waiting")
# `gh` reporting a failure is not the tool doing the thing. Line-anchored, so
# a PR body or a check name that merely contains one of these is not a
# refusal; case-insensitive, because gh is not consistent about it.
_ERROR_LINE = re.compile(
    r"(?im)^[ \t]*(?:GraphQL:|error:|X |failed to|not mergeable|HTTP 4|HTTP 5)")
# `--auto` ARMS a merge; it does not perform one. Phase 1 has no event for
# "armed", so the honest record is no record.
_AUTO = re.compile(r"(?<![\w-])--auto\b")
# Command position, and comments. Both borrowed from route-models.py, which
# is the source of truth for how this plugin reads a shell command; copies
# rather than imports because route-models imports THIS module.
_CMD_PREFIXES = {"sudo", "command", "time", "env", "xargs", "nice",
                 "timeout", "nohup", "setsid", "stdbuf"}
_COMMENT = re.compile(r"(?m)(?:^|\s)#[^\n]*")
_SEGMENTS = re.compile(r"&&|\|\||[;\n|]")
_HEREDOC = re.compile(
    r"(?<!<)<<(?!<)-?\s*(?:'([A-Za-z_]\w*)'|\"([A-Za-z_]\w*)\"|\\?([A-Za-z_]\w*))")
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


def _strip_heredocs(cmd):
    """The command with every heredoc BODY (and its terminator) removed, and
    only when the terminator actually exists — route-models._strip_heredocs,
    which carries the full rationale. Here it is what stops `gh pr create`
    written INSIDE a PR-body document from being read as the call that opens
    the PR, while the real `gh pr create` after the terminator still is."""
    if "<<" not in cmd:
        return cmd
    lines = cmd.split("\n")
    out = []
    k = 0
    while k < len(lines):
        line = lines[k]
        out.append(line)
        k += 1
        for m in _HEREDOC.finditer(line):
            delim = next((g for g in m.groups() if g is not None), "")
            if not delim:
                continue
            dashed = m.group(0)[2:3] == "-"
            end = None
            for j in range(k, len(lines)):
                cand = lines[j].lstrip("\t") if dashed else lines[j]
                if cand == delim:
                    end = j
                    break
            if end is None:
                continue        # unterminated: strip NOTHING
            k = end + 1
    return "\n".join(out)


def runs_gh_pr(cmd, verb):
    """True when `cmd` actually RUNS `gh pr <verb>` — the token at a command
    position, not merely present in the text.

    The substring reading this replaced recorded a PR for `echo gh pr
    create`, for `# gh pr create` in a note to self, and for the same words
    inside a heredoc'd PR body. Documents are stripped, quoted spans and
    comments blanked, and what is left is split on the operators that end a
    command; a segment counts only if `gh pr <verb>` is its first three words
    once env assignments and wrapper prefixes are stepped over.

    A prefix's OWN options are not stepped over (`sudo -u x gh pr merge`
    reads as no command here). That direction is the safe one: the cost is a
    record this file does not make, not a record it invents."""
    text = _COMMENT.sub(" ", _unquoted(_strip_heredocs(cmd or "")))
    want = ["gh", "pr", verb]
    for segment in _SEGMENTS.split(text):
        words = segment.split()
        i = 0
        while i < len(words) and (
                words[i].rsplit("/", 1)[-1] in _CMD_PREFIXES
                or ("=" in words[i] and not words[i].startswith("-"))):
            i += 1
        if words[i:i + 3] == want:
            return True
    return False


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
    # A RUNNING total, not a re-join per node: the budget check used to
    # rebuild the whole accumulated string at every string it found, which is
    # quadratic — a response arriving as 200 000 one-character blocks (a
    # streamed tool result is exactly that shape) took 43 seconds of a
    # session's time to decide it had read enough.
    size = [0]

    def walk(node, depth):
        if depth > 6 or size[0] > _TEXT_LIMIT:
            return
        if isinstance(node, str):
            found.append(node)
            size[0] += len(node)
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
    where agents/reviewer.md puts it.

    Both readings are anchored WORDS, and NOT SAFE is tested first because
    SAFE is a substring of it: getting either wrong turns a rejection into an
    approval, which is the one misreading in this file that can get bad code
    merged. `UNSAFE` — no boundary before SAFE — was read as an approval by
    the substring version and is `unknown` here, because a reviewer who wrote
    it did not write the charter's verdict line and the ledger should say so
    rather than pick one."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return "unknown"
    last = lines[-1].upper()      # upper(): the anchoring is case-blind
    if _NOT_SAFE.search(last):
        return "NOT SAFE"
    if _SAFE.search(last):
        return "SAFE"
    return "unknown"


def ci_verdict(text):
    """pass/fail for a settled `gh pr checks`, or None for anything else —
    still running, no rows this can read, a status nobody here recognises.

    Read from the STATUS COLUMN of each row, never from the output as a whole.
    Scanning the text made a check named `fail-fast` and a run URL ending in
    `/failures` into failures of their own, which is a verdict about the
    naming of a job reported as a verdict about the code. Textual either way,
    like TEST_RE in the routing hook: there is no API call here, and None —
    record nothing — is what every reading short of a settled one produces."""
    rows = []
    for line in (text or "").splitlines():
        cols = line.split("\t")
        if len(cols) >= 2:
            rows.append(cols[1].strip().lower())
    if not rows:
        return None
    if any(r in _CI_PENDING for r in rows):
        return None     # in flight: pending outranks a row that already fails
    if any(r in _CI_FAIL for r in rows):
        return "fail"
    if all(r in _CI_PASS for r in rows):
        return "pass"
    return None         # a status this does not know is not a verdict


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
    """A lane's return, read for a ledger line.

    The asymmetry between the two branches is deliberate and worth stating:
    `coded` requires the contract MARKER in the brief, `reviewed` does not.
    The marker is what separates a pr-lane unit from the ordinary delegations
    that make up most of a session, and a coding lane is spawned for both —
    so without it the ledger would record every implementation this plugin
    routes. The review provider is spawned for one thing, and a review whose
    brief the architect wrote by hand is still that unit's review; requiring
    the marker there would lose real verdicts to a formatting slip."""
    lane = (tool_input or {}).get("subagent_type") or ""
    if not isinstance(lane, str):
        lane = str(lane)
    prompt = prompt_text(tool_input)
    report_text = response_text(payload)
    provider = str(cfg.get("review", "provider",
                           DEFAULTS["review"]["provider"]))
    # `provider and` — an empty provider must not match a Task that named no
    # lane, which is the one way this branch could file a review nobody ran.
    if provider and lane == provider:
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
    """A `gh` call, read for a ledger line.

    Whether a nonzero-exit Bash call even reaches PostToolUse is NOT verified
    anywhere in this repo — the harness may or may not send a separate
    failure event — so nothing here relies on having been called only after a
    success. The guard is the output itself: a `gh` run whose text reports an
    error opened, merged and checked nothing, and is recorded as nothing."""
    cmd = (tool_input or {}).get("command") or ""
    if not isinstance(cmd, str):
        cmd = str(cmd)
    cmd = cmd[:_TEXT_LIMIT]
    out = response_text(payload)
    if _ERROR_LINE.search(out):
        return None
    if runs_gh_pr(cmd, "create"):
        return {"event": "pr_opened", "unit": unit_from_branch(cmd),
                "branch": branch_from_text(cmd),
                "pr": pr_from_text(out) or pr_from_text(cmd)}
    if runs_gh_pr(cmd, "merge"):
        if _AUTO.search(_unquoted(cmd)):
            # `--auto` arms the merge for whenever CI goes green, which may
            # be after this session ends. There is no `armed` event in phase
            # 1, and recording the merge that has not happened is the one
            # error this file cannot correct later.
            return None
        return {"event": "merged", "unit": unit_from_branch(cmd),
                "pr": pr_from_text(cmd) or pr_from_text(out)}
    if runs_gh_pr(cmd, "checks"):
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
