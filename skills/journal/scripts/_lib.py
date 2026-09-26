#!/usr/bin/env python3
"""Shared helpers for the journal skill scripts.

This module is NOT an entry point. Domain scripts import it directly
(``import _lib``) because Python places the script's own directory on
``sys.path[0]``.

Pure standard library, compatible with Python 3.9+. No network access. Word
counts, term frequencies, and weekly summaries are computed here so the prose
around the skill never computes them itself. Search uses SQLite FTS5 when the
build provides it and falls back to a plain ``LIKE`` scan when it does not.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_DB_DIR = "~/.local/share/journal"
DEFAULT_DB_NAME = "journal.db"
DEFAULT_TZ = "UTC"
SCHEMA_VERSION = 1

DEFAULT_REVIEW_PROMPT = (
    "Write a short weekly review from these entries only: themes, mood shifts, "
    "and open loops. Name nothing that is not in the entries."
)

SETTING_DEFAULTS: Dict[str, str] = {
    "tz": DEFAULT_TZ,
    "week_start": "mon",
    "default_limit": "20",
    "review_prompt": DEFAULT_REVIEW_PROMPT,
}

ENV_OVERRIDES: Dict[str, str] = {
    "tz": "JOURNAL_TZ",
    "week_start": "JOURNAL_WEEK_START",
    "default_limit": "JOURNAL_DEFAULT_LIMIT",
    "review_prompt": "JOURNAL_REVIEW_PROMPT",
}

WEEK_STARTS = ("mon", "sun")
ORDERS = ("asc", "desc")
NOTABLE_LIMIT = 5
TOP_TERM_LIMIT = 10

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    title      TEXT,
    body       TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    source     TEXT
);

CREATE INDEX IF NOT EXISTS idx_entries_date ON entries(entry_date);
"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    body, title, content='entries', content_rowid='id', tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, body, title) VALUES (new.id, new.body, new.title);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, body, title)
    VALUES ('delete', old.id, old.body, old.title);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, body, title)
    VALUES ('delete', old.id, old.body, old.title);
    INSERT INTO entries_fts(rowid, body, title) VALUES (new.id, new.body, new.title);
END;
"""

# A small built-in stopword list; short or numeric tokens are dropped too.
STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are aren't as at be
    because been before being below between both but by can cannot could
    couldn't did didn't do does doesn't doing don't down during each few for
    from further had hadn't has hasn't have haven't having he he'd he'll he's
    her here here's hers herself him himself his how how's i i'd i'll i'm i've
    if in into is isn't it it's its itself let's me more most mustn't my myself
    no nor not of off on once only or other ought our ours ourselves out over
    own same shan't she she'd she'll she's should shouldn't so some such than
    that that's the their theirs them themselves then there there's these they
    they'd they'll they're they've this those through to too under until up
    very was wasn't we we'd we'll we're we've were weren't what what's when
    when's where where's which while who who's whom why why's with won't would
    wouldn't you you'd you'll you're you've your yours yourself yourselves
    just really also got get getting like today yesterday tomorrow
    """.split()
)


class CommandError(Exception):
    """A user-facing error that is rendered as a JSON error envelope."""

    def __init__(self, code: str, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def resolve_db_path(cli_value: Optional[str] = None) -> Path:
    if cli_value:
        raw = cli_value
    elif os.environ.get("JOURNAL_DB"):
        raw = os.environ["JOURNAL_DB"]
    else:
        raw = os.path.join(DEFAULT_DB_DIR, DEFAULT_DB_NAME)
    return Path(os.path.expanduser(raw))


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


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------

def fts_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1 FROM entries_fts LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False


def ensure_fts(conn: sqlite3.Connection) -> bool:
    """Create the FTS index if the build supports it; return whether it is on."""
    if get_meta(conn, "fts_enabled") == "0":
        return False
    if fts_available(conn):
        set_meta(conn, "fts_enabled", "1")
        return True
    try:
        conn.executescript(FTS_SQL)
        conn.execute("INSERT INTO entries_fts(entries_fts) VALUES('rebuild')")
        set_meta(conn, "fts_enabled", "1")
        return True
    except sqlite3.OperationalError:
        set_meta(conn, "fts_enabled", "0")
        return False


def disable_fts(conn: sqlite3.Connection) -> None:
    try:
        conn.executescript(
            "DROP TRIGGER IF EXISTS entries_ai;"
            "DROP TRIGGER IF EXISTS entries_ad;"
            "DROP TRIGGER IF EXISTS entries_au;"
            "DROP TABLE IF EXISTS entries_fts;"
        )
    except sqlite3.OperationalError:
        pass
    set_meta(conn, "fts_enabled", "0")


def fts_enabled(conn: sqlite3.Connection) -> bool:
    return get_meta(conn, "fts_enabled") == "1" and fts_available(conn)


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


def setting_int(conn: sqlite3.Connection, key: str, default: int = 0) -> int:
    raw = effective_setting(conn, key)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)


def settings_snapshot(conn: sqlite3.Connection) -> Dict[str, str]:
    snapshot = dict(SETTING_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM meta"):
        snapshot[row["key"]] = row["value"]
    return snapshot


def effective_settings(conn: sqlite3.Connection) -> Dict[str, str]:
    return {key: effective_setting(conn, key) for key in SETTING_DEFAULTS}


# ---------------------------------------------------------------------------
# Dates, timezones, words
# ---------------------------------------------------------------------------

def validate_date(value: str, field: str = "date") -> str:
    text = (value or "").strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise CommandError("invalid_date", "invalid %s %r, expected YYYY-MM-DD" % (field, value))


def tzinfo_for(name: str) -> Any:
    name = (name or DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        if name.upper() in ("UTC", "GMT"):
            return None
        raise CommandError("invalid_input", "unknown timezone %r" % name)


def now_local(tz_name: str) -> datetime:
    zone = tzinfo_for(tz_name)
    if zone is None:
        return datetime.utcnow()
    return datetime.now(zone)


def resolve_today(conn: sqlite3.Connection, args: argparse.Namespace) -> date:
    tz_name = getattr(args, "tz", None) or effective_setting(conn, "tz") or DEFAULT_TZ
    return now_local(tz_name).date()


def today_str() -> str:
    return date.today().isoformat()


def resolve_week_start(conn: sqlite3.Connection) -> str:
    value = (effective_setting(conn, "week_start") or "mon").strip().lower()
    return value if value in WEEK_STARTS else "mon"


def week_bounds(day: date, week_start: str) -> Tuple[date, date]:
    start_index = 0 if (week_start or "mon") == "mon" else 6
    offset = (day.weekday() - start_index) % 7
    start = day - timedelta(days=offset)
    return start, start + timedelta(days=6)


def parse_iso_week(value: str) -> Tuple[date, date]:
    text = (value or "").strip().upper()
    match = re.match(r"^(\d{4})-W(\d{1,2})$", text)
    if not match:
        raise CommandError("invalid_date", "invalid --week %r, expected YYYY-Www" % value)
    year, week = int(match.group(1)), int(match.group(2))
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError:
        raise CommandError("invalid_date", "invalid --week %r, expected YYYY-Www" % value)
    return monday, monday + timedelta(days=6)


def word_count(text: str) -> int:
    return len((text or "").split())


def entry_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "entry_date": row["entry_date"],
        "title": row["title"],
        "body": row["body"],
        "word_count": int(row["word_count"]),
        "source": row["source"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def resolve_entry(conn: sqlite3.Connection, ident: Any) -> sqlite3.Row:
    if ident is None or not str(ident).strip():
        raise CommandError("not_found", "entry id is required")
    text = str(ident).strip()
    if not text.isdigit():
        raise CommandError("not_found", "no entry matches %r" % text)
    row = conn.execute("SELECT * FROM entries WHERE id = ?", (int(text),)).fetchone()
    if row is None:
        raise CommandError("not_found", "no entry with id %s" % text)
    return row


# ---------------------------------------------------------------------------
# Analysis helpers
# ---------------------------------------------------------------------------

def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9][a-z0-9'-]*", (text or "").lower())


def top_terms(pairs: Iterable[Tuple[Optional[str], str]], limit: int = TOP_TERM_LIMIT) -> List[Dict[str, Any]]:
    counts: Counter = Counter()
    for title, body in pairs:
        for token in tokenize((title or "") + " " + (body or "")):
            if len(token) < 2 or token in STOPWORDS:
                continue
            if not any(character.isalpha() for character in token):
                continue
            counts[token] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [{"term": term, "count": count} for term, count in ordered[:limit]]


def notable_lines(
    pairs: Iterable[Tuple[str, str]], limit: int = NOTABLE_LIMIT
) -> List[Dict[str, Any]]:
    sentences: List[Tuple[int, str, str]] = []
    for entry_date, body in pairs:
        for raw in re.split(r"(?<=[.!?])\s+", (body or "").replace("\n", " ")):
            text = raw.strip()
            if text:
                sentences.append((len(text), entry_date, text))
    sentences.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [{"date": entry_date, "text": text} for _length, entry_date, text in sentences[:limit]]


def day_run(active: Sequence[date], end: date) -> Tuple[int, int]:
    """Return (current run ending at ``end``, longest run) over active days."""
    ordered = sorted(set(active))
    longest = 0
    run = 0
    previous: Optional[date] = None
    for day in ordered:
        if previous is not None and (day - previous).days == 1:
            run += 1
        else:
            run = 1
        if run > longest:
            longest = run
        previous = day
    current = 0
    active_set = set(ordered)
    cursor = end
    while cursor in active_set:
        current += 1
        cursor -= timedelta(days=1)
    return current, longest


# ---------------------------------------------------------------------------
# Scheduling manage actions
# ---------------------------------------------------------------------------

SCHEDULE_ACTIONS = ("add", "enable", "disable", "remove", "list")


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
    installs, enables, disables, or removes anything itself. The artifact
    names the host action and the routes that can carry it out.
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
            routes.append(
                {"via": "cron_tool", "action": "remove", "params": {"job_id": resolved_job}}
            )
        elif action == "disable":
            routes.append(
                {
                    "via": "webui_automations",
                    "action": "disable",
                    "params": {"id": resolved_job},
                    "note": "requires the WebUI API token",
                }
            )
            routes.append(
                {
                    "via": "cron_tool",
                    "action": "remove",
                    "params": {"job_id": resolved_job},
                    "note": "blunt off: deletes the job; re-add to restore",
                }
            )
        else:
            routes.append(
                {
                    "via": "webui_automations",
                    "action": "enable",
                    "params": {"id": resolved_job},
                    "note": "requires the WebUI API token",
                }
            )
            routes.append(
                {
                    "via": "cron_tool",
                    "action": "add",
                    "note": "if the job was deleted, re-create it with --action add",
                }
            )
    elif family == "cli":
        support.update({"add": True, "list": True, "remove": True})
        via = "cli"
        cli = cli_name or "cron"
        if action == "list":
            routes.append({"via": "cli", "command": "%s cron ls" % cli})
        elif action == "remove":
            routes.append({"via": "cli", "command": "%s cron rm %s" % (cli, resolved_job)})
        else:
            routes.append(
                {
                    "via": "cli",
                    "command": "%s cron %s %s" % (cli, action, resolved_job),
                    "note": "confirm the exact subcommand in your host CLI",
                }
            )
    elif family == "host":
        support.update({key: True for key in SCHEDULE_ACTIONS})
        via = "host"
        routes.append({"via": "host", "action": action, "job": resolved_job})
    else:
        support.update({key: True for key in SCHEDULE_ACTIONS})
        via = "os"
        if target == "crontab":
            routes.append(
                {
                    "via": "crontab",
                    "action": action,
                    "note": "edit with crontab -e; comment to disable, uncomment to enable, delete to remove",
                }
            )
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

def add_action_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--action",
        choices=list(SCHEDULE_ACTIONS),
        default="add",
        help="emit an artifact to add, enable, disable, remove, or list the job",
    )
    parser.add_argument("--job", help="job name or id for enable/disable/remove/list")


def common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--db", metavar="PATH", help="SQLite database path")
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


def run_script(domain: str, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args()
    fmt = getattr(args, "format", "json")
    quiet = getattr(args, "quiet", False)
    verb = getattr(args, "verb", domain)
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help(sys.stderr)
        sys.exit(2)
    try:
        conn = connect(resolve_db_path(getattr(args, "db", None)))
        try:
            migrate(conn)
            data = handler(conn, args)
            conn.commit()
        finally:
            conn.close()
        emit("%s.%s" % (domain, verb), data, fmt, quiet)
    except CommandError as exc:
        fail(exc.code, exc.message, exc.exit_code)
    except sqlite3.Error as exc:
        fail("db_error", str(exc))
    except BrokenPipeError:
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # pragma: no cover - defensive
        fail("internal_error", "%s: %s" % (type(exc).__name__, exc))


def add_subparser(subparsers: Any, name: str, help_text: str, parents: Sequence[Any]) -> Any:
    parser = subparsers.add_parser(name, help=help_text, description=help_text, parents=list(parents))
    parser.set_defaults(verb=name)
    return parser
