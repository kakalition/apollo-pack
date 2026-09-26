#!/usr/bin/env python3
"""Reports: coverage per material, delivery history, and overall stats."""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def cmd_coverage(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    sql = "SELECT * FROM materials"
    if not args.include_archived:
        sql += " WHERE active = 1"
    sql += " ORDER BY priority, name COLLATE NOCASE"
    materials: List[Dict[str, Any]] = []
    total_chunks = 0
    total_delivered = 0
    for row in conn.execute(sql):
        total = int(row["chunk_count"] or 0)
        delivered = conn.execute(
            "SELECT COUNT(DISTINCT chunk_id) AS n FROM deliveries WHERE material_id = ?",
            (row["id"],),
        ).fetchone()["n"]
        coverage = round((delivered / total) * 100.0, 1) if total else 0.0
        total_chunks += total
        total_delivered += int(delivered)
        materials.append(
            {
                "id": row["id"],
                "name": row["name"],
                "active": bool(row["active"]),
                "cadence": "%d/%s" % (int(row["cadence_count"]), row["cadence_period"]),
                "chunk_count": total,
                "delivered_chunks": int(delivered),
                "coverage_pct": coverage,
                "never_touched": total > 0 and int(delivered) == 0,
            }
        )
    overall = round((total_delivered / total_chunks) * 100.0, 1) if total_chunks else 0.0
    return {
        "materials": materials,
        "material_count": len(materials),
        "chunks_total": total_chunks,
        "delivered_chunks": total_delivered,
        "coverage_pct": overall,
        "never_touched": [m["name"] for m in materials if m["never_touched"]],
    }


def cmd_history(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    limit = args.limit if args.limit is not None else 20
    if limit < 1:
        raise _lib.CommandError("invalid_input", "--limit must be 1 or greater")
    sql = (
        "SELECT d.*, m.name AS material_name, c.ordinal AS ordinal "
        "FROM deliveries d "
        "JOIN materials m ON m.id = d.material_id "
        "LEFT JOIN chunks c ON c.id = d.chunk_id"
    )
    params: List[Any] = []
    clauses = []
    if args.material:
        material = _lib.resolve_material(conn, args.material, allow_archived=True)
        clauses.append("d.material_id = ?")
        params.append(material["id"])
    if args.date:
        clauses.append("d.date = ?")
        params.append(_lib.validate_date(args.date))
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY d.delivered_at DESC, d.id DESC LIMIT ?"
    params.append(int(limit))
    items = []
    for row in conn.execute(sql, params):
        text = row["insight_text"]
        items.append(
            {
                "date": row["date"],
                "slot_index": row["slot_index"],
                "material_id": row["material_id"],
                "material": row["material_name"],
                "chunk_ordinal": row["ordinal"],
                "delivered_at": row["delivered_at"],
                "generated": bool(row["generated"]),
                "insight_preview": (text[:240] + "…") if text and len(text) > 240 else text,
            }
        )
    return {"count": len(items), "deliveries": items}


def cmd_stats(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    today = _lib.resolve_today(conn, args)
    today_str = today.isoformat()
    counts = {
        "materials": conn.execute("SELECT COUNT(*) AS n FROM materials WHERE active = 1").fetchone()["n"],
        "materials_archived": conn.execute("SELECT COUNT(*) AS n FROM materials WHERE active = 0").fetchone()["n"],
        "chunks": conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"],
        "deliveries": conn.execute("SELECT COUNT(*) AS n FROM deliveries").fetchone()["n"],
        "delivery_days": conn.execute("SELECT COUNT(DISTINCT date) AS n FROM deliveries").fetchone()["n"],
    }
    remaining_today = conn.execute(
        "SELECT COUNT(*) AS n FROM day_slots WHERE date = ? AND status = 'planned'", (today_str,)
    ).fetchone()["n"]
    delivered_today = conn.execute(
        "SELECT COUNT(*) AS n FROM deliveries WHERE date = ?", (today_str,)
    ).fetchone()["n"]
    return {
        "date": today_str,
        "budget": _lib.setting_int(conn, "budget", _lib.DEFAULT_BUDGET),
        "wake": _lib.effective_setting(conn, "wake") or _lib.DEFAULT_WAKE,
        "strategy": _lib.effective_setting(conn, "strategy") or _lib.DEFAULT_STRATEGY,
        "counts": counts,
        "today": {"delivered": int(delivered_today), "remaining": int(remaining_today)},
        "first_delivery": (
            conn.execute("SELECT MIN(delivered_at) AS v FROM deliveries").fetchone()["v"]
        ),
        "last_delivery": (
            conn.execute("SELECT MAX(delivered_at) AS v FROM deliveries").fetchone()["v"]
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="reports.py", description="Daily-insight reports.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    coverage = _lib.add_subparser(subparsers, "coverage", "coverage per material", [common])
    coverage.add_argument("--include-archived", action="store_true")
    coverage.set_defaults(func=cmd_coverage)

    history = _lib.add_subparser(subparsers, "history", "recent delivered insights", [common])
    history.add_argument("--limit", type=int, help="how many deliveries to show (default 20)")
    history.add_argument("--material", help="filter by material id or name")
    history.add_argument("--date", help="filter by date YYYY-MM-DD")
    history.set_defaults(func=cmd_history)

    stats = _lib.add_subparser(subparsers, "stats", "overall counts and today's progress", [common])
    stats.set_defaults(func=cmd_stats)

    return parser


def main() -> None:
    _lib.run_script("reports", build_parser())


if __name__ == "__main__":
    main()
