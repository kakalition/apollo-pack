#!/usr/bin/env python3
"""Initialize the charting data root and report render dependencies.

Idempotent: safe to run any number of times. Creates the database and the
``output/`` and ``tmp/`` directories, and reports whether Node, the esbuild
bundle, Playwright, and Chromium are present. ``--install`` runs the one-time
network install (``npm ci``, the bundle build, and the Chromium download).
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _lib


def _install() -> Dict[str, Any]:
    steps = []
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None:
        raise _lib.CommandError(
            "dependency_missing",
            "Node.js and npm are required for --install; install Node 20+ and retry",
        )
    commands = [
        ("npm-ci", [npm, "ci"], "install pinned Node dependencies"),
        ("build", [node, str(_lib.SKILL_ROOT / "scripts" / "build.mjs")], "bundle the chart renderer"),
        ("chromium", [npm, "exec", "--", "playwright", "install", "chromium"], "download Chromium"),
    ]
    for name, command, description in commands:
        completed = subprocess.run(
            command,
            cwd=str(_lib.SKILL_ROOT),
            capture_output=True,
            text=True,
        )
        steps.append({
            "step": name,
            "description": description,
            "command": " ".join(command),
            "returncode": completed.returncode,
        })
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()
            raise _lib.CommandError(
                "install_failed",
                "%s failed: %s" % (name, detail[-1] if detail else "see output"),
            )
    return {"steps": steps}


def cmd_init(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    already = _lib.get_meta(conn, "initialized") == "1"
    for path in (_lib.resolve_output_path(home), _lib.resolve_tmp_path(home)):
        path.mkdir(parents=True, exist_ok=True)
    _lib.set_meta(conn, "initialized", "1")
    payload: Dict[str, Any] = {
        "home": str(home),
        "db": str(_lib.resolve_db_path(home)),
        "output": str(_lib.resolve_output_path(home)),
        "tmp": str(_lib.resolve_tmp_path(home)),
        "schema_version": _lib.schema_version(conn),
        "already_initialized": already,
        "dependencies": _lib.dependency_report(),
        "install_hint": _lib.INSTALL_HINT,
    }
    if args.install:
        payload["install"] = _install()
        payload["dependencies"] = _lib.dependency_report()
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="init.py", description="Initialize the charting data root and schema."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    init = subparsers.add_parser(
        "init", help="create the data root, schema, and directories", parents=[_lib.common_parser()]
    )
    init.add_argument(
        "--install",
        action="store_true",
        help="run npm ci, build the bundle, and download Chromium (needs network)",
    )
    init.set_defaults(func=cmd_init)
    return parser


if __name__ == "__main__":
    _lib.run_script("init", build_parser())
