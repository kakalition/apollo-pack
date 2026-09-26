#!/usr/bin/env python3
"""Write and read journal entries, with FTS5 search and a LIKE fallback."""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def _read_body(args: argparse.Namespace) -> str:
    if args.body is not None:
        return args.body
    if args.file:
        try:
            with open(os.path.expanduser(args.file), "r", encoding="utf-8") as handle:
                return handle.read()
        except FileNotFoundError:
            raise _lib.CommandError("not_found", "no file at %r" % args.file)
        except OSError as exc:
            raise _lib.CommandError("invalid_input", "could not read %r: %s" % (args.file, exc))
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise _lib.CommandError("invalid_input", "provide --body, --file, or pipe text on stdin")


def cmd_add(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    body = _read_body(args)
    if not body or not body.strip():
        raise _lib.CommandError("invalid_input", "entry body cannot be empty")
    when = (
        _lib.validate_date(args.date, "--date") if args.date else _lib.resolve_today(conn, args).isoformat()
    )
    cur = conn.execute(
        "INSERT INTO entries (entry_date, title, body, word_count, source) VALUES (?, ?, ?, ?, ?)",
        (when, args.title, body, _lib.word_count(body), args.source),
    )
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)).fetchone()
    data = _lib.entry_dict(row)
    data["fts_enabled"] = _lib.fts_enabled(conn)
    return data


def cmd_list(conn: sqlite3.Connection, args: argparse.Namespace) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM entries"
    clauses: List[str] = []
    params: List[Any] = []
    if args.from_date:
        clauses.append("entry_date >= ?")
        params.append(_lib.validate_date(args.from_date, "--from"))
    if args.to_date:
        clauses.append("entry_date <= ?")
        params.append(_lib.validate_date(args.to_date, "--to"))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    order = "ASC" if (args.order or "desc") == "asc" else "DESC"
    limit = args.limit if args.limit is not None else _lib.setting_int(conn, "default_limit", 20)
    sql += " ORDER BY entry_date %s, id %s LIMIT ?" % (order, order)
    params.append(max(0, int(limit)))
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [_lib.entry_dict(row) for row in rows]


def cmd_show(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    return _lib.entry_dict(_lib.resolve_entry(conn, args.entry))


def cmd_edit(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    row = _lib.resolve_entry(conn, args.entry)
    updates: Dict[str, Any] = {}
    if args.body is not None:
        if not args.body.strip():
            raise _lib.CommandError("invalid_input", "entry body cannot be empty")
        updates["body"] = args.body
        updates["word_count"] = _lib.word_count(args.body)
    if args.title is not None:
        updates["title"] = args.title
    if args.date is not None:
        updates["entry_date"] = _lib.validate_date(args.date, "--date")
    if not updates:
        raise _lib.CommandError("invalid_input", "edit requires at least one of --body, --title, or --date")
    assignments = ", ".join("%s = ?" % key for key in updates)
    conn.execute(
        "UPDATE entries SET %s, updated_at = datetime('now') WHERE id = ?" % assignments,
        tuple(updates.values()) + (row["id"],),
    )
    updated = conn.execute("SELECT * FROM entries WHERE id = ?", (row["id"],)).fetchone()
    return _lib.entry_dict(updated)


def cmd_delete(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    row = _lib.resolve_entry(conn, args.entry)
    conn.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
    return {"deleted": True, "id": row["id"], "note": "The entry is removed from search as well."}


def _fts_query(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_]+", text or "")
    if not tokens:
        raise _lib.CommandError("invalid_input", "search query has no searchable terms")
    return " ".join('"%s"' % token for token in tokens)


def cmd_search(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    query = (args.query or "").strip()
    if not query:
        raise _lib.CommandError("invalid_input", "search query cannot be empty")
    limit = args.limit if args.limit is not None else _lib.setting_int(conn, "default_limit", 20)
    limit = max(0, int(limit))
    enabled = _lib.ensure_fts(conn)
    from_date = _lib.validate_date(args.from_date, "--from") if args.from_date else None
    to_date = _lib.validate_date(args.to_date, "--to") if args.to_date else None
    rows: List[sqlite3.Row] = []
    if enabled:
        match = _fts_query(query)
        sql = (
            "SELECT e.* FROM entries_fts f JOIN entries e ON e.id = f.rowid "
            "WHERE entries_fts MATCH ?"
        )
        params: List[Any] = [match]
        if from_date:
            sql += " AND e.entry_date >= ?"
            params.append(from_date)
        if to_date:
            sql += " AND e.entry_date <= ?"
            params.append(to_date)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            rows = conn.execute(sql, tuple(params)).fetchall()
        except sqlite3.OperationalError:
            enabled = False
    if not enabled:
        like = "%" + query + "%"
        sql = "SELECT * FROM entries WHERE (body LIKE ? OR title LIKE ?)"
        params = [like, like]
        if from_date:
            sql += " AND entry_date >= ?"
            params.append(from_date)
        if to_date:
            sql += " AND entry_date <= ?"
            params.append(to_date)
        sql += " ORDER BY entry_date DESC, id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, tuple(params)).fetchall()
    return {
        "query": query,
        "fts": enabled,
        "count": len(rows),
        "entries": [_lib.entry_dict(row) for row in rows],
    }


def _add_date_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--from", dest="from_date")
    parser.add_argument("--to", dest="to_date")
    parser.add_argument("--limit", type=int)


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="entries.py", description="Write and read journal entries.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser(
        "add",
        help="add an entry from text, a file, or stdin",
        description="Add an entry; the body comes from --body, --file, or piped stdin.",
        parents=[common],
    )
    add.add_argument("--body")
    add.add_argument("--file")
    add.add_argument("--title")
    add.add_argument("--date", help="entry date YYYY-MM-DD (default today)")
    add.add_argument("--source", help="free-text origin, e.g. chat or cli")
    add.set_defaults(func=cmd_add, verb="add")

    listing = subparsers.add_parser(
        "list",
        help="list entries",
        description="List entries with optional date range, order, and limit.",
        parents=[common],
    )
    _add_date_flags(listing)
    listing.add_argument("--order", choices=list(_lib.ORDERS), default="desc")
    listing.set_defaults(func=cmd_list, verb="list")

    show = subparsers.add_parser(
        "show", help="show one entry", description="Show one entry by id.", parents=[common]
    )
    show.add_argument("entry")
    show.set_defaults(func=cmd_show, verb="show")

    edit = subparsers.add_parser(
        "edit",
        help="edit an entry",
        description="Change an entry's body, title, or date; reindexes the full-text index.",
        parents=[common],
    )
    edit.add_argument("entry")
    edit.add_argument("--body")
    edit.add_argument("--title")
    edit.add_argument("--date")
    edit.set_defaults(func=cmd_edit, verb="edit")

    delete = subparsers.add_parser(
        "delete", help="delete an entry", description="Delete an entry by id.", parents=[common]
    )
    delete.add_argument("entry")
    delete.set_defaults(func=cmd_delete, verb="delete")

    search = subparsers.add_parser(
        "search",
        help="search entries",
        description="Search bodies and titles (FTS5 when available, LIKE otherwise).",
        parents=[common],
    )
    search.add_argument("query")
    _add_date_flags(search)
    search.set_defaults(func=cmd_search, verb="search")

    return parser


def main() -> None:
    _lib.run_script("entries", build_parser())


if __name__ == "__main__":
    main()
