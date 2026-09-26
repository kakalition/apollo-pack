#!/usr/bin/env python3
"""Read-only reporting for pdf-creator: render history and PDF introspection.

``history`` and ``show`` read the local render log. ``inspect`` reads an
existing PDF's page count and metadata when the optional ``pypdf`` package is
installed. ``storage`` summarizes the data root. Nothing here writes.
"""
from __future__ import annotations

import argparse
import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _lib


def _render_row(row: sqlite3.Row, *, detail: bool = False) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": row["id"],
        "document_id": row["document_id"],
        "name": row["name"],
        "out": row["out_path"],
        "pages": row["pages"],
        "bytes": row["bytes"],
        "sha256": (row["sha256"] or "")[:16],
        "width_pt": row["width_pt"],
        "height_pt": row["height_pt"],
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
    documents = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
    renders = conn.execute("SELECT COUNT(*) AS n FROM renders").fetchone()["n"]
    assets_dir = _lib.resolve_assets_path(home)
    fonts_dir = _lib.resolve_fonts_path(home)
    return {
        "home": str(home),
        "db": str(_lib.resolve_db_path(home)),
        "assets": str(assets_dir),
        "fonts": str(fonts_dir),
        "output": str(_lib.resolve_output_dir(conn, home)),
        "documents": int(documents),
        "renders": int(renders),
        "images": len([p for p in assets_dir.glob("*") if p.is_file()]) if assets_dir.is_dir() else 0,
        "font_files": len([p for p in fonts_dir.glob("*") if p.suffix.lower() in (".ttf", ".otf", ".ttc")]) if fonts_dir.is_dir() else 0,
        "reportlab": importlib.util.find_spec("reportlab") is not None,
        "pypdf": importlib.util.find_spec("pypdf") is not None,
    }


def cmd_inspect(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    path = Path(args.file).expanduser()
    if not path.is_file():
        raise _lib.CommandError("not_found", "PDF not found: %s" % path)
    payload: Dict[str, Any] = {
        "file": str(path),
        "bytes": path.stat().st_size,
        "sha256": _lib.sha256_file(path),
    }
    if importlib.util.find_spec("pypdf") is None:
        payload["readable"] = False
        payload["note"] = "install pypdf to read page count and metadata (pip install pypdf)"
        return payload
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            password = args.password or ""
            try:
                unlocked = reader.decrypt(password) if password else False
            except Exception:
                unlocked = False
            if not unlocked:
                payload.update({
                    "readable": False,
                    "encrypted": True,
                    "note": "the PDF is encrypted; pass --password to read page count and metadata",
                })
                return payload
        info = reader.metadata or {}
        payload.update({
            "readable": True,
            "encrypted": bool(reader.is_encrypted),
            "pages": len(reader.pages),
            "meta": {
                "title": info.get("/Title"),
                "author": info.get("/Author"),
                "subject": info.get("/Subject"),
                "creator": info.get("/Creator"),
                "producer": info.get("/Producer"),
            },
        })
    except Exception as exc:
        raise _lib.CommandError("invalid_pdf", "could not read %s: %s" % (path, exc))
    return payload


def cmd_stats(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    totals = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS b, COALESCE(SUM(pages), 0) AS p FROM renders").fetchone()
    return {
        "renders": int(totals["n"]),
        "total_bytes": int(totals["b"]),
        "total_pages": int(totals["p"]),
        "read_only": True,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reports.py", description="Report on pdf-creator state and PDFs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    history = subparsers.add_parser("history", help="list recent renders", parents=[_lib.common_parser()])
    history.add_argument("--limit", type=int, default=20, help="maximum rows (default 20)")
    history.add_argument("--doc", help="only renders of this document name")
    history.add_argument("--detail", action="store_true", help="include full hashes and warnings")
    history.set_defaults(func=cmd_history)

    show = subparsers.add_parser("show", help="show one render record", parents=[_lib.common_parser()])
    show.add_argument("render_id", type=int)
    show.set_defaults(func=cmd_show)

    subparsers.add_parser("storage", help="summarize the data root", parents=[_lib.common_parser()]).set_defaults(func=cmd_storage)

    inspect = subparsers.add_parser("inspect", help="read an existing PDF", parents=[_lib.common_parser()])
    inspect.add_argument("file")
    inspect.add_argument("--password", help="password for an encrypted PDF")
    inspect.set_defaults(func=cmd_inspect)

    subparsers.add_parser("stats", help="render totals", parents=[_lib.common_parser()]).set_defaults(func=cmd_stats)
    return parser


if __name__ == "__main__":
    _lib.run_script("reports", build_parser())
