#!/usr/bin/env python3
"""Inspect built-in palettes/themes and render ready-made example charts.

``list`` enumerates palettes, themes, and demos; ``show`` returns a palette's
colors, a theme's tokens, or a demo's full spec; ``spec`` writes a demo spec as
JSON; ``demo`` renders one to a PNG. Demo specs live here so the schema stays the
single source of truth.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _html
import _lib
import render


def _bar_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "chart": "bar",
        "variant": "grouped",
        "title": "Revenue by month",
        "description": "Desktop vs. mobile, 2026",
        "data": [
            {"month": "Jan", "desktop": 186, "mobile": 80},
            {"month": "Feb", "desktop": 205, "mobile": 120},
            {"month": "Mar", "desktop": 237, "mobile": 132},
            {"month": "Apr", "desktop": 173, "mobile": 101},
            {"month": "May", "desktop": 209, "mobile": 154},
            {"month": "Jun", "desktop": 264, "mobile": 190},
        ],
        "x": {"key": "month"},
        "y": {"hide": False, "format": "number"},
        "series": [
            {"key": "desktop", "label": "Desktop"},
            {"key": "mobile", "label": "Mobile"},
        ],
        "palette": "default",
        "legend": "bottom",
    }


def _line_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "chart": "line",
        "curve": "monotone",
        "title": "Weekly active users",
        "data": [
            {"week": "W1", "app": 420, "web": 310},
            {"week": "W2", "app": 468, "web": 322},
            {"week": "W3", "app": 501, "web": 360},
            {"week": "W4", "app": 486, "web": 373},
            {"week": "W5", "app": 540, "web": 402},
            {"week": "W6", "app": 588, "web": 431},
        ],
        "x": {"key": "week"},
        "y": {"hide": False, "format": "compact"},
        "series": [
            {"key": "app", "label": "Mobile app"},
            {"key": "web", "label": "Web"},
        ],
        "palette": "blue",
    }


def _area_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "chart": "area",
        "stacked": True,
        "title": "Traffic sources",
        "data": [
            {"month": "Jan", "organic": 240, "referral": 120, "direct": 90},
            {"month": "Feb", "organic": 262, "referral": 132, "direct": 96},
            {"month": "Mar", "organic": 288, "referral": 141, "direct": 110},
            {"month": "Apr", "organic": 271, "referral": 156, "direct": 118},
            {"month": "May", "organic": 320, "referral": 168, "direct": 129},
            {"month": "Jun", "organic": 344, "referral": 180, "direct": 141},
        ],
        "x": {"key": "month"},
        "y": {"hide": False, "format": "number"},
        "series": [
            {"key": "organic", "label": "Organic"},
            {"key": "referral", "label": "Referral"},
            {"key": "direct", "label": "Direct"},
        ],
        "palette": "emerald",
    }


def _pie_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "chart": "pie",
        "title": "Browser share",
        "description": "Last 30 days",
        "data": [
            {"browser": "Chrome", "share": 64},
            {"browser": "Safari", "share": 21},
            {"browser": "Firefox", "share": 8},
            {"browser": "Edge", "share": 5},
            {"browser": "Other", "share": 2},
        ],
        "name_key": "browser",
        "value_key": "share",
        "palette": "default",
        "legend": "right",
    }


def _donut_demo() -> Dict[str, Any]:
    spec = _pie_demo()
    spec.update({
        "chart": "donut",
        "title": "Spend by category",
        "description": "This month",
        "donut": True,
        "center_label": "$12.4k",
        "data": [
            {"category": "Housing", "amount": 42},
            {"category": "Food", "amount": 24},
            {"category": "Transport", "amount": 14},
            {"category": "Utilities", "amount": 12},
            {"category": "Other", "amount": 8},
        ],
        "name_key": "category",
        "value_key": "amount",
        "palette": "rose",
        "legend": "bottom",
    })
    return spec


def _radar_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "chart": "radar",
        "title": "Team strengths",
        "data": [
            {"skill": "Design", "team": 82, "peers": 64},
            {"skill": "Engineering", "team": 74, "peers": 71},
            {"skill": "Research", "team": 66, "peers": 58},
            {"skill": "Delivery", "team": 88, "peers": 70},
            {"skill": "Support", "team": 71, "peers": 62},
        ],
        "x": {"key": "skill"},
        "axis_key": "skill",
        "series": [
            {"key": "team", "label": "This team"},
            {"key": "peers", "label": "Peers"},
        ],
        "palette": "default",
        "fill_opacity": 0.5,
    }


def _radial_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "chart": "radial",
        "title": "Goal completion",
        "description": "Quarter to date",
        "data": [
            {"goal": "Revenue", "progress": 78},
            {"goal": "Retention", "progress": 64},
            {"goal": "NPS", "progress": 52},
        ],
        "name_key": "goal",
        "value_key": "progress",
        "y": {"format": "percent"},
        "palette": "amber",
    }


DEMOS = {
    "bar": _bar_demo,
    "line": _line_demo,
    "area": _area_demo,
    "pie": _pie_demo,
    "donut": _donut_demo,
    "radar": _radar_demo,
    "radial": _radial_demo,
}


def _demo_spec(name: str) -> Dict[str, Any]:
    if name not in DEMOS:
        raise _lib.CommandError("not_found", "no demo named %r (try: %s)" % (name, ", ".join(sorted(DEMOS))))
    spec = DEMOS[name]()
    _lib.validate_spec(spec)
    return spec


def cmd_list(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    palettes = [{"name": name, "colors": colors} for name, colors in sorted(_lib.PALETTES.items())]
    return {
        "themes": [
            {"name": "light", "background": _lib.LIGHT_TOKENS["--background"]},
            {"name": "dark", "background": _lib.DARK_TOKENS["--background"]},
        ],
        "palettes": palettes,
        "demos": sorted(DEMOS),
    }


def cmd_show(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    name = args.name
    kind = getattr(args, "kind", None)
    if kind == "palette" or (kind is None and name in _lib.PALETTES):
        if name not in _lib.PALETTES:
            raise _lib.CommandError("not_found", "no palette named %r" % name)
        return {"kind": "palette", "name": name, "colors": _lib.PALETTES[name]}
    if kind == "theme" or (kind is None and name in _lib.THEMES):
        if name not in _lib.THEMES:
            raise _lib.CommandError("not_found", "no theme named %r" % name)
        return {"kind": "theme", "name": name, "tokens": _lib.theme_tokens(name, _lib.PALETTES["default"])}
    if name in DEMOS:
        return {"kind": "demo", "name": name, "spec": _demo_spec(name)}
    raise _lib.CommandError("not_found", "no palette, theme, or demo named %r" % name)


def cmd_spec(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    spec = _demo_spec(args.name)
    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"demo": args.name, "out": str(out_path), "bytes": out_path.stat().st_size}
    return {"demo": args.name, "spec": spec}


def cmd_demo(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    spec = _demo_spec(args.name)
    if args.theme:
        spec["theme"] = args.theme
    if args.scale is not None:
        spec["scale"] = args.scale
    out_path = Path(args.out).expanduser() if args.out else _lib.resolve_output_dir(conn, home) / ("%s.png" % args.name)
    result = render.render_spec(
        conn,
        home,
        spec,
        out_path,
        force=True,
        transparent=args.transparent,
        keep_html=False,
        no_record=True,
        name=args.name,
    )
    return {"demo": args.name, **result}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="themes.py", description="Inspect palettes/themes and render example charts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list palettes, themes, and demos", parents=[_lib.common_parser()]).set_defaults(func=cmd_list)

    show = subparsers.add_parser("show", help="show a palette, theme, or demo", parents=[_lib.common_parser()])
    show.add_argument("name")
    show.add_argument("--kind", choices=("palette", "theme", "demo"), help="disambiguate the name")
    show.set_defaults(func=cmd_show)

    spec = subparsers.add_parser("spec", help="emit a demo's spec JSON", parents=[_lib.common_parser()])
    spec.add_argument("name")
    spec.add_argument("--out", help="write to this path instead of printing")
    spec.set_defaults(func=cmd_spec)

    demo = subparsers.add_parser("demo", help="render a demo to a PNG", parents=[_lib.common_parser()])
    demo.add_argument("name")
    demo.add_argument("--out", help="output path (default: <home>/output/<name>.png)")
    demo.add_argument("--scale", type=int, help="device scale factor override (1-4)")
    demo.add_argument("--theme", choices=list(_lib.THEMES), help="theme override")
    demo.add_argument("--transparent", action="store_true", help="force a transparent background")
    demo.set_defaults(func=cmd_demo)
    return parser


if __name__ == "__main__":
    _lib.run_script("themes", build_parser())
