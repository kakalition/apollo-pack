#!/usr/bin/env python3
"""Initialize the habit-tracker database.

Creates the schema and records the initialization marker. Safe to run more
than once (idempotent).
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
    _lib.set_meta(conn, "initialized", "1")
    return {
        "initialized": True,
        "already_initialized": already_initialized,
        "schema_version": _lib.SCHEMA_VERSION,
        "db": str(_lib.resolve_db_path(args.db)),
        "settings": _lib.effective_settings(conn),
        "hint": "Run settings.py show to confirm the timezone and week start.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="init.py",
        description="Initialize the habit-tracker database (schema and settings).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser(
        "init",
        help="create the database if needed",
        description="Create the schema and mark the database initialized. Idempotent.",
        parents=[_lib.common_parser()],
    )
    init_parser.set_defaults(func=cmd_init, verb="init")
    return parser


def main() -> None:
    _lib.run_script("init", build_parser())


if __name__ == "__main__":
    main()
