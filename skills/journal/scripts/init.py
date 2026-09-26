#!/usr/bin/env python3
"""Initialize the journal database.

Creates the schema plus the full-text index when the SQLite build supports
FTS5, and records whether it did. Safe to run more than once (idempotent).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def cmd_init(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    already_initialized = _lib.get_meta(conn, "initialized") is not None
    if args.no_fts:
        _lib.disable_fts(conn)
        enabled = False
    else:
        if _lib.get_meta(conn, "fts_enabled") == "0":
            _lib.set_meta(conn, "fts_enabled", "")
        enabled = _lib.ensure_fts(conn)
    _lib.set_meta(conn, "initialized", "1")
    return {
        "initialized": True,
        "already_initialized": already_initialized,
        "fts_enabled": enabled,
        "schema_version": _lib.SCHEMA_VERSION,
        "db": str(_lib.resolve_db_path(args.db)),
        "settings": _lib.effective_settings(conn),
        "hint": "Run settings.py show to confirm the timezone and search mode.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="init.py", description="Initialize the journal database (schema and full-text index)."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser(
        "init",
        help="create the database if needed",
        description="Create the schema and full-text index. Idempotent.",
        parents=[_lib.common_parser()],
    )
    init_parser.add_argument(
        "--no-fts",
        action="store_true",
        help="force the plain LIKE search fallback (drops any full-text index)",
    )
    init_parser.set_defaults(func=cmd_init, verb="init")
    return parser


def main() -> None:
    _lib.run_script("init", build_parser())


if __name__ == "__main__":
    main()
