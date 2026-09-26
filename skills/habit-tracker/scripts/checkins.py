#!/usr/bin/env python3
"""Log daily check-ins for habits: done, skip (neutral), or fail."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def _checkin_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "habit_id": row["habit_id"],
        "date": row["date"],
        "status": row["status"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def _record(conn: sqlite3.Connection, args: argparse.Namespace, status: str) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    when = (
        _lib.validate_date(args.date, "--date") if args.date else _lib.resolve_today(conn, args).isoformat()
    )
    cur = conn.execute(
        "INSERT INTO checkins (habit_id, date, status, note) VALUES (?, ?, ?, ?)",
        (habit["id"], when, status, args.note),
    )
    row = conn.execute("SELECT * FROM checkins WHERE id = ?", (cur.lastrowid,)).fetchone()
    data = _checkin_dict(row)
    data["habit"] = habit["name"]
    return data


def cmd_done(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    return _record(conn, args, "done")


def cmd_skip(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    data = _record(conn, args, "skip")
    data["note"] = data.get("note") or "skip is neutral: it breaks neither streak nor adherence"
    return data


def cmd_fail(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    return _record(conn, args, "fail")


def cmd_undo(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    when = (
        _lib.validate_date(args.date, "--date") if args.date else _lib.resolve_today(conn, args).isoformat()
    )
    cur = conn.execute(
        "DELETE FROM checkins WHERE habit_id = ? AND date = ?", (habit["id"], when)
    )
    if cur.rowcount == 0:
        raise _lib.CommandError(
            "not_found", "no check-in for %r on %s" % (habit["name"], when)
        )
    return {"removed": cur.rowcount, "habit": habit["name"], "date": when}


def cmd_list(conn: sqlite3.Connection, args: argparse.Namespace) -> List[Dict[str, Any]]:
    sql = (
        "SELECT c.*, h.name AS habit FROM checkins c "
        "JOIN habits h ON h.id = c.habit_id"
    )
    clauses: List[str] = []
    params: List[Any] = []
    if args.habit:
        habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
        clauses.append("c.habit_id = ?")
        params.append(habit["id"])
    if args.from_date:
        clauses.append("c.date >= ?")
        params.append(_lib.validate_date(args.from_date, "--from"))
    if args.to_date:
        clauses.append("c.date <= ?")
        params.append(_lib.validate_date(args.to_date, "--to"))
    if args.status:
        clauses.append("c.status = ?")
        params.append(args.status)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    limit = 50 if args.limit is None else max(0, int(args.limit))
    sql += " ORDER BY c.date DESC, c.id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": row["id"],
            "habit": row["habit"],
            "habit_id": row["habit_id"],
            "date": row["date"],
            "status": row["status"],
            "note": row["note"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _add_date_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("habit", help="habit id or name")
    parser.add_argument("--date", help="check-in date YYYY-MM-DD (default today)")
    parser.add_argument("--note")


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="checkins.py", description="Log habit check-ins.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    done = subparsers.add_parser(
        "done", help="mark a habit done", description="Record a done check-in.", parents=[common]
    )
    _add_date_flags(done)
    done.set_defaults(func=cmd_done, verb="done")

    skip = subparsers.add_parser(
        "skip",
        help="mark a habit skipped (neutral)",
        description="Record a neutral skip that breaks neither streak nor adherence.",
        parents=[common],
    )
    _add_date_flags(skip)
    skip.set_defaults(func=cmd_skip, verb="skip")

    fail = subparsers.add_parser(
        "fail", help="mark a habit failed", description="Record a fail check-in.", parents=[common]
    )
    _add_date_flags(fail)
    fail.set_defaults(func=cmd_fail, verb="fail")

    undo = subparsers.add_parser(
        "undo",
        help="remove a check-in",
        description="Remove a habit's check-in for a date.",
        parents=[common],
    )
    undo.add_argument("habit", help="habit id or name")
    undo.add_argument("--date", help="check-in date YYYY-MM-DD (default today)")
    undo.set_defaults(func=cmd_undo, verb="undo")

    listing = subparsers.add_parser(
        "list", help="list check-ins", description="List check-ins with filters.", parents=[common]
    )
    listing.add_argument("--habit", help="filter by habit id or name")
    listing.add_argument("--from", dest="from_date")
    listing.add_argument("--to", dest="to_date")
    listing.add_argument("--status", choices=list(_lib.STATUSES))
    listing.add_argument("--limit", type=int, help="maximum rows (default 50)")
    listing.set_defaults(func=cmd_list, verb="list")

    return parser


def main() -> None:
    _lib.run_script("checkins", build_parser())


if __name__ == "__main__":
    main()
