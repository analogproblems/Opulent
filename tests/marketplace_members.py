#!/usr/bin/env python3
"""Derives the marketplace roster from .claude-plugin/marketplace.json so CI
covers every member without a per-member edit — add a plugin to the
marketplace and it is checked, remove it and it stops being checked.

Members whose source is another repo cannot be checked against this tree;
they come back with manifest=None so callers skip the tree-level checks and
say so out loud."""
import json
import os
from collections import namedtuple

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETPLACE = ".claude-plugin/marketplace.json"

# Source forms the marketplace schema accepts, mapped to the keys each form
# needs to resolve. A "./"-prefixed string is the only in-tree form; every
# object form names another repo. Verified against `claude plugin validate`:
# a bare (non-"./") path, a "local" object, and a "git" object are all rejected
# by the schema, so they are not accepted here either.
EXTERNAL_SOURCES = {
    "github": ("repo",),
    "url": ("url",),
    "git-subdir": ("url", "path"),
}

# name     — the plugin name the entry publishes
# where    — "./sub" in-tree, or "github:owner/repo" style for another repo
# manifest — repo-relative path to the member's plugin.json, None if external
Member = namedtuple("Member", "name where manifest")


def load():
    """The parsed marketplace manifest."""
    with open(os.path.join(REPO, MARKETPLACE)) as f:
        return json.load(f)


def members():
    """Every marketplace entry as a Member. Raises SystemExit on an entry CI
    cannot make sense of: a missing required field, an unrecognised source
    form, or an in-tree source with no plugin manifest behind it."""
    entries = load().get("plugins")
    if not isinstance(entries, list) or not entries:
        raise SystemExit(f"{MARKETPLACE}: no plugins list")

    roster = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SystemExit(f"{MARKETPLACE}: entry {i} is not an object")
        # The schema requires name and source. description is optional there,
        # but an entry without one is a blank line in the /plugin browser, so
        # this marketplace requires it.
        for field in ("name", "source", "description"):
            if not entry.get(field):
                raise SystemExit(f"{MARKETPLACE}: entry {i} has no {field}")
        name, source = entry["name"], entry["source"]

        if isinstance(source, str):
            if not source.startswith("./"):
                raise SystemExit(
                    f"{name}: in-tree source must start with './', got {source!r}")
            sub = source[2:].strip("/")
            manifest = (sub + "/" if sub else "") + ".claude-plugin/plugin.json"
            if not os.path.isfile(os.path.join(REPO, manifest)):
                raise SystemExit(f"{name}: source {source!r} has no {manifest}")
            roster.append(Member(name, source, manifest))
            continue

        if not isinstance(source, dict):
            raise SystemExit(
                f"{name}: source must be a './' path or a source object")
        kind = source.get("source")
        if kind not in EXTERNAL_SOURCES:
            known = ", ".join(sorted(EXTERNAL_SOURCES))
            raise SystemExit(
                f"{name}: unknown source type {kind!r} (expected a './' path or one of {known})")
        missing = [k for k in EXTERNAL_SOURCES[kind] if not source.get(k)]
        if missing:
            raise SystemExit(
                f"{name}: {kind} source is missing {', '.join(missing)}")
        roster.append(
            Member(name, f"{kind}:{source.get('repo') or source['url']}", None))

    return roster
