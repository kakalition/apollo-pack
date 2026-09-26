#!/usr/bin/env python3
"""Manage source materials and their cadence.

A material is a named source (a book, a paper, a feed) with a delivery cadence.
Chunks of a material are produced by ``ingest.py`` and delivered by
``insights.py``.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def _validate_cadence(count: int, period: str) -> None:
    if count < 1:
        raise _lib.CommandError("invalid_input", "cadence count must be 1 or greater")
    if period == "week" and count > 7:
        raise _lib.CommandError("invalid_input", "a weekly cadence cannot exceed 7 days")
    if period not in _lib.PERIODS:
        raise _lib.CommandError("invalid_input", "cadence period must be one of: %s" % ", ".join(_lib.PERIODS))


def cmd_add(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    name = (args.name or "").strip()
    if not name:
        raise _lib.CommandError("invalid_input", "material name cannot be empty")
    count = args.cadence_count if args.cadence_count is not None else 1
    period = args.cadence_period or "day"
    _validate_cadence(count, period)
    priority = args.priority if args.priority is not None else 100
    existing = conn.execute(
        "SELECT id FROM materials WHERE name = ? COLLATE NOCASE", (name,)
    ).fetchone()
    if existing:
        raise _lib.CommandError("conflict", "a material named %r already exists" % name)
    conn.execute(
        "INSERT INTO materials (name, source_path, cadence_count, cadence_period, priority) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, args.source, count, period, priority),
    )
    row = _lib.resolve_material(conn, name)
    data = _lib.material_dict(conn, row, detail=True)
    data["hint"] = "Add content with ingest.py ingest <file> --material %r." % name
    return data


def cmd_list(conn: sqlite3.Connection, home, args: argparse.Namespace) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM materials"
    if not args.include_archived:
        sql += " WHERE active = 1"
    sql += " ORDER BY priority, name COLLATE NOCASE"
    return [_lib.material_dict(conn, row) for row in conn.execute(sql)]


def cmd_show(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    row = _lib.resolve_material(conn, args.material, allow_archived=True)
    data = _lib.material_dict(conn, row, detail=True)
    chunks = conn.execute(
        "SELECT ordinal, token_est, delivered_count, last_delivered_at FROM chunks "
        "WHERE material_id = ? ORDER BY ordinal LIMIT 20",
        (row["id"],),
    ).fetchall()
    data["chunks_preview"] = [dict(chunk) for chunk in chunks]
    data["weekdays"] = (
        _lib.weekly_weekdays(int(row["id"]), int(row["cadence_count"]))
        if row["cadence_period"] == "week"
        else []
    )
    return data


def cmd_cadence(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    row = _lib.resolve_material(conn, args.material)
    count = args.count if args.count is not None else int(row["cadence_count"])
    period = args.period or row["cadence_period"]
    _validate_cadence(count, period)
    conn.execute(
        "UPDATE materials SET cadence_count = ?, cadence_period = ? WHERE id = ?",
        (count, period, row["id"]),
    )
    updated = _lib.resolve_material(conn, args.material)
    data = _lib.material_dict(conn, updated)
    data["weekdays"] = (
        _lib.weekly_weekdays(int(updated["id"]), count) if period == "week" else []
    )
    return data


def cmd_priority(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    row = _lib.resolve_material(conn, args.material)
    if args.value is None:
        raise _lib.CommandError("usage", "priority requires --value N")
    conn.execute("UPDATE materials SET priority = ? WHERE id = ?", (int(args.value), row["id"]))
    return _lib.material_dict(conn, _lib.resolve_material(conn, args.material))


def cmd_rename(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    row = _lib.resolve_material(conn, args.material, allow_archived=True)
    new_name = (args.name or "").strip()
    if not new_name:
        raise _lib.CommandError("invalid_input", "new name cannot be empty")
    clash = conn.execute(
        "SELECT id FROM materials WHERE name = ? COLLATE NOCASE AND id != ?",
        (new_name, row["id"]),
    ).fetchone()
    if clash:
        raise _lib.CommandError("conflict", "a material named %r already exists" % new_name)
    conn.execute("UPDATE materials SET name = ? WHERE id = ?", (new_name, row["id"]))
    return _lib.material_dict(conn, _lib.resolve_material(conn, new_name, allow_archived=True))


def cmd_archive(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    row = _lib.resolve_material(conn, args.material, allow_archived=True)
    active = 1 if args.unarchive else 0
    conn.execute("UPDATE materials SET active = ? WHERE id = ?", (active, row["id"]))
    return _lib.material_dict(conn, _lib.resolve_material(conn, args.material, allow_archived=True))


def cmd_delete(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    row = _lib.resolve_material(conn, args.material, allow_archived=True)
    chunk_count = conn.execute(
        "SELECT COUNT(*) AS n FROM chunks WHERE material_id = ?", (row["id"],)
    ).fetchone()["n"]
    delivery_count = conn.execute(
        "SELECT COUNT(*) AS n FROM deliveries WHERE material_id = ?", (row["id"],)
    ).fetchone()["n"]
    if args.dry_run:
        return {
            "dry_run": True,
            "material_id": row["id"],
            "name": row["name"],
            "chunks_removed": int(chunk_count),
            "deliveries_removed": int(delivery_count),
        }
    conn.execute("DELETE FROM chunks WHERE material_id = ?", (row["id"],))
    conn.execute("DELETE FROM day_slots WHERE material_id = ?", (row["id"],))
    conn.execute("DELETE FROM deliveries WHERE material_id = ?", (row["id"],))
    conn.execute("DELETE FROM materials WHERE id = ?", (row["id"],))
    vectors_removed = 0
    if _lib.deps_status().get("chromadb"):
        try:
            collection = _lib.open_collection(home)
            _lib.chroma_delete_material(collection, int(row["id"]))
            vectors_removed = int(chunk_count)
        except _lib.CommandError:
            vectors_removed = 0
    return {
        "deleted": True,
        "material_id": row["id"],
        "name": row["name"],
        "chunks_removed": int(chunk_count),
        "deliveries_removed": int(delivery_count),
        "vectors_removed": vectors_removed,
    }


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="materials.py", description="Manage daily-insight materials.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = _lib.add_subparser(subparsers, "add", "add a material", [common])
    add.add_argument("--name", required=True)
    add.add_argument("--cadence-count", type=int, default=1)
    add.add_argument("--cadence-period", choices=list(_lib.PERIODS), default="day")
    add.add_argument("--priority", type=int, default=100)
    add.add_argument("--source", help="source path or URL for reference")
    add.set_defaults(func=cmd_add)

    listing = _lib.add_subparser(subparsers, "list", "list materials", [common])
    listing.add_argument("--include-archived", action="store_true")
    listing.set_defaults(func=cmd_list)

    show = _lib.add_subparser(subparsers, "show", "show one material", [common])
    show.add_argument("material", help="material id or name")
    show.set_defaults(func=cmd_show)

    cadence = _lib.add_subparser(subparsers, "cadence", "set a material cadence", [common])
    cadence.add_argument("material", help="material id or name")
    cadence.add_argument("--count", type=int)
    cadence.add_argument("--period", choices=list(_lib.PERIODS))
    cadence.set_defaults(func=cmd_cadence)

    priority = _lib.add_subparser(subparsers, "priority", "set material priority", [common])
    priority.add_argument("material", help="material id or name")
    priority.add_argument("--value", type=int)
    priority.set_defaults(func=cmd_priority)

    rename = _lib.add_subparser(subparsers, "rename", "rename a material", [common])
    rename.add_argument("material", help="material id or name")
    rename.add_argument("--name", required=True)
    rename.set_defaults(func=cmd_rename)

    archive = _lib.add_subparser(subparsers, "archive", "archive or restore a material", [common])
    archive.add_argument("material", help="material id or name")
    archive.add_argument("--unarchive", action="store_true")
    archive.set_defaults(func=cmd_archive)

    delete = _lib.add_subparser(subparsers, "delete", "delete a material and its chunks", [common])
    delete.add_argument("material", help="material id or name")
    delete.add_argument("--dry-run", action="store_true")
    delete.set_defaults(func=cmd_delete)

    return parser


def main() -> None:
    _lib.run_script("materials", build_parser())


if __name__ == "__main__":
    main()
