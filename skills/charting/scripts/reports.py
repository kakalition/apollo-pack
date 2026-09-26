#!/usr/bin/env python3
"""Read-only reporting for charting: render history and PNG introspection.

``history`` and ``show`` read the local render log. ``inspect`` reads an
existing PNG's IHDR header (dimensions, bit depth, color type) with the standard
library only — no Pillow. ``storage`` summarizes the data root. Nothing here
writes.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _lib


def _render_row(row: sqlite3.Row, *, detail: bool = False) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": row["id"],
        "chart_id": row["chart_id"],
        "name": row["name"],
        "out": row["out_path"],
        "width": row["width_px"],
        "height": row["height_px"],
        "scale": row["scale"],
        "bytes": row["bytes"],
        "sha256": (row["sha256"] or "")[:16],
        "rendered_at": row["rendered_at"],
    }
    if detail:
        data["sha256"] = row["sha256"]
        data["warnings"] = [w for w in (row["warnings"] or "").split("; ") if w]
    return data


def cmd_history(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if args.doc:
        rows = conn.execute(
            "SELECT * FROM renders WHERE name = ? ORDER BY id DESC LIMIT ?", (args.doc, args.limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM renders ORDER BY id DESC LIMIT ?", (args.limit,)).fetchall()
    renders = [_render_row(row, detail=args.detail) for row in rows]
    return {
        "count": len(renders),
        "read_only": True,
        "renders": renders,
        "latest": renders[0] if renders else None,
    }


def cmd_show(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    row = conn.execute("SELECT * FROM renders WHERE id = ?", (args.render_id,)).fetchone()
    if row is None:
        raise _lib.CommandError("not_found", "no render with id %s" % args.render_id)
    return _render_row(row, detail=True)


def cmd_storage(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    charts = conn.execute("SELECT COUNT(*) AS n FROM charts").fetchone()["n"]
    renders = conn.execute("SELECT COUNT(*) AS n FROM renders").fetchone()["n"]
    output_dir = _lib.resolve_output_dir(conn, home)
    return {
        "home": str(home),
        "db": str(_lib.resolve_db_path(home)),
        "output": str(output_dir),
        "tmp": str(_lib.resolve_tmp_path(home)),
        "charts": int(charts),
        "renders": int(renders),
        "images": len([p for p in output_dir.glob("*.png") if p.is_file()]) if output_dir.is_dir() else 0,
        "dependencies": _lib.dependency_report(),
    }


def cmd_inspect(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    path = Path(args.file).expanduser()
    if not path.is_file():
        raise _lib.CommandError("not_found", "PNG not found: %s" % path)
    payload: Dict[str, Any] = {
        "file": str(path),
        "bytes": path.stat().st_size,
        "sha256": _lib.sha256_file(path),
    }
    payload.update(_lib.png_info(path))
    return payload


def cmd_stats(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    totals = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS b FROM renders").fetchone()
    return {
        "renders": int(totals["n"]),
        "total_bytes": int(totals["b"]),
        "read_only": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reports.py", description="Report on charting state and PNGs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    history = subparsers.add_parser("history", help="list recent renders", parents=[_lib.common_parser()])
    history.add_argument("--limit", type=int, default=20, help="maximum rows (default 20)")
    history.add_argument("--doc", help="only renders of this chart name")
    history.add_argument("--detail", action="store_true", help="include full hashes and warnings")
    history.set_defaults(func=cmd_history)

    show = subparsers.add_parser("show", help="show one render record", parents=[_lib.common_parser()])
    show.add_argument("render_id", type=int)
    show.set_defaults(func=cmd_show)

    subparsers.add_parser("storage", help="summarize the data root", parents=[_lib.common_parser()]).set_defaults(func=cmd_storage)

    inspect = subparsers.add_parser("inspect", help="read an existing PNG header", parents=[_lib.common_parser()])
    inspect.add_argument("file")
    inspect.set_defaults(func=cmd_inspect)

    subparsers.add_parser("stats", help="render totals", parents=[_lib.common_parser()]).set_defaults(func=cmd_stats)
    return parser


if __name__ == "__main__":
    _lib.run_script("reports", build_parser())
