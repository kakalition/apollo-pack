#!/usr/bin/env python3
"""Read and change charting defaults (theme, palette, size, legend).

Settings are stored per data root and may be overridden per call by namespaced
host environment variables (``CHARTING_THEME``, ``CHARTING_WIDTH``,
...). ``show`` reports the effective settings, the stored values, the active
environment overrides, and the resolved output directory.
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
    "theme": "--theme",
    "palette": "--palette",
    "width": "--width",
    "height": "--height",
    "scale": "--scale",
    "background": "--background",
    "font": "--font",
    "legend": "--legend",
    "output_dir": "--output-dir",
}


def _validate(key: str, value: str) -> None:
    if key == "theme" and value not in _lib.THEMES:
        raise _lib.CommandError("invalid_input", "theme must be 'light' or 'dark'")
    if key == "legend" and value not in _lib.LEGENDS:
        raise _lib.CommandError("invalid_input", "legend must be one of %s" % ", ".join(_lib.LEGENDS))
    if key == "palette" and value not in _lib.PALETTES:
        raise _lib.CommandError(
            "invalid_input", "palette must be one of %s" % ", ".join(sorted(_lib.PALETTES))
        )
    if key in ("width", "height"):
        _lib.parse_int(value, 720, _lib.MIN_DIMENSION, _lib.MAX_DIMENSION, key)
    if key == "scale":
        _lib.parse_int(value, 2, _lib.MIN_SCALE, _lib.MAX_SCALE, key)
    if key == "background" and value != "transparent" and not _lib.is_color(value):
        raise _lib.CommandError("invalid_input", "background must be 'transparent' or a CSS color")


def cmd_show(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "home": str(home),
        "settings": _lib.settings_snapshot(conn),
        "env_overrides": _lib.active_env_overrides(),
        "output_dir": str(_lib.resolve_output_dir(conn, home)),
        "dependencies": _lib.dependency_report(),
    }


def cmd_get(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if args.key:
        if args.key not in _lib.SETTING_DEFAULTS:
            raise _lib.CommandError("not_found", "unknown setting %r" % args.key)
        return {"key": args.key, "value": _lib.effective_setting(conn, args.key)}
    return {"settings": _lib.settings_snapshot(conn)}


def cmd_set(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    changed: Dict[str, str] = {}
    grid = getattr(args, "grid", None)
    if grid is not None:
        value = "true" if grid == "on" else "false"
        _lib.set_meta(conn, "grid", value)
        changed["grid"] = value
    for key, flag in FLAGS.items():
        value = getattr(args, key, None)
        if value is None:
            continue
        value = str(value)
        _validate(key, value)
        _lib.set_meta(conn, key, value)
        changed[key] = value
    if not changed:
        raise _lib.CommandError("invalid_input", "no settings supplied; pass at least one flag")
    return {"changed": changed, "settings": _lib.settings_snapshot(conn)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="settings.py", description="Show or change charting settings.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "show", help="show effective settings", parents=[_lib.common_parser()]
    ).set_defaults(func=cmd_show)

    get = subparsers.add_parser("get", help="read one setting", parents=[_lib.common_parser()])
    get.add_argument("--key", help="setting name; omit for the whole map")
    get.set_defaults(func=cmd_get)

    set_cmd = subparsers.add_parser("set", help="change settings", parents=[_lib.common_parser()])
    set_cmd.add_argument("--theme", choices=list(_lib.THEMES), help="default theme")
    set_cmd.add_argument("--palette", help="default palette preset: %s" % ", ".join(sorted(_lib.PALETTES)))
    set_cmd.add_argument("--width", help="default width in CSS pixels")
    set_cmd.add_argument("--height", help="default height in CSS pixels")
    set_cmd.add_argument("--scale", help="default device scale factor (1-4)")
    set_cmd.add_argument("--background", help="default background: transparent or a CSS color")
    set_cmd.add_argument("--font", help="default font: system or a font file path")
    set_cmd.add_argument("--grid", choices=("on", "off"), help="show the cartesian grid by default")
    set_cmd.add_argument("--legend", choices=list(_lib.LEGENDS), help="default legend position")
    set_cmd.add_argument("--output-dir", help="default directory for rendered PNGs")
    set_cmd.set_defaults(func=cmd_set)
    return parser


if __name__ == "__main__":
    _lib.run_script("settings", build_parser())
