#!/usr/bin/env python3
"""Show or change journal settings (timezone, week start, limit, review prompt)."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def _counts(conn: sqlite3.Connection) -> Dict[str, int]:
    return {
        "entries": conn.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"],
        "active_days": conn.execute(
            "SELECT COUNT(DISTINCT entry_date) AS n FROM entries"
        ).fetchone()["n"],
    }


def cmd_show(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "settings": _lib.effective_settings(conn),
        "stored": _lib.settings_snapshot(conn),
        "env_overrides": _lib.active_env_overrides(),
        "fts_enabled": _lib.fts_enabled(conn),
        "initialized": _lib.get_meta(conn, "initialized") == "1",
        "db": str(_lib.resolve_db_path(args.db)),
        "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "counts": _counts(conn),
    }


def cmd_get(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    if not args.key:
        return {"settings": _lib.effective_settings(conn)}
    key = args.key.strip()
    if key in _lib.SETTING_DEFAULTS:
        return {"key": key, "value": _lib.effective_setting(conn, key)}
    if key in ("fts_enabled", "fts"):
        return {"key": "fts_enabled", "value": _lib.fts_enabled(conn)}
    if key in ("db", "db_path"):
        return {"key": "db", "value": str(_lib.resolve_db_path(args.db))}
    if key in ("schema_version", "user_version"):
        return {"key": "schema_version", "value": conn.execute("PRAGMA user_version").fetchone()[0]}
    raise _lib.CommandError("not_found", "no setting named %r" % key)


def cmd_set(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    changed: Dict[str, Any] = {}
    if args.tz is not None:
        _lib.tzinfo_for(args.tz)
        _lib.set_meta(conn, "tz", args.tz)
        changed["tz"] = args.tz
    if args.week_start is not None:
        value = args.week_start.strip().lower()
        if value not in _lib.WEEK_STARTS:
            raise _lib.CommandError(
                "invalid_input", "--week-start must be one of: %s" % ", ".join(_lib.WEEK_STARTS)
            )
        _lib.set_meta(conn, "week_start", value)
        changed["week_start"] = value
    if args.default_limit is not None:
        if int(args.default_limit) < 1:
            raise _lib.CommandError("invalid_input", "--default-limit must be 1 or greater")
        _lib.set_meta(conn, "default_limit", str(int(args.default_limit)))
        changed["default_limit"] = str(int(args.default_limit))
    if args.review_prompt is not None:
        prompt = args.review_prompt.strip()
        if not prompt:
            raise _lib.CommandError("invalid_input", "--review-prompt cannot be empty")
        _lib.set_meta(conn, "review_prompt", prompt)
        changed["review_prompt"] = prompt
    if not changed:
        raise _lib.CommandError(
            "invalid_input",
            "set requires at least one of --tz, --week-start, --default-limit, or --review-prompt",
        )
    _lib.set_meta(conn, "initialized", "1")
    return {
        "changed": changed,
        "settings": _lib.effective_settings(conn),
        "stored": _lib.settings_snapshot(conn),
    }


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="settings.py", description="Show or change journal settings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser(
        "show",
        help="show settings, search mode, and counts",
        description="Show effective settings, stored settings, and row counts.",
        parents=[common],
    )
    show.set_defaults(func=cmd_show, verb="show")

    get = subparsers.add_parser(
        "get",
        help="read one setting or all settings",
        description="Read a single effective setting or the whole settings map.",
        parents=[common],
    )
    get.add_argument("--key", help="setting name, e.g. tz, week_start, default_limit")
    get.set_defaults(func=cmd_get, verb="get")

    set_cmd = subparsers.add_parser(
        "set",
        help="change one or more settings",
        description="Persist one or more settings (timezone, week start, limit, review prompt).",
        parents=[common],
    )
    set_cmd.add_argument("--week-start", dest="week_start", choices=list(_lib.WEEK_STARTS))
    set_cmd.add_argument("--default-limit", dest="default_limit", type=int)
    set_cmd.add_argument("--review-prompt", dest="review_prompt")
    set_cmd.set_defaults(func=cmd_set, verb="set")

    return parser


def main() -> None:
    _lib.run_script("settings", build_parser())


if __name__ == "__main__":
    main()
