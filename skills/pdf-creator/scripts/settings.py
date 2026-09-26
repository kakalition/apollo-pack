#!/usr/bin/env python3
"""Read and change pdf-creator defaults (page size, margins, theme, fonts).

Settings are stored per data root and may be overridden per call by namespaced
host environment variables (``PDF_CREATOR_PAGE_SIZE``, ``PDF_CREATOR_THEME``,
...). ``show`` reports the effective settings, the stored values, and which
environment variables are currently in force.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _lib

FLAGS = {
    "page_size": "--page-size",
    "orientation": "--orientation",
    "unit": "--unit",
    "theme": "--theme",
    "font_family": "--font-family",
    "font_size": "--font-size",
    "line_height": "--line-height",
    "heading_scale": "--heading-scale",
    "text_color": "--text-color",
    "accent": "--accent",
    "author": "--author",
    "language": "--language",
    "output_dir": "--output-dir",
    "allow_remote": "--allow-remote",
}


def cmd_show(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "home": str(home),
        "settings": _lib.settings_snapshot(conn),
        "env_overrides": _lib.active_env_overrides(),
        "output_dir": str(_lib.resolve_output_dir(conn, home)),
    }


def cmd_get(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if args.key:
        if args.key not in _lib.SETTING_DEFAULTS:
            raise _lib.CommandError("not_found", "unknown setting %r" % args.key)
        return {"key": args.key, "value": _lib.effective_setting(conn, args.key)}
    return {"settings": _lib.settings_snapshot(conn)}


def cmd_set(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    changed: Dict[str, str] = {}
    margin = getattr(args, "margin", None)
    if margin is not None:
        for side in ("margin_top", "margin_right", "margin_bottom", "margin_left"):
            _lib.set_meta(conn, side, margin)
            changed[side] = margin
    allow_remote = getattr(args, "allow_remote", None)
    if allow_remote is not None:
        value = "true" if allow_remote == "yes" else "false"
        _lib.set_meta(conn, "allow_remote", value)
        changed["allow_remote"] = value
    for key, flag in FLAGS.items():
        if key == "allow_remote":
            continue
        value = getattr(args, key.replace("-", "_"), None)
        if value is not None:
            _lib.set_meta(conn, key, value)
            changed[key] = value
    if not changed:
        raise _lib.CommandError("invalid_input", "no settings supplied; pass at least one flag")
    return {"changed": changed, "settings": _lib.settings_snapshot(conn)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="settings.py", description="Show or change pdf-creator settings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "show", help="show effective settings", parents=[_lib.common_parser()]
    ).set_defaults(func=cmd_show)

    get = subparsers.add_parser("get", help="read one setting", parents=[_lib.common_parser()])
    get.add_argument("--key", help="setting name; omit for the whole map")
    get.set_defaults(func=cmd_get)

    set_cmd = subparsers.add_parser("set", help="change settings", parents=[_lib.common_parser()])
    set_cmd.add_argument("--page-size", help="A4, Letter, Legal, A3, 210x297mm, ...")
    set_cmd.add_argument("--orientation", choices=("portrait", "landscape"))
    set_cmd.add_argument("--unit", choices=("mm", "cm", "in", "pt", "pc"))
    set_cmd.add_argument("--margin", help="set all four margins at once, e.g. 20mm")
    set_cmd.add_argument("--theme", help="default theme name")
    set_cmd.add_argument("--font-family", help="built-in family or a registered TTF family")
    set_cmd.add_argument("--font-size", help="base body font size in points")
    set_cmd.add_argument("--line-height", help="base line height multiplier")
    set_cmd.add_argument("--heading-scale", help="multiply every heading size by this factor")
    set_cmd.add_argument("--text-color", help="default body text color")
    set_cmd.add_argument("--accent", help="default accent color")
    set_cmd.add_argument("--author", help="default document author")
    set_cmd.add_argument("--language", help="default document language tag")
    set_cmd.add_argument("--output-dir", help="default directory for rendered PDFs")
    set_cmd.add_argument("--allow-remote", choices=("yes", "no"), help="allow fetching remote images by default")
    set_cmd.set_defaults(func=cmd_set)
    return parser


if __name__ == "__main__":
    _lib.run_script("settings", build_parser())
