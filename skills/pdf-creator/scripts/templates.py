#!/usr/bin/env python3
"""Inspect built-in themes and render ready-made example documents.

``list`` enumerates themes and demos; ``show`` returns a theme's palette and
style overrides or a demo's full spec; ``spec`` writes a demo spec as JSON;
``demo`` renders one to a PDF. Themes live in ``_themes.py`` so the schema is
the single source of truth.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _lib
import _engine
from _themes import BASE_PALETTE, THEMES


def _invoice_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "theme": "invoice",
        "meta": {"title": "Invoice INV-1042", "author": "Acme Studio"},
        "page": {"size": "A4"},
        "header": {"text": "Acme Studio", "align": "left", "divider": True},
        "footer": {"text": "Thank you for your business", "align": "center"},
        "content": [
            {"type": "heading", "level": 1, "text": "Invoice INV-1042"},
            {"type": "key_values", "columns": 2, "items": [
                {"key": "Billed to", "value": "Northwind Ltd."},
                {"key": "Issued", "value": "2026-09-01"},
                {"key": "Address", "value": "12 Harbor Road"},
                {"key": "Due", "value": "2026-09-30"},
            ]},
            {"type": "spacer", "height": "4mm"},
            {"type": "table", "header": ["Description", "Qty", "Rate", "Amount"], "number_align": "first",
             "widths": [0.5, 0.12, 0.18, 0.2], "zebra": True,
             "rows": [
                 ["Design sprint", "1", "$2,400.00", "$2,400.00"],
                 ["Illustration set", "6", "$180.00", "$1,080.00"],
                 ["Retouching", "3", "$90.00", "$270.00"],
                 [{"text": "Subtotal", "bold": True}, "", "", "$3,750.00"],
                 [{"text": "Tax (10%)", "bold": True}, "", "", "$375.00"],
                 [{"text": "Total due", "bold": True, "background": "#E8F0FE"}, "", "",
                  {"text": "$4,125.00", "bold": True, "background": "#E8F0FE"}],
             ]},
            {"type": "callout", "kind": "info", "title": "Payment", "text": "Bank transfer to Acme Studio, account ending 4021."},
        ],
    }


def _letter_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "theme": "letter",
        "meta": {"title": "Offer letter", "author": "Acme Studio"},
        "header": None,
        "footer": {"text": "{page} / {pages}", "align": "right"},
        "content": [
            {"type": "paragraph", "text": "2026-09-26"},
            {"type": "paragraph", "text": "Dear Ms. Rivera,"},
            {"type": "paragraph", "text": "We are delighted to offer you the position of Lead Designer at Acme Studio, reporting to the Creative Director."},
            {"type": "list", "items": [
                "Annual salary of $132,000, reviewed each January.",
                "Four weeks of paid leave plus public holidays.",
                "A $2,000 yearly budget for conferences and courses.",
            ]},
            {"type": "paragraph", "text": "Please confirm your acceptance by **30 September 2026**. We look forward to welcoming you."},
            {"type": "spacer", "height": "10mm"},
            {"type": "paragraph", "text": "Warm regards,\nAda Lovelace\nCreative Director"},
        ],
    }


def _resume_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "theme": "resume",
        "meta": {"title": "Ada Lovelace — Resume"},
        "content": [
            {"type": "heading", "level": 1, "text": "Ada Lovelace"},
            {"type": "paragraph", "text": "Lead Designer · ada@example.com · +44 20 7946 0000"},
            {"type": "divider"},
            {"type": "heading", "level": 2, "text": "Experience"},
            {"type": "key_values", "items": [
                {"key": "2022—now", "value": "Lead Designer, Acme Studio"},
                {"key": "2019—2022", "value": "Senior Designer, Northwind"},
            ]},
            {"type": "heading", "level": 2, "text": "Skills"},
            {"type": "list", "items": ["Design systems", "Typography", "Data visualization", "Print production"]},
            {"type": "heading", "level": 2, "text": "Education"},
            {"type": "paragraph", "text": "BA (Hons) Graphic Design, University of London"},
        ],
    }


def _report_demo() -> Dict[str, Any]:
    return {
        "spec_version": 1,
        "theme": "report",
        "meta": {"title": "Quarterly Report", "author": "Acme Analytics", "subject": "Q3 2026"},
        "header": {"text": "Quarterly Report", "align": "right", "divider": True},
        "footer": {"text": "Page {page} of {pages}", "align": "center"},
        "watermark": {"text": "DRAFT", "angle": 32, "opacity": 0.10, "size": 78},
        "toc": {"title": "Contents", "depth": 2},
        "cover": {
            "eyebrow": "Acme Analytics",
            "title": "Quarterly Report",
            "subtitle": "Revenue, retention, and outlook for Q3 2026",
            "author": "Prepared by the data team",
            "date": "2026-09-26",
            "rule": True,
        },
        "content": [
            {"type": "heading", "level": 1, "text": "Executive summary"},
            {"type": "paragraph", "text": "Revenue grew **12%** quarter over quarter, driven by *enterprise* renewals. See the [dashboard](https://example.com) for detail."},
            {"type": "list", "ordered": True, "items": [
                "Enterprise renewals closed ahead of plan.",
                {"text": "Retention held steady", "items": ["Net revenue retention 118%", "Logo churn 3.1%"]},
                "Operating costs stayed within budget.",
            ]},
            {"type": "table", "header": ["Region", "Revenue", "Growth"], "widths": [0.4, 0.3, 0.3],
             "zebra": True, "caption": "Revenue by region", "numbered": True,
             "rows": [["North America", "$4.1M", "14%"], ["Europe", "$2.6M", "9%"], ["APAC", "$1.3M", "11%"]]},
            {"type": "heading", "level": 2, "text": "Outlook"},
            {"type": "callout", "kind": "warning", "title": "Watch item", "text": "Hiring is pacing behind plan and may slow Q4 delivery."},
            {"type": "blockquote", "text": "Growth is a byproduct of keeping promises.", "attribution": "Operations review"},
            {"type": "page_template", "name": "two_column"},
            {"type": "heading", "level": 1, "text": "Appendix"},
            {"type": "paragraph", "text": "Detailed notes follow in a two-column layout. " * 20},
            {"type": "qr", "data": "https://example.com/dashboard", "size": "24mm", "caption": "Dashboard"},
        ],
    }


DEMOS: Dict[str, Any] = {
    "blank": lambda: {
        "spec_version": 1,
        "meta": {"title": "Untitled"},
        "content": [{"type": "heading", "level": 1, "text": "Untitled"}],
    },
    "report": _report_demo,
    "invoice": _invoice_demo,
    "letter": _letter_demo,
    "resume": _resume_demo,
}


def _demo_spec(name: str) -> Dict[str, Any]:
    if name not in DEMOS:
        raise _lib.CommandError("not_found", "no demo named %r (try: %s)" % (name, ", ".join(sorted(DEMOS))))
    spec = DEMOS[name]()
    _lib.validate_spec(spec)
    return spec


def cmd_list(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    themes = [
        {"name": name, "label": theme.get("label", ""), "font_family": theme.get("font_family")}
        for name, theme in sorted(THEMES.items())
    ]
    return {"themes": themes, "demos": sorted(DEMOS)}


def cmd_show(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    name = args.name
    kind = getattr(args, "kind", None)
    if kind == "theme" or (kind is None and name in THEMES):
        if name not in THEMES:
            raise _lib.CommandError("not_found", "no theme named %r" % name)
        theme = THEMES[name]
        return {
            "kind": "theme",
            "name": name,
            "label": theme.get("label", ""),
            "font_family": theme.get("font_family"),
            "palette": _lib.deep_merge(BASE_PALETTE, theme.get("palette") or {}),
            "styles": theme.get("styles") or {},
            "header": theme.get("header"),
            "footer": theme.get("footer"),
        }
    if name in DEMOS:
        return {"kind": "demo", "name": name, "spec": _demo_spec(name)}
    raise _lib.CommandError("not_found", "no theme or demo named %r" % name)


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
    out_path = Path(args.out).expanduser() if args.out else _lib.resolve_output_dir(conn, home) / ("%s.pdf" % args.name)
    settings = _lib.settings_snapshot(conn)
    for key in ("output_dir", "allow_remote"):
        settings[key] = _lib.effective_setting(conn, key)
    result = _engine.build_pdf(spec, out_path, home=home, base_dir=Path.cwd(), settings=settings, allow_remote=args.allow_remote)
    return {"demo": args.name, **result}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="templates.py", description="Inspect themes and render example documents.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="list themes and demos", parents=[_lib.common_parser()]).set_defaults(func=cmd_list)

    show = subparsers.add_parser("show", help="show a theme or demo", parents=[_lib.common_parser()])
    show.add_argument("name")
    show.add_argument("--kind", choices=("theme", "demo"), help="disambiguate names that are both (report, invoice, ...)")
    show.set_defaults(func=cmd_show)

    spec = subparsers.add_parser("spec", help="emit a demo's spec JSON", parents=[_lib.common_parser()])
    spec.add_argument("name")
    spec.add_argument("--out", help="write to this path instead of printing")
    spec.set_defaults(func=cmd_spec)

    demo = subparsers.add_parser("demo", help="render a demo to a PDF", parents=[_lib.common_parser()])
    demo.add_argument("name")
    demo.add_argument("--out", help="output path (default: <home>/output/<name>.pdf)")
    demo.add_argument("--allow-remote", action="store_true", help="allow remote images")
    demo.set_defaults(func=cmd_demo)
    return parser


if __name__ == "__main__":
    _lib.run_script("templates", build_parser())
