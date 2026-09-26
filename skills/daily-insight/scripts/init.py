#!/usr/bin/env python3
"""Initialize the daily-insight data root.

Creates the data directory, the SQLite schema, and the Chroma collection, and
reports which optional dependencies are present. Safe to run more than once
(idempotent).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def cmd_init(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    already_initialized = _lib.get_meta(conn, "initialized") == "1"
    deps = _lib.deps_status()

    if not deps.get("chromadb"):
        raise _lib.CommandError(
            "dependency_missing",
            "init needs the optional dependencies: pip install -r requirements.txt",
        )

    collection = _lib.open_collection(home)
    try:
        count = collection.count()
    except Exception:
        count = 0

    _lib.set_meta(conn, "initialized", "1")
    db_path = _lib.resolve_db_path(home)

    return {
        "initialized": True,
        "already_initialized": already_initialized,
        "home": str(home),
        "db": str(db_path),
        "chroma": str(_lib.resolve_chroma_path(home)),
        "collection": _lib.COLLECTION_NAME,
        "vector_count": int(count),
        "schema_version": _lib.SCHEMA_VERSION,
        "dependencies": deps,
        "settings": _lib.settings_snapshot(conn),
        "env_overrides": _lib.active_env_overrides(),
        "hint": "Run settings.py show to confirm the daily budget and wake window.",
    }


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(
        prog="init.py",
        description="Initialize the daily-insight data root (schema, vector store).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser(
        "init",
        help="create the data root if needed and verify dependencies",
        description="Create the schema and vector collection. Idempotent.",
        parents=[common],
    )
    init_parser.set_defaults(func=cmd_init, verb="init")
    return parser


def main() -> None:
    _lib.run_script("init", build_parser())


if __name__ == "__main__":
    main()
