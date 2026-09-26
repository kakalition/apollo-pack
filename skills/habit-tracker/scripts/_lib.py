#!/usr/bin/env python3
"""Shared helpers for the habit-tracker skill scripts.

This module is NOT an entry point. Domain scripts import it directly
(``import _lib``) because Python places the script's own directory on
``sys.path[0]``.

Pure standard library, compatible with Python 3.9+. No network access. All
cadence, streak, and adherence arithmetic lives here so that the prose around
the skill never computes a number itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_DB_DIR = "~/.local/share/habit-tracker"
DEFAULT_DB_NAME = "habits.db"
DEFAULT_TZ = "UTC"
SCHEMA_VERSION = 1

CADENCE_KINDS = ("daily", "weekly", "interval")
WEEK_STARTS = ("mon", "sun")
VIEWS = ("today", "streaks")
STATUSES = ("done", "skip", "fail")

SETTING_DEFAULTS: Dict[str, str] = {
    "tz": DEFAULT_TZ,
    "week_start": "mon",
    "default_view": "today",
}

ENV_OVERRIDES: Dict[str, str] = {
    "tz": "HABIT_TRACKER_TZ",
    "week_start": "HABIT_TRACKER_WEEK_START",
    "default_view": "HABIT_TRACKER_DEFAULT_VIEW",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS habits (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    cadence_kind  TEXT NOT NULL CHECK (cadence_kind IN ('daily','weekly','interval')),
    cadence_count INTEGER NOT NULL DEFAULT 1 CHECK (cadence_count >= 1),
    start_date    TEXT NOT NULL,
    end_date      TEXT,
    notes         TEXT,
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS checkins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    habit_id   INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    status     TEXT NOT NULL CHECK (status IN ('done','skip','fail')),
    note       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (habit_id, date)
);

CREATE INDEX IF NOT EXISTS idx_checkins_habit ON checkins(habit_id);
CREATE INDEX IF NOT EXISTS idx_checkins_date ON checkins(date);
"""


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
    elif os.environ.get("HABIT_TRACKER_DB"):
        raw = os.environ["HABIT_TRACKER_DB"]
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
# Dates, timezones, weeks
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


def resolve_week_start(conn: sqlite3.Connection) -> str:
    value = (effective_setting(conn, "week_start") or "mon").strip().lower()
    return value if value in WEEK_STARTS else "mon"


def today_str() -> str:
    return date.today().isoformat()


def week_bounds(day: date, week_start: str) -> Tuple[date, date]:
    start_index = 0 if (week_start or "mon") == "mon" else 6
    offset = (day.weekday() - start_index) % 7
    start = day - timedelta(days=offset)
    return start, start + timedelta(days=6)


# ---------------------------------------------------------------------------
# Habit lookups and serialization
# ---------------------------------------------------------------------------

def habit_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "cadence": row["cadence_kind"],
        "cadence_count": int(row["cadence_count"]),
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "notes": row["notes"],
        "active": bool(row["active"]),
        "created_at": row["created_at"],
    }


def resolve_habit(
    conn: sqlite3.Connection,
    ident: Any,
    field: str = "habit",
    allow_inactive: bool = False,
) -> sqlite3.Row:
    if ident is None or not str(ident).strip():
        raise CommandError("not_found", "%s is required" % field)
    text = str(ident).strip()
    row = None
    if text.isdigit():
        row = conn.execute("SELECT * FROM habits WHERE id = ?", (int(text),)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM habits WHERE name = ? COLLATE NOCASE", (text,)).fetchone()
    if row is None:
        raise CommandError("not_found", "no %s matches %r" % (field, text))
    if not row["active"] and not allow_inactive:
        raise CommandError("not_found", "%s %r is paused or archived" % (field, row["name"]))
    return row


def checkin_map(conn: sqlite3.Connection, habit_id: int) -> Dict[str, str]:
    return {
        row["date"]: row["status"]
        for row in conn.execute(
            "SELECT date, status FROM checkins WHERE habit_id = ? ORDER BY date", (habit_id,)
        )
    }


# ---------------------------------------------------------------------------
# Cadence engine
# ---------------------------------------------------------------------------

def _empty_counts() -> Dict[str, int]:
    return {"done": 0, "skip": 0, "fail": 0, "miss": 0}


def adherence_pct(counts: Dict[str, int]) -> float:
    denominator = int(counts["done"]) + int(counts["fail"]) + int(counts["miss"])
    if denominator <= 0:
        return 0.0
    return round(int(counts["done"]) / float(denominator) * 100.0, 1)


def _bounds(habit: sqlite3.Row, as_of: date) -> Tuple[date, Optional[date], date]:
    start = date.fromisoformat(habit["start_date"])
    end = date.fromisoformat(habit["end_date"]) if habit["end_date"] else None
    bound = as_of if end is None or as_of < end else end
    return start, end, bound


def daily_progress(habit: sqlite3.Row, checkins: Dict[str, str], as_of: date) -> Dict[str, Any]:
    start, _end, bound = _bounds(habit, as_of)
    counts = _empty_counts()
    pending = False
    days: List[date] = []
    if bound >= start:
        current = start
        guard = 0
        while current <= bound:
            days.append(current)
            current += timedelta(days=1)
            guard += 1
            if guard > 20000:
                raise CommandError("too_many_days", "habit %r spans too many days" % habit["name"])
    for day in days:
        status = checkins.get(day.isoformat())
        if status == "done":
            counts["done"] += 1
        elif status == "skip":
            counts["skip"] += 1
        elif status == "fail":
            counts["fail"] += 1
        elif day == as_of:
            pending = True
        else:
            counts["miss"] += 1

    current_streak = 0
    for day in reversed(days):
        status = checkins.get(day.isoformat())
        if status == "done":
            current_streak += 1
        elif status == "skip":
            continue
        elif status == "fail":
            break
        elif day == as_of:
            continue
        else:
            break

    longest = 0
    run = 0
    for day in days:
        status = checkins.get(day.isoformat())
        if status == "done":
            run += 1
            if run > longest:
                longest = run
        elif status == "skip":
            continue
        elif status == "fail":
            run = 0
        elif day == as_of:
            continue
        else:
            run = 0
    return {
        "counts": counts,
        "current_streak": current_streak,
        "longest_streak": longest,
        "pending": pending,
        "unit": "day",
    }


def _week_state(
    week_start: date,
    week_end: date,
    habit_start: date,
    bound: date,
    as_of: date,
    quota: int,
    checkins: Dict[str, str],
) -> Dict[str, Any]:
    done = 0
    skipped = False
    failed = False
    day = week_start
    while day <= week_end:
        if habit_start <= day <= bound:
            status = checkins.get(day.isoformat())
            if status == "done":
                done += 1
            elif status == "skip":
                skipped = True
            elif status == "fail":
                failed = True
        day += timedelta(days=1)
    complete = week_end <= as_of
    satisfied = done >= quota
    excused = (not satisfied) and skipped
    pending = (not satisfied) and (not skipped) and (not complete)
    missed = (not satisfied) and (not skipped) and complete
    return {
        "start": week_start.isoformat(),
        "end": week_end.isoformat(),
        "done": done,
        "quota": quota,
        "failed": failed,
        "skipped": skipped,
        "satisfied": satisfied,
        "excused": excused,
        "pending": pending,
        "missed": missed,
    }


def weekly_progress(
    habit: sqlite3.Row, checkins: Dict[str, str], as_of: date, week_start_name: str
) -> Dict[str, Any]:
    start, _end, bound = _bounds(habit, as_of)
    quota = max(1, int(habit["cadence_count"]))
    counts = _empty_counts()
    current_streak = 0
    longest = 0
    pending = False
    current_week: Optional[Dict[str, Any]] = None
    if bound >= start:
        week_start = week_bounds(start, week_start_name)[0]
        guard = 0
        while week_start <= bound:
            week_end = week_start + timedelta(days=6)
            state = _week_state(week_start, week_end, start, bound, as_of, quota, checkins)
            if state["satisfied"]:
                counts["done"] += 1
                current_streak += 1
                if current_streak > longest:
                    longest = current_streak
            elif state["excused"]:
                counts["skip"] += 1
            elif state["pending"]:
                pending = True
            else:
                counts["miss"] += 1
                current_streak = 0
            if week_start <= as_of <= week_end:
                current_week = state
            week_start = week_end + timedelta(days=1)
            guard += 1
            if guard > 5000:
                raise CommandError("too_many_weeks", "habit %r spans too many weeks" % habit["name"])
    return {
        "counts": counts,
        "current_streak": current_streak,
        "longest_streak": longest,
        "pending": pending,
        "unit": "week",
        "current_week": current_week,
    }


def interval_progress(
    habit: sqlite3.Row, checkins: Dict[str, str], as_of: date
) -> Dict[str, Any]:
    start, _end, bound = _bounds(habit, as_of)
    step = max(1, int(habit["cadence_count"]))
    counts = _empty_counts()
    current_streak = 0
    longest = 0
    pending = False
    due = start
    next_due = start
    guard = 0
    while due <= bound:
        guard += 1
        if guard > 20000:
            raise CommandError(
                "too_many_occurrences",
                "habit %r produces too many occurrences; raise the interval" % habit["name"],
            )
        window_end = due + timedelta(days=step)
        found: Optional[Tuple[date, str]] = None
        day = due
        while day < window_end and day <= bound:
            status = checkins.get(day.isoformat())
            if status is not None:
                found = (day, status)
                break
            day += timedelta(days=1)
        if found is None:
            if due < as_of:
                counts["miss"] += 1
                current_streak = 0
            else:
                pending = True
            next_due = due + timedelta(days=step)
        else:
            found_day, status = found
            if status == "done":
                counts["done"] += 1
                current_streak += 1
                if current_streak > longest:
                    longest = current_streak
                next_due = found_day + timedelta(days=step)
            elif status == "skip":
                counts["skip"] += 1
                next_due = due + timedelta(days=step)
            else:
                counts["fail"] += 1
                current_streak = 0
                next_due = due + timedelta(days=step)
        due = next_due
    return {
        "counts": counts,
        "current_streak": current_streak,
        "longest_streak": longest,
        "pending": pending,
        "unit": "instance",
        "next_due": next_due.isoformat(),
    }


def habit_stats(
    conn: sqlite3.Connection,
    habit: sqlite3.Row,
    as_of: date,
    week_start_name: str,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "id": habit["id"],
        "habit": habit["name"],
        "cadence": habit["cadence_kind"],
        "cadence_count": int(habit["cadence_count"]),
        "as_of": as_of.isoformat(),
        "active": bool(habit["active"]),
    }
    if not habit["active"]:
        base.update(
            {
                "inactive": True,
                "counts": _empty_counts(),
                "adherence_pct": 0.0,
                "current_streak": 0,
                "longest_streak": 0,
                "pending": False,
                "unit": habit["cadence_kind"],
                "last_done": None,
            }
        )
        return base
    checkins = checkin_map(conn, habit["id"])
    kind = habit["cadence_kind"]
    if kind == "daily":
        progress = daily_progress(habit, checkins, as_of)
    elif kind == "weekly":
        progress = weekly_progress(habit, checkins, as_of, week_start_name)
    else:
        progress = interval_progress(habit, checkins, as_of)
    done_dates = sorted(
        day for day, status in checkins.items() if status == "done" and day <= as_of.isoformat()
    )
    progress["last_done"] = done_dates[-1] if done_dates else None
    progress["adherence_pct"] = adherence_pct(progress["counts"])
    base.update(progress)
    return base


def adherence_for_range(
    habit: sqlite3.Row,
    checkins: Dict[str, str],
    from_date: date,
    to_date: date,
    as_of: date,
    week_start_name: str,
) -> Dict[str, int]:
    start, _end, bound = _bounds(habit, to_date)
    counts = _empty_counts()
    kind = habit["cadence_kind"]
    if kind == "daily":
        low = max(start, from_date)
        high = min(bound, to_date)
        day = low
        while day <= high:
            status = checkins.get(day.isoformat())
            if status in ("done", "skip", "fail"):
                counts[status] += 1
            elif day != as_of:
                counts["miss"] += 1
            day += timedelta(days=1)
    elif kind == "weekly":
        quota = max(1, int(habit["cadence_count"]))
        high = min(bound, to_date)
        if high >= start:
            week_start = week_bounds(max(start, from_date), week_start_name)[0]
            while week_start <= high:
                week_end = week_start + timedelta(days=6)
                state = _week_state(week_start, week_end, start, high, to_date, quota, checkins)
                if state["satisfied"]:
                    counts["done"] += 1
                elif state["excused"]:
                    counts["skip"] += 1
                elif not state["pending"]:
                    counts["miss"] += 1
                week_start = week_end + timedelta(days=1)
    else:
        step = max(1, int(habit["cadence_count"]))
        high = min(bound, to_date)
        due = start
        guard = 0
        while due <= high:
            guard += 1
            if guard > 20000:
                break
            window_end = due + timedelta(days=step)
            found: Optional[Tuple[date, str]] = None
            day = due
            while day < window_end and day <= high:
                status = checkins.get(day.isoformat())
                if status is not None:
                    found = (day, status)
                    break
                day += timedelta(days=1)
            if due >= from_date:
                if found is None:
                    if due != as_of:
                        counts["miss"] += 1
                else:
                    counts[found[1]] += 1
            due = (found[0] + timedelta(days=step)) if (found and found[1] == "done") else (
                due + timedelta(days=step)
            )
    return counts


def habit_due(
    conn: sqlite3.Connection,
    habit: sqlite3.Row,
    as_of: date,
    week_start_name: str,
) -> Optional[Dict[str, Any]]:
    if not habit["active"]:
        return None
    start = date.fromisoformat(habit["start_date"])
    end = date.fromisoformat(habit["end_date"]) if habit["end_date"] else None
    if as_of < start or (end is not None and as_of > end):
        return None
    checkins = checkin_map(conn, habit["id"])
    kind = habit["cadence_kind"]
    base: Dict[str, Any] = {
        "id": habit["id"],
        "name": habit["name"],
        "cadence": kind,
        "cadence_count": int(habit["cadence_count"]),
        "status": checkins.get(as_of.isoformat()),
        "as_of": as_of.isoformat(),
    }
    if kind == "daily":
        base["due"] = base["status"] is None
        base["expected"] = True
    elif kind == "weekly":
        week_start, week_end = week_bounds(as_of, week_start_name)
        quota = max(1, int(habit["cadence_count"]))
        state = _week_state(week_start, week_end, start, as_of, as_of, quota, checkins)
        base["due"] = (not state["satisfied"]) and (not state["excused"])
        base["week"] = state
        base["remaining"] = max(0, quota - state["done"])
        base["excused"] = state["excused"]
        base["satisfied"] = state["satisfied"]
    else:
        progress = interval_progress(habit, checkins, as_of)
        next_due = date.fromisoformat(progress["next_due"])
        base["due"] = next_due <= as_of
        base["next_due"] = progress["next_due"]
        base["overdue"] = next_due < as_of
    return base


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
    parser = subparsers.add_parser(name, help=help_text, description=help_text, parents=list(parents))
    parser.set_defaults(verb=name)
    return parser
