#!/usr/bin/env python3
"""Shared helpers for the charting skill scripts.

This module is NOT an entry point. Domain scripts import it directly
(``import _lib``) because Python places the script's own directory on
``sys.path[0]``.

Only the standard library is imported at module load, and this module never
imports a renderer. Rendering needs Node, Playwright, and the esbuild bundle,
all of which the render verb looks up lazily so the state, library, theme, and
report verbs keep working on a host without Node installed. Those verbs fail
fast with a ``dependency_missing`` error instead.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_HOME_DIR = "~/.local/share/charting"
DEFAULT_DB_NAME = "charting.db"
OUTPUT_DIR_NAME = "output"
TMP_DIR_NAME = "tmp"
SCHEMA_VERSION = 1
SPEC_VERSION = 1

CHART_FAMILIES = ("bar", "line", "area", "pie", "donut", "radar", "radial")
CARTESIAN_FAMILIES = ("bar", "line", "area")
PIE_FAMILIES = ("pie", "donut")
CURVES = ("linear", "monotone", "stepAfter", "step", "basis", "natural")
BAR_VARIANTS = ("grouped", "stacked", "horizontal")
THEMES = ("light", "dark")
LEGENDS = ("none", "top", "bottom", "right")
TICK_FORMATS = ("number", "percent", "currency", "compact", "raw")
MIN_DIMENSION = 64
MAX_DIMENSION = 4096
MIN_SCALE = 1
MAX_SCALE = 4

FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)

# ---------------------------------------------------------------------------
# Settings (stored as text in the meta table)
# ---------------------------------------------------------------------------

SETTING_DEFAULTS: Dict[str, str] = {
    "theme": "light",
    "palette": "default",
    "width": "720",
    "height": "420",
    "scale": "2",
    "background": "transparent",
    "font": "system",
    "grid": "true",
    "legend": "bottom",
    "output_dir": "",
}

ENV_OVERRIDES: Dict[str, str] = {
    "theme": "CHARTING_THEME",
    "palette": "CHARTING_PALETTE",
    "width": "CHARTING_WIDTH",
    "height": "CHARTING_HEIGHT",
    "scale": "CHARTING_SCALE",
    "background": "CHARTING_BACKGROUND",
    "font": "CHARTING_FONT",
    "grid": "CHARTING_GRID",
    "legend": "CHARTING_LEGEND",
    "output_dir": "CHARTING_OUTPUT_DIR",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS charts (
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
    chart_id     INTEGER REFERENCES charts(id) ON DELETE SET NULL,
    name         TEXT,
    out_path     TEXT NOT NULL,
    width_px     INTEGER,
    height_px    INTEGER,
    scale        INTEGER,
    bytes        INTEGER,
    sha256       TEXT,
    warnings     TEXT NOT NULL DEFAULT '',
    rendered_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_renders_chart ON renders(chart_id);
CREATE INDEX IF NOT EXISTS idx_renders_rendered_at ON renders(rendered_at);
CREATE INDEX IF NOT EXISTS idx_charts_name ON charts(name);
"""

# ---------------------------------------------------------------------------
# Themes and palette presets
# ---------------------------------------------------------------------------

# CSS custom properties for the two built-in themes. ``--chart-1..5`` are
# injected from the resolved palette by ``theme_tokens``.
LIGHT_TOKENS: Dict[str, str] = {
    "--background": "#ffffff",
    "--foreground": "#111827",
    "--card": "#ffffff",
    "--card-foreground": "#111827",
    "--muted": "#f4f4f5",
    "--muted-foreground": "#71717a",
    "--border": "#e4e4e7",
    "--input": "#e4e4e7",
    "--ring": "#7c3aed",
    "--radius": "10px",
}

DARK_TOKENS: Dict[str, str] = {
    "--background": "#09090b",
    "--foreground": "#fafafa",
    "--card": "#111113",
    "--card-foreground": "#fafafa",
    "--muted": "#27272a",
    "--muted-foreground": "#a1a1aa",
    "--border": "#27272a",
    "--input": "#27272a",
    "--ring": "#a78bfa",
    "--radius": "10px",
}

# Palette presets. ``default`` is the modern violet that matches the pack's
# restrained accent (#7C3AED family); the rest are neutral-to-warm variants.
PALETTES: Dict[str, List[str]] = {
    "default": ["#7c3aed", "#a78bfa", "#60a5fa", "#34d399", "#fbbf24"],
    "neutral": ["#18181b", "#52525b", "#a1a1aa", "#d4d4d8", "#e4e4e7"],
    "blue": ["#2563eb", "#60a5fa", "#93c5fd", "#38bdf8", "#0ea5e9"],
    "emerald": ["#059669", "#34d399", "#6ee7b7", "#10b981", "#14b8a6"],
    "amber": ["#d97706", "#f59e0b", "#fbbf24", "#fcd34d", "#fb923c"],
    "rose": ["#e11d48", "#fb7185", "#fda4af", "#f472b6", "#be123c"],
    "slate": ["#334155", "#64748b", "#94a3b8", "#cbd5e1", "#0f172a"],
}

_HEX_RE = re.compile(r"^#([0-9a-fA-F]{3,8})$")
_RGB_RE = re.compile(
    r"^rgba?\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*(?:,\s*[\d.]+\s*)?\)$"
)
_NAMED = {
    "black", "white", "red", "green", "blue", "yellow", "orange", "purple",
    "pink", "teal", "cyan", "magenta", "gray", "grey", "silver", "navy",
    "maroon", "olive", "lime", "aqua", "fuchsia", "gold", "brown",
}


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
    elif os.environ.get("CHARTING_HOME"):
        raw = os.environ["CHARTING_HOME"]
    else:
        raw = DEFAULT_HOME_DIR
    return Path(os.path.expanduser(raw))


def resolve_db_path(home: Path) -> Path:
    return Path(home) / DEFAULT_DB_NAME


def resolve_output_path(home: Path) -> Path:
    return Path(home) / OUTPUT_DIR_NAME


def resolve_tmp_path(home: Path) -> Path:
    return Path(home) / TMP_DIR_NAME


# ---------------------------------------------------------------------------
# Render dependencies (Node, the esbuild bundle, the Chromium browser)
# ---------------------------------------------------------------------------

SKILL_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_PATH = SKILL_ROOT / "scripts" / "vendor" / "chart-bundle.js"
INSTALL_HINT = "npm ci --prefix %s && node %s/scripts/build.mjs && npx --prefix %s playwright install chromium" % (
    SKILL_ROOT,
    SKILL_ROOT,
    SKILL_ROOT,
)


def bundle_path() -> Path:
    return BUNDLE_PATH


def playwright_browser_dirs() -> List[Path]:
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override and override not in ("0", ""):
        return [Path(os.path.expanduser(override))]
    home = Path.home()
    return [
        home / "Library" / "Caches" / "ms-playwright",
        home / ".cache" / "ms-playwright",
        home / "AppData" / "Local" / "ms-playwright",
    ]


def chromium_installed() -> bool:
    for directory in playwright_browser_dirs():
        if not directory.is_dir():
            continue
        for child in directory.iterdir():
            if child.name.startswith("chromium-") and child.is_dir():
                return True
    return False


def dependency_report() -> Dict[str, bool]:
    """Report which render pieces are present, without running any of them."""
    import shutil

    node_modules = SKILL_ROOT / "node_modules"
    return {
        "node": shutil.which("node") is not None,
        "npm": shutil.which("npm") is not None,
        "bundle": BUNDLE_PATH.is_file(),
        "playwright": (node_modules / "playwright" / "package.json").is_file(),
        "chromium": chromium_installed(),
    }


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


def parse_int(value: Any, default: int, minimum: int, maximum: int, field: str) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        raise CommandError("invalid_spec", "%s must be an integer, got %r" % (field, value))
    if not (minimum <= number <= maximum):
        raise CommandError(
            "invalid_spec", "%s must be between %d and %d, got %d" % (field, minimum, maximum, number)
        )
    return number


def is_color(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    if not text:
        return False
    return bool(_HEX_RE.match(text)) or bool(_RGB_RE.match(text)) or text in _NAMED


def _palette_key(key: Any) -> Optional[int]:
    text = str(key).strip().lower().replace("_", "-")
    match = re.match(r"^(?:chart-?)?([1-5])$", text)
    return int(match.group(1)) if match else None


def resolve_palette(value: Any) -> List[str]:
    """Resolve a palette name, an array of colors, or a token override map."""
    if value is None or value == "":
        return list(PALETTES["default"])
    if isinstance(value, str):
        name = value.strip().lower()
        if name not in PALETTES:
            raise CommandError(
                "invalid_spec",
                "unknown palette %r (try: %s)" % (value, ", ".join(sorted(PALETTES))),
            )
        return list(PALETTES[name])
    if isinstance(value, (list, tuple)):
        colors = [str(item).strip() for item in value if str(item).strip()]
        if not colors:
            raise CommandError("invalid_spec", "palette array is empty")
        if len(colors) > 5:
            raise CommandError("invalid_spec", "palette accepts at most 5 colors")
        for color in colors:
            if not is_color(color):
                raise CommandError("invalid_spec", "invalid palette color %r" % color)
        return colors
    if isinstance(value, dict):
        tokens = list(PALETTES["default"])
        for key, color in value.items():
            index = _palette_key(key)
            if index is None:
                raise CommandError(
                    "invalid_spec",
                    "palette override key %r must be chart-1..chart-5" % key,
                )
            if not is_color(color):
                raise CommandError("invalid_spec", "invalid palette color %r" % color)
            tokens[index - 1] = str(color).strip()
        return tokens
    raise CommandError("invalid_spec", "palette must be a name, an array, or an object")


def theme_tokens(theme: str, palette: Sequence[str]) -> Dict[str, str]:
    base = dict(LIGHT_TOKENS if theme == "light" else DARK_TOKENS)
    colors = list(palette) or list(PALETTES["default"])
    for index in range(5):
        base["--chart-%d" % (index + 1)] = colors[index % len(colors)]
    return base


def _series_color(index: int, series: Dict[str, Any]) -> str:
    explicit = series.get("color")
    if explicit:
        text = str(explicit).strip()
        if text.startswith("chart-") or text.startswith("--chart-"):
            token = text[2:] if text.startswith("--") else text
            return "var(--%s)" % token
        if is_color(text):
            return text
        raise CommandError("invalid_spec", "invalid series color %r" % explicit)
    return "var(--chart-%d)" % ((index % 5) + 1)


# ---------------------------------------------------------------------------
# Dict / file helpers
# ---------------------------------------------------------------------------

def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge ``override`` into a copy of ``base``."""
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    if override is None:
        return base
    return override


def slugify(value: str, fallback: str = "chart") -> str:
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


# ---------------------------------------------------------------------------
# Chart spec resolution
# ---------------------------------------------------------------------------

def _cartesian_x_key(spec: Dict[str, Any]) -> str:
    x = spec.get("x") or {}
    key = x.get("key") if isinstance(x, dict) else None
    return str(key).strip() if key else ""


def _tabular_rows(spec: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    data = spec.get("data")
    if data is None:
        return None
    if not isinstance(data, list):
        raise CommandError("invalid_spec", "'data' must be a list of objects")
    rows: List[Dict[str, Any]] = []
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise CommandError("invalid_spec", "data[%d] must be an object" % index)
        rows.append(dict(row))
    return rows


def _explicit_series(spec: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    series = spec.get("series")
    if series is None:
        return None
    if not isinstance(series, list):
        raise CommandError("invalid_spec", "'series' must be a list")
    resolved: List[Dict[str, Any]] = []
    for index, entry in enumerate(series):
        if isinstance(entry, str):
            resolved.append({"key": entry})
        elif isinstance(entry, dict):
            if not entry.get("key"):
                raise CommandError("invalid_spec", "series[%d] is missing 'key'" % index)
            resolved.append(dict(entry))
        else:
            raise CommandError("invalid_spec", "series[%d] must be a string or object" % index)
    return resolved


def _categories(spec: Dict[str, Any], count: int) -> List[Any]:
    explicit = spec.get("categories")
    if isinstance(explicit, list) and explicit:
        return list(explicit)
    x = spec.get("x") or {}
    labels = x.get("labels") if isinstance(x, dict) else None
    if isinstance(labels, list) and labels:
        return list(labels)
    return list(range(1, count + 1))


def resolve_rows_and_series(spec: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """Return ``(rows, series, x_key)`` for a cartesian family."""
    x_key = _cartesian_x_key(spec)
    if not x_key:
        raise CommandError("invalid_spec", "cartesian charts need x.key naming the category field")
    rows = _tabular_rows(spec)
    series = _explicit_series(spec)
    if series and any(isinstance(entry.get("values"), list) for entry in series):
        length = max((len(entry["values"]) for entry in series if isinstance(entry.get("values"), list)), default=0)
        labels = _categories(spec, length)
        rows = []
        for index in range(length):
            row: Dict[str, Any] = {x_key: labels[index] if index < len(labels) else index + 1}
            for entry in series:
                values = entry.get("values")
                if isinstance(values, list) and index < len(values):
                    row[entry["key"]] = values[index]
            rows.append(row)
    if rows is None:
        raise CommandError("invalid_spec", "provide 'data' rows or series with 'values'")
    if not rows:
        raise CommandError("invalid_spec", "'data' must contain at least one row")
    ordered: List[str] = []
    for row in rows:
        for key in row.keys():
            if key not in ordered:
                ordered.append(key)
    known = set(ordered)
    if not series:
        series = [
            {"key": key}
            for key in ordered
            if key != x_key and any(
                isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool) for row in rows
            )
        ]
    if not series:
        raise CommandError("invalid_spec", "no numeric series found; name them in 'series'")
    for entry in series:
        if entry["key"] not in known:
            raise CommandError(
                "invalid_spec",
                "series key %r is not present in 'data'" % entry["key"],
            )
    return rows, series, x_key


def resolve_pie_slices(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return ``[{name, value, value2?}]`` for pie/donut/radial families."""
    name_key = spec.get("name_key")
    value_key = spec.get("value_key")
    value_key_2 = spec.get("value_key_2")
    rows = _tabular_rows(spec)
    series = _explicit_series(spec)
    x_key = _cartesian_x_key(spec)
    slices: List[Dict[str, Any]] = []
    if series and isinstance(series[0].get("values"), list):
        labels = _categories(spec, len(series[0]["values"]))
        second = series[1].get("values") if len(series) > 1 and isinstance(series[1].get("values"), list) else None
        for index, value in enumerate(series[0]["values"]):
            slice_data: Dict[str, Any] = {"name": labels[index] if index < len(labels) else index + 1, "value": value}
            if second and index < len(second):
                slice_data["value2"] = second[index]
            slices.append(slice_data)
    elif rows is not None:
        if name_key and value_key:
            for row in rows:
                if name_key not in row or value_key not in row:
                    raise CommandError(
                        "invalid_spec",
                        "data rows need %r and %r fields" % (name_key, value_key),
                    )
                slice_data = {"name": row[name_key], "value": row[value_key]}
                if value_key_2 and value_key_2 in row:
                    slice_data["value2"] = row[value_key_2]
                slices.append(slice_data)
        elif series and x_key:
            key = series[0]["key"]
            for row in rows:
                if x_key not in row or key not in row:
                    raise CommandError("invalid_spec", "data rows need %r and %r fields" % (x_key, key))
                slice_data = {"name": row[x_key], "value": row[key]}
                if value_key_2 and value_key_2 in row:
                    slice_data["value2"] = row[value_key_2]
                slices.append(slice_data)
        else:
            raise CommandError(
                "invalid_spec",
                "pie/radial charts need name_key+value_key, or x.key plus one series",
            )
    else:
        raise CommandError("invalid_spec", "pie/radial charts need 'data' or a series with 'values'")
    if not slices:
        raise CommandError("invalid_spec", "no slices to draw")
    return slices


def validate_spec(spec: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Validate a chart spec; return ``(spec, warnings)``."""
    if not isinstance(spec, dict):
        raise CommandError("invalid_spec", "the chart spec must be a JSON object")
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
    family = spec.get("chart")
    if not isinstance(family, str) or not family:
        raise CommandError("invalid_spec", "'chart' is required and must be a family name")
    family = family.strip().lower()
    if family not in CHART_FAMILIES:
        raise CommandError(
            "invalid_spec",
            "unknown chart family %r (try: %s)" % (spec.get("chart"), ", ".join(CHART_FAMILIES)),
        )
    spec["chart"] = family

    if "variant" in spec and spec["variant"] is not None:
        if spec["variant"] not in BAR_VARIANTS:
            raise CommandError("invalid_spec", "variant must be one of %s" % ", ".join(BAR_VARIANTS))
    if "curve" in spec and spec["curve"] is not None and spec["curve"] not in CURVES:
        raise CommandError("invalid_spec", "curve must be one of %s" % ", ".join(CURVES))
    if "theme" in spec and spec["theme"] not in (None, "") and spec["theme"] not in THEMES:
        raise CommandError("invalid_spec", "theme must be 'light' or 'dark'")
    if "x" in spec and spec["x"] is not None and not isinstance(spec["x"], dict):
        raise CommandError("invalid_spec", "'x' must be an object")
    if "y" in spec and spec["y"] is not None and not isinstance(spec["y"], dict):
        raise CommandError("invalid_spec", "'y' must be an object")
    if "y" in spec and isinstance(spec.get("y"), dict) and spec["y"].get("format") not in (None, "", *TICK_FORMATS):
        raise CommandError("invalid_spec", "y.format must be one of %s" % ", ".join(TICK_FORMATS))

    legend = spec.get("legend")
    if isinstance(legend, str) and legend not in LEGENDS:
        raise CommandError("invalid_spec", "legend must be one of %s" % ", ".join(LEGENDS))

    for key in ("expand", "axes", "labels", "separator", "negative", "pie_stacked",
                "radial_grid", "radial_labels", "radial_stacked", "radar_dots",
                "radar_grid_fill", "fill", "legend_values"):
        if key in spec and spec[key] is not None and not isinstance(spec[key], bool):
            raise CommandError("invalid_spec", "%r must be true or false" % key)
    if "radar_grid" in spec and spec["radar_grid"] not in (None, "", "polygon", "circle", "none"):
        raise CommandError("invalid_spec", "radar_grid must be polygon, circle, or none")
    if "active" in spec and spec["active"] is not None:
        try:
            spec["active"] = int(spec["active"])
        except (TypeError, ValueError):
            raise CommandError("invalid_spec", "'active' must be an integer index")
        if spec["active"] < 0:
            raise CommandError("invalid_spec", "'active' must be >= 0")
    if "outer_radius" in spec and spec["outer_radius"] is not None:
        if not isinstance(spec["outer_radius"], (str, int, float)):
            raise CommandError("invalid_spec", "outer_radius must be a percent string or number")
    if "value_key_2" in spec and spec["value_key_2"] is not None and not isinstance(spec["value_key_2"], str):
        raise CommandError("invalid_spec", "value_key_2 must be a string")
    if "radial_corner" in spec and spec["radial_corner"] is not None:
        try:
            spec["radial_corner"] = int(spec["radial_corner"])
        except (TypeError, ValueError):
            raise CommandError("invalid_spec", "radial_corner must be an integer")

    width = parse_int(spec.get("width", 720), 720, MIN_DIMENSION, MAX_DIMENSION, "width")
    height = parse_int(spec.get("height", 420), 420, MIN_DIMENSION, MAX_DIMENSION, "height")
    scale_raw = spec.get("scale", 2)
    try:
        scale = int(scale_raw)
    except (TypeError, ValueError):
        raise CommandError("invalid_spec", "scale must be an integer")
    if not (MIN_SCALE <= scale <= MAX_SCALE):
        raise CommandError("invalid_spec", "scale must be between %d and %d" % (MIN_SCALE, MAX_SCALE))
    spec["width"] = width
    spec["height"] = height
    spec["scale"] = scale
    parse_int(spec.get("padding", 16), 16, 0, 200, "padding")
    parse_int(spec.get("radius", 4), 4, 0, 40, "radius")

    # Resolve the palette (raises on a bad name/array/object).
    resolve_palette(spec.get("palette"))

    if family in CARTESIAN_FAMILIES:
        resolve_rows_and_series(spec)
    if family in PIE_FAMILIES:
        resolve_pie_slices(spec)
    if family == "radar":
        rows, series, _ = resolve_rows_and_series(spec)
        if len(series) < 1:
            raise CommandError("invalid_spec", "radar charts need at least one series")
        axis_key = spec.get("axis_key") or _cartesian_x_key(spec)
        if not axis_key:
            raise CommandError("invalid_spec", "radar charts need axis_key or x.key")
        if rows and axis_key not in rows[0]:
            raise CommandError("invalid_spec", "radar axis key %r is not present in 'data'" % axis_key)
    if family == "radial":
        resolve_pie_slices(spec)
    return spec, warnings


def apply_settings(spec: Dict[str, Any], settings: Dict[str, str]) -> Dict[str, Any]:
    """Fill spec fields that were not set from the stored settings."""
    resolved = dict(spec)
    if resolved.get("theme") in (None, ""):
        resolved["theme"] = settings.get("theme", "light")
    if resolved.get("palette") in (None, ""):
        resolved["palette"] = settings.get("palette", "default")
    if resolved.get("background") in (None, ""):
        resolved["background"] = settings.get("background", "transparent")
    if resolved.get("font") in (None, ""):
        resolved["font"] = settings.get("font", "system")
    if "grid" not in resolved or resolved.get("grid") is None:
        resolved["grid"] = parse_bool(settings.get("grid"), True)
    if resolved.get("legend") in (None, ""):
        resolved["legend"] = settings.get("legend", "bottom")
    for key in ("width", "height", "scale"):
        if resolved.get(key) in (None, ""):
            try:
                resolved[key] = int(str(settings.get(key)).strip())
            except (TypeError, ValueError):
                pass
    return resolved


# ---------------------------------------------------------------------------
# PNG header (stdlib only; no Pillow)
# ---------------------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_COLOR_TYPES = {
    0: "grayscale",
    2: "truecolor",
    3: "indexed",
    4: "grayscale-alpha",
    6: "truecolor-alpha",
}


def png_info(path: Path) -> Dict[str, Any]:
    """Read a PNG's IHDR with the standard library only."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(33)
    except FileNotFoundError:
        raise CommandError("not_found", "PNG not found: %s" % path)
    except OSError as exc:
        raise CommandError("io_error", "could not read %s: %s" % (path, exc))
    if len(header) < 33 or header[:8] != PNG_SIGNATURE:
        raise CommandError("invalid_png", "%s is not a PNG file" % path)
    if header[12:16] != b"IHDR":
        raise CommandError("invalid_png", "%s is missing an IHDR chunk" % path)
    width, height = struct.unpack(">II", header[16:24])
    bit_depth = header[24]
    color_type = header[25]
    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "color_type_name": _PNG_COLOR_TYPES.get(color_type, "unknown"),
    }


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
    installs, enables, disables, or removes anything itself.
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
