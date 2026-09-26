#!/usr/bin/env python3
"""Show or change habit-tracker settings (timezone, week start, default view)."""
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
        "habits": conn.execute("SELECT COUNT(*) AS n FROM habits").fetchone()["n"],
        "active_habits": conn.execute(
            "SELECT COUNT(*) AS n FROM habits WHERE active = 1"
        ).fetchone()["n"],
        "checkins": conn.execute("SELECT COUNT(*) AS n FROM checkins").fetchone()["n"],
    }


def cmd_show(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "settings": _lib.effective_settings(conn),
        "stored": _lib.settings_snapshot(conn),
        "env_overrides": _lib.active_env_overrides(),
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
    if key in ("db", "db_path"):
        return {"key": "db", "value": str(_lib.resolve_db_path(args.db))}
    if key in ("schema_version", "user_version"):
        return {"key": "schema_version", "value": conn.execute("PRAGMA user_version").fetchone()[0]}
    raise _lib.CommandError("not_found", "no setting named %r" % key)


def cmd_set(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    changed: Dict[str, str] = {}
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
    if args.default_view is not None:
        value = args.default_view.strip().lower()
        if value not in _lib.VIEWS:
            raise _lib.CommandError(
                "invalid_input",
                "--default-view must be one of: %s" % ", ".join(_lib.VIEWS),
            )
        _lib.set_meta(conn, "default_view", value)
        changed["default_view"] = value
    if not changed:
        raise _lib.CommandError(
            "invalid_input",
            "set requires at least one of --tz, --week-start, or --default-view",
        )
    _lib.set_meta(conn, "initialized", "1")
    return {
        "changed": changed,
        "settings": _lib.effective_settings(conn),
        "stored": _lib.settings_snapshot(conn),
    }


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(
        prog="settings.py", description="Show or change habit-tracker settings."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser(
        "show",
        help="show settings, database path, and counts",
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
    get.add_argument("--key", help="setting name, e.g. tz, week_start, default_view")
    get.set_defaults(func=cmd_get, verb="get")

    set_cmd = subparsers.add_parser(
        "set",
        help="change one or more settings",
        description="Persist one or more settings (timezone, week start, default view).",
        parents=[common],
    )
    set_cmd.add_argument("--week-start", dest="week_start", choices=list(_lib.WEEK_STARTS))
    set_cmd.add_argument("--default-view", dest="default_view", choices=list(_lib.VIEWS))
    set_cmd.set_defaults(func=cmd_set, verb="set")

    return parser


def main() -> None:
    _lib.run_script("settings", build_parser())


if __name__ == "__main__":
    main()
