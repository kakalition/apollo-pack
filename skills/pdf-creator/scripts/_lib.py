#!/usr/bin/env python3
"""Shared helpers for the pdf-creator skill scripts.

This module is NOT an entry point. Domain scripts import it directly
(``import _lib``) because Python places the script's own directory on
``sys.path[0]``.

Only the standard library is imported at module load, and this module never
imports a rendering engine. ``reportlab`` (and optional ``Pillow``) are
imported lazily by :mod:`_engine` and :mod:`render`, so the state, library, and
metadata verbs keep working on a host that has a data root but no renderer
installed. Those verbs fail fast with a ``dependency_missing`` error instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_HOME_DIR = "~/.local/share/pdf-creator"
DEFAULT_DB_NAME = "pdf-creator.db"
ASSETS_DIR_NAME = "assets"
FONTS_DIR_NAME = "fonts"
OUTPUT_DIR_NAME = "output"
SCHEMA_VERSION = 1
SPEC_VERSION = 1

# ---------------------------------------------------------------------------
# Settings (stored as text in the meta table)
# ---------------------------------------------------------------------------

SETTING_DEFAULTS: Dict[str, str] = {
    "page_size": "A4",
    "orientation": "portrait",
    "unit": "mm",
    "margin_top": "20mm",
    "margin_right": "18mm",
    "margin_bottom": "20mm",
    "margin_left": "18mm",
    "theme": "default",
    "font_family": "Helvetica",
    "font_size": "10.5",
    "line_height": "1.4",
    "heading_scale": "1.0",
    "text_color": "#1A1A1A",
    "accent": "#2563EB",
    "author": "",
    "language": "en",
    "output_dir": "",
    "allow_remote": "false",
}

ENV_OVERRIDES: Dict[str, str] = {
    "page_size": "PDF_CREATOR_PAGE_SIZE",
    "orientation": "PDF_CREATOR_ORIENTATION",
    "unit": "PDF_CREATOR_UNIT",
    "theme": "PDF_CREATOR_THEME",
    "font_family": "PDF_CREATOR_FONT_FAMILY",
    "font_size": "PDF_CREATOR_FONT_SIZE",
    "line_height": "PDF_CREATOR_LINE_HEIGHT",
    "text_color": "PDF_CREATOR_TEXT_COLOR",
    "accent": "PDF_CREATOR_ACCENT",
    "author": "PDF_CREATOR_AUTHOR",
    "language": "PDF_CREATOR_LANGUAGE",
    "output_dir": "PDF_CREATOR_OUTPUT_DIR",
    "allow_remote": "PDF_CREATOR_ALLOW_REMOTE",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS documents (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL UNIQUE,
    title            TEXT,
    spec             TEXT NOT NULL,
    tags             TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    render_count     INTEGER NOT NULL DEFAULT 0,
    last_rendered_at TEXT,
    last_output      TEXT
);

CREATE TABLE IF NOT EXISTS renders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    name         TEXT,
    out_path     TEXT NOT NULL,
    pages        INTEGER,
    bytes        INTEGER,
    sha256       TEXT,
    width_pt     REAL,
    height_pt    REAL,
    warnings     TEXT NOT NULL DEFAULT '',
    rendered_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_renders_document ON renders(document_id);
CREATE INDEX IF NOT EXISTS idx_renders_rendered_at ON renders(rendered_at);
CREATE INDEX IF NOT EXISTS idx_documents_name ON documents(name);
"""

# Block types the renderer understands. Keep in sync with references/schema.md
# and the builders in _engine.py.
BLOCK_TYPES = (
    "heading",
    "paragraph",
    "rich",
    "list",
    "table",
    "image",
    "figure",
    "code",
    "callout",
    "blockquote",
    "divider",
    "hr",
    "spacer",
    "page_break",
    "page_template",
    "columns",
    "toc",
    "checkbox_list",
    "definition_list",
    "key_values",
    "anchor",
    "qr",
    "barcode",
)

PAGE_TEMPLATES = ("body", "cover", "title", "two_column", "three_column", "landscape", "blank")


class CommandError(Exception):
    """A user-facing error rendered as a JSON error envelope."""

    def __init__(self, code: str, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# Data root / database
# ---------------------------------------------------------------------------

def resolve_home(cli_value: Optional[str] = None) -> Path:
    if cli_value:
        raw = cli_value
    elif os.environ.get("PDF_CREATOR_HOME"):
        raw = os.environ["PDF_CREATOR_HOME"]
    else:
        raw = DEFAULT_HOME_DIR
    return Path(os.path.expanduser(raw))


def resolve_db_path(home: Path) -> Path:
    return Path(home) / DEFAULT_DB_NAME


def resolve_assets_path(home: Path) -> Path:
    return Path(home) / ASSETS_DIR_NAME


def resolve_fonts_path(home: Path) -> Path:
    return Path(home) / FONTS_DIR_NAME


def resolve_output_path(home: Path) -> Path:
    return Path(home) / OUTPUT_DIR_NAME


def resolve_output_dir(conn: sqlite3.Connection, home: Path) -> Path:
    configured = effective_setting(conn, "output_dir").strip()
    if configured:
        return Path(os.path.expanduser(configured))
    return resolve_output_path(home)


def connect(db_path: Path) -> sqlite3.Connection:
    db_path = Path(os.path.expanduser(str(db_path)))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
    conn.commit()


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def get_meta(conn: sqlite3.Connection, key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return default
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, "" if value is None else str(value)),
    )


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    return get_meta(conn, key, SETTING_DEFAULTS.get(key, "")) or ""


def effective_setting(conn: sqlite3.Connection, key: str) -> str:
    """The stored setting, unless a namespaced host env var overrides it."""
    env_name = ENV_OVERRIDES.get(key)
    if env_name:
        value = os.environ.get(env_name)
        if value is not None and value.strip() != "":
            return value
    return get_setting(conn, key)


def active_env_overrides() -> Dict[str, str]:
    active: Dict[str, str] = {}
    for key, env_name in ENV_OVERRIDES.items():
        value = os.environ.get(env_name)
        if value is not None and value.strip() != "":
            active[key] = value
    return active


def setting_float(conn: sqlite3.Connection, key: str, default: float = 0.0) -> float:
    raw = effective_setting(conn, key)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return float(default)


def setting_bool(conn: sqlite3.Connection, key: str, default: bool = False) -> bool:
    raw = effective_setting(conn, key)
    return parse_bool(raw, default)


def settings_snapshot(conn: sqlite3.Connection) -> Dict[str, str]:
    snapshot = dict(SETTING_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM meta"):
        snapshot[row["key"]] = row["value"]
    return snapshot


def effective_settings(conn: sqlite3.Connection) -> Dict[str, str]:
    """Every setting after applying the namespaced host environment overrides."""
    return {key: effective_setting(conn, key) for key in SETTING_DEFAULTS}


# ---------------------------------------------------------------------------
# Generic value parsing
# ---------------------------------------------------------------------------

def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on"):
        return True
    if text in ("0", "false", "no", "n", "off"):
        return False
    return default


# Points per unit.
_UNIT_FACTORS: Dict[str, float] = {
    "pt": 1.0,
    "px": 0.75,
    "in": 72.0,
    "cm": 72.0 / 2.54,
    "mm": 72.0 / 25.4,
    "pc": 12.0,
    "q": 72.0 / 25.4 / 4.0,
}

_LENGTH_RE = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+))\s*([a-zA-Z%]*)\s*$")


def parse_length(
    value: Any,
    unit: str = "pt",
    base: Optional[float] = None,
    *,
    allow_percent: bool = False,
    allow_auto: bool = False,
    field: str = "length",
) -> Optional[float]:
    """Parse a CSS-ish dimension to points.

    Bare numbers are interpreted in ``unit``. Strings may carry a suffix
    (``pt``, ``px``, ``in``, ``cm``, ``mm``, ``pc``, ``q``, ``%``). ``%`` needs
    ``base`` and ``allow_percent``; ``auto`` returns ``None`` when
    ``allow_auto``. Raises :class:`CommandError` on anything else.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) * _UNIT_FACTORS.get(unit, 1.0)
    text = str(value).strip()
    if not text:
        return None
    if text.lower() == "auto":
        if allow_auto:
            return None
        raise CommandError("invalid_input", "%s does not accept 'auto'" % field)
    match = _LENGTH_RE.match(text)
    if not match:
        raise CommandError("invalid_input", "invalid %s %r" % (field, value))
    number = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "%":
        if not allow_percent or base is None:
            raise CommandError("invalid_input", "%s does not accept a percentage: %r" % (field, value))
        return number / 100.0 * float(base)
    factor = _UNIT_FACTORS.get(suffix) if suffix else _UNIT_FACTORS.get(unit, 1.0)
    if factor is None:
        raise CommandError("invalid_input", "unknown unit %r in %s %r" % (suffix, field, value))
    return number * factor


_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3,8})$")
_RGB_RE = re.compile(
    r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$"
)

# A compact CSS color table. Hex, rgb(), and rgba() always work; this covers the
# names people actually type. Values are 0-255.
NAMED_COLORS: Dict[str, Tuple[int, int, int]] = {
    "black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0),
    "lime": (0, 255, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
    "yellow": (255, 255, 0), "cyan": (0, 255, 255), "aqua": (0, 255, 255),
    "magenta": (255, 0, 255), "fuchsia": (255, 0, 255), "silver": (192, 192, 192),
    "gray": (128, 128, 128), "grey": (128, 128, 128), "maroon": (128, 0, 0),
    "olive": (128, 128, 0), "purple": (128, 0, 128), "teal": (0, 128, 128),
    "navy": (0, 0, 128), "orange": (255, 165, 0), "gold": (255, 215, 0),
    "pink": (255, 192, 203), "hotpink": (255, 105, 180), "brown": (165, 42, 42),
    "beige": (245, 245, 220), "ivory": (255, 255, 240), "khaki": (240, 230, 140),
    "indigo": (75, 0, 130), "violet": (238, 130, 238), "plum": (221, 160, 221),
    "orchid": (218, 112, 214), "salmon": (250, 128, 114), "coral": (255, 127, 80),
    "tomato": (255, 99, 71), "crimson": (220, 20, 60), "firebrick": (178, 34, 34),
    "chocolate": (210, 105, 30), "peru": (205, 133, 63), "tan": (210, 180, 140),
    "lightgray": (211, 211, 211), "lightgrey": (211, 211, 211),
    "darkgray": (169, 169, 169), "darkgrey": (169, 169, 169),
    "slategray": (112, 128, 144), "slategrey": (112, 128, 144),
    "dimgray": (105, 105, 105), "dimgrey": (105, 105, 105),
    "whitesmoke": (245, 245, 245), "gainsboro": (220, 220, 220),
    "lightblue": (173, 216, 230), "skyblue": (135, 206, 235),
    "steelblue": (70, 130, 180), "royalblue": (65, 105, 225),
    "dodgerblue": (30, 144, 255), "cornflowerblue": (100, 149, 237),
    "midnightblue": (25, 25, 112), "darkblue": (0, 0, 139),
    "lightgreen": (144, 238, 144), "forestgreen": (34, 139, 34),
    "seagreen": (46, 139, 87), "mediumseagreen": (60, 179, 113),
    "darkgreen": (0, 100, 0), "olivedrab": (107, 142, 35),
    "darkred": (139, 0, 0), "darkorange": (255, 140, 0),
    "darkgoldenrod": (184, 134, 11), "goldenrod": (218, 165, 32),
    "lightyellow": (255, 255, 224), "lemonchiffon": (255, 250, 205),
    "lightcyan": (224, 255, 255), "powderblue": (176, 224, 230),
    "lightpink": (255, 182, 193), "lightcoral": (240, 128, 128),
    "lavender": (230, 230, 250), "thistle": (216, 191, 216),
    "transparent": (255, 255, 255),
}


def parse_color(value: Any, default: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 1.0)) -> Tuple[float, float, float, float]:
    """Parse a color to an ``(r, g, b, a)`` tuple of floats in 0..1."""
    if value is None:
        return default
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        parts = [float(v) for v in value]
        if max(parts[:3]) > 1.0:
            parts = [v / 255.0 for v in parts[:3]] + parts[3:]
        if len(parts) == 3:
            parts.append(1.0)
        return (parts[0], parts[1], parts[2], parts[3])
    text = str(value).strip().lower()
    if text in ("none", ""):
        return (0.0, 0.0, 0.0, 0.0)
    if text in NAMED_COLORS:
        r, g, b = NAMED_COLORS[text]
        return (r / 255.0, g / 255.0, b / 255.0, 0.0 if text == "transparent" else 1.0)
    match = _HEX_RE.match(text)
    if match:
        digits = match.group(1)
        if len(digits) in (3, 4):
            vals = [int(d * 2, 16) for d in digits]
        else:
            vals = [int(digits[i:i + 2], 16) for i in range(0, len(digits), 2)]
        r, g, b = vals[0], vals[1], vals[2]
        a = (vals[3] / 255.0) if len(vals) == 4 else 1.0
        return (r / 255.0, g / 255.0, b / 255.0, a)
    match = _RGB_RE.match(text)
    if match:
        r, g, b = (float(match.group(i)) for i in (1, 2, 3))
        a = float(match.group(4)) if match.group(4) is not None else 1.0
        return (r / 255.0, g / 255.0, b / 255.0, a)
    raise CommandError("invalid_input", "invalid color %r" % value)


# ---------------------------------------------------------------------------
# Text / inline markup
# ---------------------------------------------------------------------------

def escape_xml(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def inline_markup(
    text: Any,
    *,
    code_font: Optional[str] = None,
    allow_html: bool = False,
) -> str:
    """Convert a small, well-defined Markdown subset to reportlab markup.

    Supported: ``**bold**``/``__bold__``, ``*italic*``/``_italic_``,
    ``~~strike~~``, `` `code` ``, ``[label](url)``, ``^superscript^``,
    ``~subscript~``, and newlines as ``<br/>``. When ``allow_html`` is true the
    text is treated as trusted reportlab markup and passed through (newlines
    still become ``<br/>``).
    """
    if text is None:
        return ""
    raw = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if allow_html:
        return raw.replace("\n", "<br/>")

    escaped = escape_xml(raw)

    codes: List[str] = []

    def _stash_code(match: "re.Match[str]") -> str:
        codes.append(match.group(1))
        return "\x00%d\x00" % (len(codes) - 1)

    escaped = re.sub(r"`([^`]+)`", _stash_code, escaped)
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: '<link href="%s">%s</link>' % (m.group(2), m.group(1)),
        escaped,
    )
    # Bold before italic so ** is consumed first.
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped, flags=re.S)
    escaped = re.sub(r"__(.+?)__", r"<b>\1</b>", escaped, flags=re.S)
    escaped = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", escaped, flags=re.S)
    escaped = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"<i>\1</i>", escaped, flags=re.S)
    escaped = re.sub(r"~~(.+?)~~", r"<strike>\1</strike>", escaped, flags=re.S)
    escaped = re.sub(r"\^([^\^\n]+)\^", r"<super>\1</super>", escaped)
    escaped = re.sub(r"(?<!~)~([^~\n]+)~(?!~)", r"<sub>\1</sub>", escaped)

    def _restore_code(match: "re.Match[str]") -> str:
        inner = codes[int(match.group(1))]
        if code_font:
            return '<font name="%s">%s</font>' % (code_font, inner)
        return "<font>%s</font>" % inner

    escaped = re.sub("\x00(\\d+)\x00", _restore_code, escaped)
    return escaped.replace("\n", "<br/>")


def plain_text(markup: str) -> str:
    """Strip reportlab markup to a plain string (for TOC entries, sizes)."""
    text = re.sub(r"<[^>]+>", "", str(markup or ""))
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
    )


# ---------------------------------------------------------------------------
# Dict helpers
# ---------------------------------------------------------------------------

def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge ``override`` into a copy of ``base``."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            if key in merged and isinstance(merged[key], (dict,)) and isinstance(value, dict):
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    if override is None:
        return base
    return override


def slugify(value: str, fallback: str = "document") -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return text or fallback


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# Spec loading and validation
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise CommandError("not_found", "file not found: %s" % path)
    except OSError as exc:
        raise CommandError("io_error", "could not read %s: %s" % (path, exc))
    try:
        return json.loads(text)
    except ValueError as exc:
        raise CommandError("invalid_spec", "%s is not valid JSON: %s" % (path, exc))


def substitute_vars(value: Any, variables: Dict[str, str]) -> Any:
    """Replace ``{{name}}`` tokens in every string of a spec tree."""
    if not variables:
        return value
    if isinstance(value, str):
        def repl(match: "re.Match[str]") -> str:
            return variables.get(match.group(1), match.group(0))
        return re.sub(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}", repl, value)
    if isinstance(value, list):
        return [substitute_vars(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: substitute_vars(item, variables) for key, item in value.items()}
    return value


def load_spec(path: Optional[Path], variables: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    if path is None:
        raise CommandError("invalid_input", "a spec file is required")
    spec = load_json(path)
    if not isinstance(spec, dict):
        raise CommandError("invalid_spec", "%s must contain a JSON object" % path)
    if variables:
        spec = substitute_vars(spec, variables)
    return spec


def validate_spec(spec: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Validate the shape of a document spec; return ``(spec, warnings)``."""
    if not isinstance(spec, dict):
        raise CommandError("invalid_spec", "the document spec must be a JSON object")
    warnings: List[str] = []
    version = spec.get("spec_version", SPEC_VERSION)
    try:
        version_int = int(version)
    except (TypeError, ValueError):
        raise CommandError("invalid_spec", "spec_version must be an integer")
    if version_int > SPEC_VERSION:
        raise CommandError(
            "invalid_spec",
            "spec_version %d is newer than this skill supports (%d)" % (version_int, SPEC_VERSION),
        )
    for key in ("meta", "page", "styles", "toc", "security"):
        if key in spec and spec[key] is not None and not isinstance(spec[key], dict):
            raise CommandError("invalid_spec", "%r must be an object" % key)
    if "theme" in spec and not isinstance(spec["theme"], (str, dict)):
        raise CommandError("invalid_spec", "'theme' must be a name or an object")
    if "fonts" in spec and not isinstance(spec["fonts"], list):
        raise CommandError("invalid_spec", "'fonts' must be a list")
    if "header" in spec and not isinstance(spec["header"], (str, dict)):
        raise CommandError("invalid_spec", "'header' must be a string or an object")
    if "footer" in spec and not isinstance(spec["footer"], (str, dict)):
        raise CommandError("invalid_spec", "'footer' must be a string or an object")
    if "content" in spec and not isinstance(spec["content"], list):
        raise CommandError("invalid_spec", "'content' must be a list of blocks")

    def check_blocks(blocks: Any, where: str) -> None:
        if blocks is None:
            return
        if not isinstance(blocks, list):
            raise CommandError("invalid_spec", "%s must be a list of blocks" % where)
        for index, block in enumerate(blocks):
            location = "%s[%d]" % (where, index)
            if isinstance(block, str):
                continue
            if not isinstance(block, dict):
                raise CommandError("invalid_spec", "%s must be a block object or string" % location)
            block_type = block.get("type", "paragraph")
            if block_type not in BLOCK_TYPES:
                raise CommandError("invalid_spec", "%s has unknown type %r" % (location, block_type))
            if block_type in ("list", "columns") and "content" in block:
                check_blocks(block.get("content"), location + ".content")
            if block_type == "columns" and isinstance(block.get("columns"), list):
                for col_index, column in enumerate(block["columns"]):
                    check_blocks(column, "%s.columns[%d]" % (location, col_index))

    check_blocks(spec.get("content"), "content")
    return spec, warnings


# ---------------------------------------------------------------------------
# Scheduling manage actions
# ---------------------------------------------------------------------------

SCHEDULE_ACTIONS = ("add", "enable", "disable", "remove", "list")


def add_action_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--action",
        choices=list(SCHEDULE_ACTIONS),
        default="add",
        help="emit an artifact to add, enable, disable, remove, or list the job",
    )
    parser.add_argument("--job", help="job name or id for enable/disable/remove/list")


def manage_artifact(
    action: str,
    job: Optional[str],
    *,
    target: str,
    path_mode: str,
    tz: str,
    name: str,
    script: str,
    store: str,
    generated_at: str,
    skill_dir: str,
    prog: str,
    service: str,
    timer: str,
    plist: str,
    add_command: str,
    family: str,
    cli_name: Optional[str] = None,
    add_note: str = "",
) -> Dict[str, Any]:
    """Build a non-``add`` scheduling artifact.

    Like ``add``, this only emits an instruction: ``schedule-hint`` never
    installs, enables, disables, or removes anything itself. The artifact names
    the host action and the routes that can carry it out.
    """
    if action not in SCHEDULE_ACTIONS:
        raise CommandError("invalid_input", "unknown --action %r" % action)
    if action in ("enable", "disable", "remove") and not job:
        raise CommandError("invalid_input", "--job is required for --action %s" % action)
    resolved_job = job or name
    support = {key: False for key in SCHEDULE_ACTIONS}
    routes: List[Dict[str, Any]] = []

    if family == "chat":
        support.update({"add": True, "list": True, "remove": True})
        via = "chat_cron_tool"
        if action == "list":
            routes.append({"via": "cron_tool", "action": "list"})
        elif action == "remove":
            routes.append({"via": "cron_tool", "action": "remove", "params": {"job_id": resolved_job}})
        elif action == "disable":
            routes.append({
                "via": "webui_automations", "action": "disable", "params": {"id": resolved_job},
                "note": "requires the WebUI API token",
            })
            routes.append({
                "via": "cron_tool", "action": "remove", "params": {"job_id": resolved_job},
                "note": "blunt off: deletes the job; re-add to restore",
            })
        else:
            routes.append({
                "via": "webui_automations", "action": "enable", "params": {"id": resolved_job},
                "note": "requires the WebUI API token",
            })
            routes.append({
                "via": "cron_tool", "action": "add",
                "note": "if the job was deleted, re-create it with --action add",
            })
    elif family == "cli":
        support.update({"add": True, "list": True, "remove": True})
        via = "cli"
        cli = cli_name or "cron"
        if action == "list":
            routes.append({"via": "cli", "command": "%s cron ls" % cli})
        elif action == "remove":
            routes.append({"via": "cli", "command": "%s cron rm %s" % (cli, resolved_job)})
        else:
            routes.append({
                "via": "cli", "command": "%s cron %s %s" % (cli, action, resolved_job),
                "note": "confirm the exact subcommand in your host CLI",
            })
    elif family == "host":
        support.update({key: True for key in SCHEDULE_ACTIONS})
        via = "host"
        routes.append({"via": "host", "action": action, "job": resolved_job})
    else:
        support.update({key: True for key in SCHEDULE_ACTIONS})
        via = "os"
        if target == "crontab":
            routes.append({
                "via": "crontab", "action": action,
                "note": "edit with crontab -e; comment to disable, uncomment to enable, delete to remove",
            })
        elif target == "systemd":
            commands = {
                "list": ["systemctl --user list-timers"],
                "enable": ["systemctl --user enable --now %s" % timer],
                "disable": ["systemctl --user disable --now %s" % timer],
                "remove": [
                    "systemctl --user disable --now %s" % timer,
                    "rm ~/.config/systemd/user/%s ~/.config/systemd/user/%s" % (service, timer),
                ],
            }
            routes.append({"via": "systemd", "action": action, "commands": commands[action]})
        else:
            commands = {
                "list": ["launchctl list | grep %s" % prog],
                "enable": ["launchctl load ~/Library/LaunchAgents/%s" % plist],
                "disable": ["launchctl unload ~/Library/LaunchAgents/%s" % plist],
                "remove": [
                    "launchctl unload ~/Library/LaunchAgents/%s" % plist,
                    "rm ~/Library/LaunchAgents/%s" % plist,
                ],
            }
            routes.append({"via": "launchd", "action": action, "commands": commands[action]})

    instructions = (
        "This is an instruction only; schedule-hint installs and changes nothing. "
        "Apply --action %s for job %r through one of the routes below." % (action, resolved_job)
    )
    if add_note:
        instructions += " " + add_note
    return {
        "target": target,
        "path_mode": path_mode,
        "generated_at": generated_at,
        "skill_dir": skill_dir,
        "script": script,
        "store": store,
        "name": name,
        "action": action,
        "job": resolved_job,
        "tz": tz,
        "cron_expr": None,
        "commands": [],
        "installs_nothing": True,
        "read_only": True,
        "host_support": support,
        "via": via,
        "routes": routes,
        "add_command": add_command,
        "instructions": instructions,
        "notes": [
            "schedule-hint never installs, enables, disables, or removes anything itself.",
            "Re-create or re-run the job with add_command when a route requires it.",
        ],
    }


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--home", metavar="DIR", help="data root directory")
    parser.add_argument(
        "--format", choices=("json", "table"), default="json", help="output format"
    )
    parser.add_argument("--tz", metavar="ZONE", help="override the timezone for this call")
    parser.add_argument(
        "--quiet", action="store_true", help="suppress success output (errors still print)"
    )
    return parser


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _render_rows(rows: Sequence[Dict[str, Any]]) -> str:
    if not rows:
        return "(none)"
    headers: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in headers:
                headers.append(key)
    cells = [[_cell(row.get(h)) for h in headers] for row in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))
    lines = ["  ".join(h.ljust(widths[idx]) for idx, h in enumerate(headers))]
    lines.append("  ".join("-" * widths[idx] for idx in range(len(headers))))
    for row in cells:
        lines.append("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))
    return "\n".join(lines)


def render_table(data: Any) -> str:
    if isinstance(data, list):
        return _render_rows(data)
    if isinstance(data, dict):
        lines: List[str] = []
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                nested = _render_rows(value).splitlines()
                lines.append("%s:" % key)
                lines.append("\n".join("    " + line for line in nested))
            else:
                lines.append("%s: %s" % (key, _cell(value)))
        return "\n".join(lines) if lines else "(empty)"
    return _cell(data)


def emit(command: str, data: Any, fmt: str = "json", quiet: bool = False) -> None:
    if quiet:
        return
    if fmt == "table":
        sys.stdout.write(render_table(data) + "\n")
    else:
        sys.stdout.write(
            json.dumps(
                {"ok": True, "command": command, "data": data},
                indent=2,
                ensure_ascii=False,
                default=str,
            )
            + "\n"
        )


def fail(code: str, message: str, exit_code: int = 1) -> None:
    sys.stdout.write(
        json.dumps(
            {"ok": False, "error": {"code": code, "message": message}},
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    sys.exit(exit_code)


def run_script(domain: str, parser: argparse.ArgumentParser, *, needs_db: bool = True) -> None:
    args = parser.parse_args()
    fmt = getattr(args, "format", "json")
    quiet = getattr(args, "quiet", False)
    verb = getattr(args, "command", None) or getattr(args, "verb", domain)
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help(sys.stderr)
        sys.exit(2)
    home = resolve_home(getattr(args, "home", None))
    try:
        home.mkdir(parents=True, exist_ok=True)
        if needs_db:
            conn = connect(resolve_db_path(home))
            try:
                migrate(conn)
                data = handler(conn, home, args)
                conn.commit()
            finally:
                conn.close()
        else:
            data = handler(home, args)
        emit("%s.%s" % (domain, verb), data, fmt, quiet)
    except CommandError as exc:
        fail(exc.code, exc.message, exc.exit_code)
    except sqlite3.IntegrityError as exc:
        fail("conflict", str(exc))
    except sqlite3.Error as exc:
        fail("db_error", str(exc))
    except BrokenPipeError:
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # pragma: no cover - defensive
        fail("internal_error", "%s: %s" % (type(exc).__name__, exc))


def add_subparser(subparsers: Any, name: str, help_text: str, parents: Sequence[Any]) -> Any:
    parser = subparsers.add_parser(
        name, help=help_text, description=help_text, parents=list(parents)
    )
    parser.set_defaults(verb=name)
    return parser
