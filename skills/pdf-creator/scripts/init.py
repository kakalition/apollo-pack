#!/usr/bin/env python3
"""Initialize the pdf-creator data root and its SQLite schema.

Idempotent: safe to run any number of times. Creates the database, the asset,
font, and output directories, and reports which optional renderer pieces are
installed.
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


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def cmd_init(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    already = _lib.get_meta(conn, "initialized") == "1"
    for path in (
        _lib.resolve_assets_path(home),
        _lib.resolve_fonts_path(home),
        _lib.resolve_output_path(home),
    ):
        path.mkdir(parents=True, exist_ok=True)
    _lib.set_meta(conn, "initialized", "1")
    return {
        "home": str(home),
        "db": str(_lib.resolve_db_path(home)),
        "assets": str(_lib.resolve_assets_path(home)),
        "fonts": str(_lib.resolve_fonts_path(home)),
        "output": str(_lib.resolve_output_path(home)),
        "schema_version": _lib.schema_version(conn),
        "already_initialized": already,
        "dependencies": {
            "reportlab": _has_module("reportlab"),
            "pillow": _has_module("PIL"),
            "pypdf": _has_module("pypdf"),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="init.py", description="Initialize the pdf-creator data root and schema."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "init", help="create the data root, schema, and directories", parents=[_lib.common_parser()]
    ).set_defaults(func=cmd_init)
    return parser


if __name__ == "__main__":
    _lib.run_script("init", build_parser())
