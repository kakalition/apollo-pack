#!/usr/bin/env python3
"""Register reusable images and fonts in the pdf-creator data root.

Images are copied to ``<home>/assets`` and fonts to ``<home>/fonts``; a
``fonts.json`` manifest records the family, style faces, and file names so the
renderer can register them automatically. Specs then refer to an asset by its
bare file name.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _lib

FONT_SUFFIXES = (".ttf", ".otf", ".ttc")


def _manifest_path(home: Path) -> Path:
    return _lib.resolve_fonts_path(home) / "fonts.json"


def _read_manifest(home: Path) -> List[Dict[str, Any]]:
    path = _manifest_path(home)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return [entry for entry in data if isinstance(entry, dict)] if isinstance(data, list) else []
    except ValueError:
        raise _lib.CommandError("invalid_state", "font manifest %s is not valid JSON" % path)


def _write_manifest(home: Path, entries: List[Dict[str, Any]]) -> None:
    path = _manifest_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _copy_asset(source: str, target_dir: Path, name: Optional[str], force: bool) -> Path:
    src = Path(source).expanduser()
    if not src.is_file():
        raise _lib.CommandError("not_found", "file not found: %s" % source)
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / (name or src.name)
    if destination.exists() and not force:
        raise _lib.CommandError("conflict", "%s exists; pass --force to overwrite" % destination)
    shutil.copyfile(src, destination)
    return destination


def cmd_add_image(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    destination = _copy_asset(args.source, _lib.resolve_assets_path(home), args.name, args.force)
    return {
        "kind": "image",
        "name": destination.name,
        "path": str(destination),
        "bytes": destination.stat().st_size,
        "reference": destination.name,
    }


def cmd_add_font(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    fonts_dir = _lib.resolve_fonts_path(home)
    family = args.family or Path(args.file).stem
    normal = _copy_asset(args.file, fonts_dir, None, args.force)
    entry: Dict[str, Any] = {"name": family, "file": normal.name}
    for flag, key in (("bold", "bold"), ("italic", "italic"), ("bold_italic", "bold_italic")):
        value = getattr(args, flag, None)
        if value:
            entry[key] = _copy_asset(value, fonts_dir, None, args.force).name
    entries = [existing for existing in _read_manifest(home) if existing.get("name") != family]
    entries.append(entry)
    entries.sort(key=lambda item: str(item.get("name")))
    _write_manifest(home, entries)
    return {"kind": "font", "family": family, "entry": entry, "manifest": str(_manifest_path(home))}


def cmd_list(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    assets_dir = _lib.resolve_assets_path(home)
    images = sorted(
        (
            {"name": path.name, "bytes": path.stat().st_size, "path": str(path)}
            for path in assets_dir.glob("*")
            if path.is_file()
        ),
        key=lambda item: item["name"],
    ) if assets_dir.is_dir() else []
    fonts = _read_manifest(home)
    kind = (args.type or "").lower()
    data: Dict[str, Any] = {"assets": str(assets_dir), "fonts_dir": str(_lib.resolve_fonts_path(home))}
    if kind in ("", "image"):
        data["images"] = images
    if kind in ("", "font"):
        data["fonts"] = fonts
    return data


def cmd_remove(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    kind = (args.type or "image").lower()
    if kind == "image":
        target = _lib.resolve_assets_path(home) / args.name
        if not target.is_file():
            raise _lib.CommandError("not_found", "no registered image named %r" % args.name)
        target.unlink()
        return {"kind": "image", "name": args.name, "removed": True}
    if kind == "font":
        entries = _read_manifest(home)
        match = next((entry for entry in entries if entry.get("name") == args.name), None)
        if match is None:
            raise _lib.CommandError("not_found", "no registered font family named %r" % args.name)
        fonts_dir = _lib.resolve_fonts_path(home)
        for key in ("file", "bold", "italic", "bold_italic"):
            if match.get(key) and not args.keep_files:
                candidate = fonts_dir / str(match[key])
                if candidate.is_file():
                    candidate.unlink()
        _write_manifest(home, [entry for entry in entries if entry.get("name") != args.name])
        return {"kind": "font", "family": args.name, "removed": True, "entry": match}
    raise _lib.CommandError("invalid_input", "--type must be image or font")


def cmd_paths(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "home": str(home),
        "assets": str(_lib.resolve_assets_path(home)),
        "fonts": str(_lib.resolve_fonts_path(home)),
        "manifest": str(_manifest_path(home)),
        "output": str(_lib.resolve_output_dir(conn, home)),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assets.py", description="Register images and fonts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    image = subparsers.add_parser("add-image", help="copy an image into the asset store", parents=[_lib.common_parser()])
    image.add_argument("source", help="path to the image file")
    image.add_argument("--name", help="store under this name (defaults to the file name)")
    image.add_argument("--force", action="store_true", help="overwrite an existing asset")
    image.set_defaults(func=cmd_add_image)

    font = subparsers.add_parser("add-font", help="copy a TTF/OTF family into the font store", parents=[_lib.common_parser()])
    font.add_argument("file", help="path to the regular face (TTF/OTF)")
    font.add_argument("--family", help="family name used in specs (defaults to the file stem)")
    font.add_argument("--bold", help="path to the bold face")
    font.add_argument("--italic", help="path to the italic face")
    font.add_argument("--bold-italic", dest="bold_italic", help="path to the bold-italic face")
    font.add_argument("--force", action="store_true", help="overwrite existing files")
    font.set_defaults(func=cmd_add_font)

    listing = subparsers.add_parser("list", help="list registered assets", parents=[_lib.common_parser()])
    listing.add_argument("--type", choices=("image", "font"), help="restrict to one kind")
    listing.set_defaults(func=cmd_list)

    remove = subparsers.add_parser("remove", help="remove a registered asset", parents=[_lib.common_parser()])
    remove.add_argument("name")
    remove.add_argument("--type", choices=("image", "font"), default="image")
    remove.add_argument("--keep-files", action="store_true", help="unregister a font without deleting its files")
    remove.set_defaults(func=cmd_remove)

    subparsers.add_parser("paths", help="print the asset, font, and output paths", parents=[_lib.common_parser()]).set_defaults(func=cmd_paths)
    return parser


if __name__ == "__main__":
    _lib.run_script("assets", build_parser())
