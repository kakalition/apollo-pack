#!/usr/bin/env python3
"""Manage a local library of chart specs.

Specs are stored as JSON in the data-root database so they can be re-rendered,
listed, exported, and scheduled by name. Rendering itself happens in
``render.py``; this script never touches Node or Playwright.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _lib


def _parse_tags(value: Optional[str]) -> str:
    if not value:
        return ""
    tags = [tag.strip() for tag in str(value).split(",") if tag.strip()]
    return ",".join(dict.fromkeys(tags))


def _summary(row: sqlite3.Row, *, detail: bool = False) -> Dict[str, Any]:
    spec = json.loads(row["spec"])
    series = spec.get("series") or []
    data = {
        "id": row["id"],
        "name": row["name"],
        "title": row["title"],
        "tags": [tag for tag in (row["tags"] or "").split(",") if tag],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "render_count": int(row["render_count"] or 0),
        "last_rendered_at": row["last_rendered_at"],
        "last_output": row["last_output"],
        "family": spec.get("chart"),
        "variant": spec.get("variant"),
        "theme": spec.get("theme"),
        "palette": spec.get("palette") if isinstance(spec.get("palette"), str) else "custom",
        "series": len(series) if isinstance(series, list) else 0,
        "points": len(spec.get("data") or []) if isinstance(spec.get("data"), list) else 0,
        "width": spec.get("width"),
        "height": spec.get("height"),
    }
    if detail:
        data["spec"] = spec
    return data


def resolve_chart(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    text = str(name or "").strip()
    if not text:
        raise _lib.CommandError("invalid_input", "a chart name is required")
    row = conn.execute("SELECT * FROM charts WHERE name = ?", (text,)).fetchone()
    if row is None:
        raise _lib.CommandError("not_found", "no stored chart named %r" % text)
    return row


def cmd_save(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    name = args.name.strip()
    if not name:
        raise _lib.CommandError("invalid_input", "--name is required")
    if args.spec and args.stdin:
        raise _lib.CommandError("invalid_input", "pass either --spec or --stdin, not both")
    if args.stdin:
        try:
            spec = json.loads(sys.stdin.read())
        except ValueError as exc:
            raise _lib.CommandError("invalid_spec", "stdin is not valid JSON: %s" % exc)
    elif args.spec:
        spec = _lib.load_json(Path(args.spec))
    else:
        raise _lib.CommandError("invalid_input", "pass --spec FILE or --stdin")
    spec, warnings = _lib.validate_spec(spec)
    title = args.title or spec.get("title") or name
    tags = _parse_tags(args.tags)
    now = _lib.now_iso()
    existing = conn.execute("SELECT id, created_at FROM charts WHERE name = ?", (name,)).fetchone()
    if existing and not args.force:
        raise _lib.CommandError("conflict", "chart %r already exists; pass --force to overwrite" % name)
    if existing:
        conn.execute(
            "UPDATE charts SET title = ?, spec = ?, tags = ?, updated_at = ? WHERE id = ?",
            (title, json.dumps(spec), tags, now, existing["id"]),
        )
        chart_id = existing["id"]
        created = False
    else:
        cursor = conn.execute(
            "INSERT INTO charts (name, title, spec, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, title, json.dumps(spec), tags, now, now),
        )
        chart_id = cursor.lastrowid
        created = True
    return {
        "id": chart_id,
        "name": name,
        "title": title,
        "family": spec.get("chart"),
        "created": created,
        "overwritten": bool(existing),
        "warnings": warnings,
    }


def cmd_list(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    rows = conn.execute("SELECT * FROM charts ORDER BY name").fetchall()
    items: List[Dict[str, Any]] = []
    for row in rows:
        if args.tag and args.tag not in (row["tags"] or "").split(","):
            continue
        if args.family:
            spec = json.loads(row["spec"])
            if spec.get("chart") != args.family:
                continue
        items.append(_summary(row))
    return {"count": len(items), "charts": items}


def cmd_show(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    return _summary(resolve_chart(conn, args.name), detail=True)


def cmd_rename(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    row = resolve_chart(conn, args.name)
    new_name = args.new_name.strip()
    if not new_name:
        raise _lib.CommandError("invalid_input", "the new name is required")
    clash = conn.execute("SELECT id FROM charts WHERE name = ?", (new_name,)).fetchone()
    if clash:
        raise _lib.CommandError("conflict", "chart %r already exists" % new_name)
    conn.execute(
        "UPDATE charts SET name = ?, updated_at = ? WHERE id = ?",
        (new_name, _lib.now_iso(), row["id"]),
    )
    return {"id": row["id"], "name": new_name, "renamed_from": row["name"]}


def cmd_duplicate(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    row = resolve_chart(conn, args.name)
    new_name = args.new_name.strip()
    if not new_name:
        raise _lib.CommandError("invalid_input", "the new name is required")
    clash = conn.execute("SELECT id FROM charts WHERE name = ?", (new_name,)).fetchone()
    if clash and not args.force:
        raise _lib.CommandError("conflict", "chart %r already exists; pass --force" % new_name)
    now = _lib.now_iso()
    title = "%s (copy)" % (row["title"] or row["name"])
    if clash:
        conn.execute(
            "UPDATE charts SET title = ?, spec = ?, tags = ?, updated_at = ? WHERE id = ?",
            (title, row["spec"], row["tags"], now, clash["id"]),
        )
        chart_id = clash["id"]
    else:
        cursor = conn.execute(
            "INSERT INTO charts (name, title, spec, tags, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (new_name, title, row["spec"], row["tags"], now, now),
        )
        chart_id = cursor.lastrowid
    return {"id": chart_id, "name": new_name, "duplicated_from": row["name"]}


def cmd_delete(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    row = resolve_chart(conn, args.name)
    if not args.yes:
        raise _lib.CommandError("invalid_input", "deleting %r needs --yes" % row["name"])
    conn.execute("DELETE FROM charts WHERE id = ?", (row["id"],))
    return {"id": row["id"], "name": row["name"], "deleted": True}


def cmd_export(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    row = resolve_chart(conn, args.name)
    spec = json.loads(row["spec"])
    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {"name": row["name"], "out": str(out_path), "bytes": out_path.stat().st_size}
    return {"name": row["name"], "spec": spec}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="charts.py", description="Manage stored chart specs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    save = subparsers.add_parser("save", help="store a spec", parents=[_lib.common_parser()])
    save.add_argument("--name", required=True, help="chart name (unique)")
    save.add_argument("--spec", help="path to a JSON spec file")
    save.add_argument("--stdin", action="store_true", help="read the spec JSON from stdin")
    save.add_argument("--title", help="human title (defaults to spec.title or the name)")
    save.add_argument("--tags", help="comma-separated tags")
    save.add_argument("--force", action="store_true", help="overwrite an existing chart")
    save.set_defaults(func=cmd_save)

    listing = subparsers.add_parser("list", help="list charts", parents=[_lib.common_parser()])
    listing.add_argument("--tag", help="only charts carrying this tag")
    listing.add_argument("--family", choices=list(_lib.CHART_FAMILIES), help="only this chart family")
    listing.set_defaults(func=cmd_list)

    show = subparsers.add_parser("show", help="show one chart", parents=[_lib.common_parser()])
    show.add_argument("name")
    show.set_defaults(func=cmd_show)

    rename = subparsers.add_parser("rename", help="rename a chart", parents=[_lib.common_parser()])
    rename.add_argument("name")
    rename.add_argument("new_name")
    rename.set_defaults(func=cmd_rename)

    duplicate = subparsers.add_parser("duplicate", help="copy a chart", parents=[_lib.common_parser()])
    duplicate.add_argument("name")
    duplicate.add_argument("new_name")
    duplicate.add_argument("--force", action="store_true", help="overwrite an existing target")
    duplicate.set_defaults(func=cmd_duplicate)

    delete = subparsers.add_parser("delete", help="delete a chart", parents=[_lib.common_parser()])
    delete.add_argument("name")
    delete.add_argument("--yes", action="store_true", help="confirm deletion")
    delete.set_defaults(func=cmd_delete)

    export = subparsers.add_parser("export", help="write a chart's spec as JSON", parents=[_lib.common_parser()])
    export.add_argument("name")
    export.add_argument("--out", help="write to this path instead of printing")
    export.set_defaults(func=cmd_export)
    return parser


if __name__ == "__main__":
    _lib.run_script("charts", build_parser())
