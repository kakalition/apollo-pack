#!/usr/bin/env python3
"""Create and manage habits (daily, weekly quota, or fixed interval)."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def _apply_cadence(cadence: str, count: Any) -> int:
    if cadence not in _lib.CADENCE_KINDS:
        raise _lib.CommandError(
            "invalid_cadence", "cadence must be one of: %s" % ", ".join(_lib.CADENCE_KINDS)
        )
    if cadence == "daily":
        if count is not None:
            raise _lib.CommandError(
                "invalid_cadence", "--count is only valid for weekly or interval cadences"
            )
        return 1
    value = 1 if count is None else int(count)
    if value < 1:
        raise _lib.CommandError("invalid_input", "--count must be 1 or greater")
    return value


def cmd_add(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    name = (args.name or "").strip()
    if not name:
        raise _lib.CommandError("invalid_input", "habit name cannot be empty")
    count = _apply_cadence(args.cadence, args.count)
    start = (
        _lib.validate_date(args.start, "--start")
        if args.start
        else _lib.resolve_today(conn, args).isoformat()
    )
    end = _lib.validate_date(args.end, "--end") if args.end else None
    if end and end < start:
        raise _lib.CommandError("invalid_input", "--end must not be before --start")
    cur = conn.execute(
        "INSERT INTO habits (name, cadence_kind, cadence_count, start_date, end_date, notes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, args.cadence, count, start, end, args.notes),
    )
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (cur.lastrowid,)).fetchone()
    data = _lib.habit_dict(row)
    data["hint"] = "Log progress with checkins.py done NAME."
    return data


def cmd_list(conn: sqlite3.Connection, args: argparse.Namespace) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM habits"
    if not args.include_inactive:
        sql += " WHERE active = 1"
    sql += " ORDER BY name COLLATE NOCASE"
    return [_lib.habit_dict(row) for row in conn.execute(sql).fetchall()]


def cmd_show(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    data = _lib.habit_dict(habit)
    data["stats"] = _lib.habit_stats(
        conn, habit, _lib.resolve_today(conn, args), _lib.resolve_week_start(conn)
    )
    return data


def cmd_edit(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    updates: Dict[str, Any] = {}
    if args.cadence is not None:
        count = args.count if args.count is not None else int(habit["cadence_count"])
        updates["cadence_count"] = _apply_cadence(
            args.cadence, count if args.cadence != "daily" else None
        )
        updates["cadence_kind"] = args.cadence
    elif args.count is not None:
        if habit["cadence_kind"] == "daily":
            raise _lib.CommandError(
                "invalid_cadence", "--count is only valid for weekly or interval cadences"
            )
        if int(args.count) < 1:
            raise _lib.CommandError("invalid_input", "--count must be 1 or greater")
        updates["cadence_count"] = int(args.count)
    if args.start is not None:
        updates["start_date"] = _lib.validate_date(args.start, "--start")
    if args.end is not None:
        updates["end_date"] = _lib.validate_date(args.end, "--end") if args.end else None
    if args.notes is not None:
        updates["notes"] = args.notes
    if not updates:
        raise _lib.CommandError("invalid_input", "edit requires at least one field to change")
    start = updates.get("start_date", habit["start_date"])
    end = updates.get("end_date", habit["end_date"])
    if end and end < start:
        raise _lib.CommandError("invalid_input", "--end must not be before --start")
    assignments = ", ".join("%s = ?" % key for key in updates)
    conn.execute(
        "UPDATE habits SET %s WHERE id = ?" % assignments,
        tuple(updates.values()) + (habit["id"],),
    )
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit["id"],)).fetchone()
    return _lib.habit_dict(row)


def cmd_rename(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    name = (args.name or "").strip()
    if not name:
        raise _lib.CommandError("invalid_input", "new habit name cannot be empty")
    conn.execute("UPDATE habits SET name = ? WHERE id = ?", (name, habit["id"]))
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit["id"],)).fetchone()
    return _lib.habit_dict(row)


def _set_active(conn: sqlite3.Connection, habit: sqlite3.Row, active: int, note: str) -> Dict[str, Any]:
    conn.execute("UPDATE habits SET active = ? WHERE id = ?", (active, habit["id"]))
    row = conn.execute("SELECT * FROM habits WHERE id = ?", (habit["id"],)).fetchone()
    data = _lib.habit_dict(row)
    data["note"] = note
    return data


def cmd_pause(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    return _set_active(
        conn, habit, 0, "Pausing hides the habit from reports and due lists; history is kept."
    )


def cmd_resume(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    return _set_active(conn, habit, 1, "Resuming restores the habit to reports and due lists.")


def cmd_archive(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    return _set_active(
        conn, habit, 0, "Archiving is non-destructive: use delete only when history is unwanted."
    )


def cmd_delete(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    if not args.yes:
        raise _lib.CommandError(
            "invalid_input",
            "deleting %r also deletes its check-ins; re-run with --yes to confirm" % habit["name"],
        )
    removed = conn.execute(
        "SELECT COUNT(*) AS n FROM checkins WHERE habit_id = ?", (habit["id"],)
    ).fetchone()["n"]
    conn.execute("DELETE FROM habits WHERE id = ?", (habit["id"],))
    return {
        "deleted": True,
        "habit_id": habit["id"],
        "name": habit["name"],
        "checkins_removed": removed,
        "note": "Deleting a habit removes its check-ins; pausing or archiving keeps them.",
    }


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="habits.py", description="Create and manage habits.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser(
        "add",
        help="create a habit",
        description="Create a habit with a daily, weekly, or interval cadence.",
        parents=[common],
    )
    add.add_argument("--name", required=True)
    add.add_argument("--cadence", required=True, choices=list(_lib.CADENCE_KINDS))
    add.add_argument("--count", type=int, help="weekly times-per-week or interval days")
    add.add_argument("--start", help="first expected day YYYY-MM-DD (default today)")
    add.add_argument("--end", help="optional last expected day YYYY-MM-DD")
    add.add_argument("--notes")
    add.set_defaults(func=cmd_add, verb="add")

    listing = subparsers.add_parser(
        "list",
        help="list habits",
        description="List habits (active by default).",
        parents=[common],
    )
    listing.add_argument("--include-inactive", action="store_true")
    listing.set_defaults(func=cmd_list, verb="list")

    show = subparsers.add_parser(
        "show",
        help="show one habit with its stats",
        description="Show one habit and its streak and adherence stats.",
        parents=[common],
    )
    show.add_argument("habit", help="habit id or name")
    show.set_defaults(func=cmd_show, verb="show")

    edit = subparsers.add_parser(
        "edit",
        help="edit a habit",
        description="Change a habit's cadence, count, dates, or notes.",
        parents=[common],
    )
    edit.add_argument("habit", help="habit id or name")
    edit.add_argument("--cadence", choices=list(_lib.CADENCE_KINDS))
    edit.add_argument("--count", type=int)
    edit.add_argument("--start")
    edit.add_argument("--end")
    edit.add_argument("--notes")
    edit.set_defaults(func=cmd_edit, verb="edit")

    rename = subparsers.add_parser(
        "rename",
        help="rename a habit",
        description="Rename a habit.",
        parents=[common],
    )
    rename.add_argument("habit", help="habit id or name")
    rename.add_argument("--name", required=True)
    rename.set_defaults(func=cmd_rename, verb="rename")

    pause = subparsers.add_parser(
        "pause",
        help="pause a habit",
        description="Pause a habit; history is kept.",
        parents=[common],
    )
    pause.add_argument("habit", help="habit id or name")
    pause.set_defaults(func=cmd_pause, verb="pause")

    resume = subparsers.add_parser(
        "resume",
        help="resume a paused habit",
        description="Resume a paused habit.",
        parents=[common],
    )
    resume.add_argument("habit", help="habit id or name")
    resume.set_defaults(func=cmd_resume, verb="resume")

    archive = subparsers.add_parser(
        "archive",
        help="archive a habit (non-destructive)",
        description="Archive a habit without deleting its check-ins.",
        parents=[common],
    )
    archive.add_argument("habit", help="habit id or name")
    archive.set_defaults(func=cmd_archive, verb="archive")

    delete = subparsers.add_parser(
        "delete",
        help="delete a habit and its check-ins",
        description="Delete a habit and all of its check-ins (requires --yes).",
        parents=[common],
    )
    delete.add_argument("habit", help="habit id or name")
    delete.add_argument("--yes", action="store_true", help="confirm the cascade delete")
    delete.set_defaults(func=cmd_delete, verb="delete")

    return parser


def main() -> None:
    _lib.run_script("habits", build_parser())


if __name__ == "__main__":
    main()
