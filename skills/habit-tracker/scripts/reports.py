#!/usr/bin/env python3
"""Read-only habit reports plus a scheduling-artifact emitter.

Everything here is read-only. All streak, adherence, and due arithmetic is
computed by ``_lib`` so the surrounding prose never computes a number itself.
``schedule-hint`` only emits an artifact; it installs nothing.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402

SCHEDULE_TARGETS = (
    "generic",
    "nanobot",
    "hermes",
    "claude",
    "codex",
    "kilo",
    "crontab",
    "systemd",
    "launchd",
)
OS_TARGETS = ("crontab", "systemd", "launchd")
ABS_DEFAULT_TARGETS = OS_TARGETS + ("nanobot", "hermes")


# ---------------------------------------------------------------------------
# Read-only verbs
# ---------------------------------------------------------------------------

def cmd_today(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    as_of = (
        date.fromisoformat(_lib.validate_date(args.as_of, "--as-of"))
        if args.as_of
        else _lib.resolve_today(conn, args)
    )
    week_start = _lib.resolve_week_start(conn)
    habits = conn.execute("SELECT * FROM habits WHERE active = 1 ORDER BY name COLLATE NOCASE").fetchall()
    rows: List[Dict[str, Any]] = []
    for habit in habits:
        row = _lib.habit_due(conn, habit, as_of, week_start)
        if row is not None:
            rows.append(row)
    return {
        "read_only": True,
        "as_of": as_of.isoformat(),
        "week_start": week_start,
        "due_count": sum(1 for row in rows if row["due"]),
        "habits": rows,
    }


def cmd_due(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    as_of = (
        date.fromisoformat(_lib.validate_date(args.as_of, "--as-of"))
        if args.as_of
        else _lib.resolve_today(conn, args)
    )
    within = 7 if args.within is None else int(args.within)
    if within < 0:
        raise _lib.CommandError("invalid_input", "--within must be zero or greater")
    horizon = as_of + timedelta(days=within)
    week_start = _lib.resolve_week_start(conn)
    habits = conn.execute("SELECT * FROM habits WHERE active = 1 ORDER BY name COLLATE NOCASE").fetchall()
    rows: List[Dict[str, Any]] = []
    for habit in habits:
        row = _lib.habit_due(conn, habit, as_of, week_start)
        if row is None:
            continue
        if row["due"]:
            rows.append(row)
            continue
        if row["cadence"] == "interval" and row.get("next_due"):
            next_due = date.fromisoformat(row["next_due"])
            if next_due <= horizon:
                row["due"] = False
                rows.append(row)
    return {
        "read_only": True,
        "as_of": as_of.isoformat(),
        "within_days": within,
        "horizon": horizon.isoformat(),
        "week_start": week_start,
        "count": len(rows),
        "habits": rows,
    }


def cmd_streaks(conn: sqlite3.Connection, args: argparse.Namespace) -> List[Dict[str, Any]]:
    as_of = (
        date.fromisoformat(_lib.validate_date(args.as_of, "--as-of"))
        if args.as_of
        else _lib.resolve_today(conn, args)
    )
    week_start = _lib.resolve_week_start(conn)
    if args.habit:
        habits = [_lib.resolve_habit(conn, args.habit, allow_inactive=True)]
    else:
        habits = conn.execute("SELECT * FROM habits ORDER BY name COLLATE NOCASE").fetchall()
    return [_lib.habit_stats(conn, habit, as_of, week_start) for habit in habits]


def cmd_adherence(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    from_date = date.fromisoformat(_lib.validate_date(args.from_date, "--from"))
    to_date = date.fromisoformat(_lib.validate_date(args.to_date, "--to"))
    if to_date < from_date:
        raise _lib.CommandError("invalid_input", "--to must not be before --from")
    as_of = _lib.resolve_today(conn, args)
    week_start = _lib.resolve_week_start(conn)
    if args.habit:
        habits = [_lib.resolve_habit(conn, args.habit, allow_inactive=True)]
    else:
        habits = conn.execute("SELECT * FROM habits ORDER BY name COLLATE NOCASE").fetchall()
    rows: List[Dict[str, Any]] = []
    for habit in habits:
        counts = _lib.adherence_for_range(
            habit, _lib.checkin_map(conn, habit["id"]), from_date, to_date, as_of, week_start
        )
        rows.append(
            {
                "habit": habit["name"],
                "id": habit["id"],
                "cadence": habit["cadence_kind"],
                "unit": habit["cadence_kind"],
                "counts": counts,
                "adherence_pct": _lib.adherence_pct(counts),
            }
        )
    return {
        "read_only": True,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "habits": rows,
    }


def cmd_history(conn: sqlite3.Connection, args: argparse.Namespace) -> List[Dict[str, Any]]:
    habit = _lib.resolve_habit(conn, args.habit, allow_inactive=True)
    sql = "SELECT * FROM checkins WHERE habit_id = ?"
    params: List[Any] = [habit["id"]]
    if args.from_date:
        sql += " AND date >= ?"
        params.append(_lib.validate_date(args.from_date, "--from"))
    if args.to_date:
        sql += " AND date <= ?"
        params.append(_lib.validate_date(args.to_date, "--to"))
    limit = 50 if args.limit is None else max(0, int(args.limit))
    sql += " ORDER BY date DESC, id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        {
            "id": row["id"],
            "habit": habit["name"],
            "date": row["date"],
            "status": row["status"],
            "note": row["note"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def cmd_stats(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    habits_total = conn.execute("SELECT COUNT(*) AS n FROM habits").fetchone()["n"]
    habits_active = conn.execute("SELECT COUNT(*) AS n FROM habits WHERE active = 1").fetchone()["n"]
    by_status = {"done": 0, "skip": 0, "fail": 0}
    for row in conn.execute("SELECT status, COUNT(*) AS n FROM checkins GROUP BY status"):
        by_status[row["status"]] = row["n"]
    span = conn.execute(
        "SELECT MIN(date) AS first, MAX(date) AS last FROM checkins"
    ).fetchone()
    return {
        "habits": habits_total,
        "active_habits": habits_active,
        "checkins": sum(by_status.values()),
        "by_status": by_status,
        "first_checkin": span["first"],
        "last_checkin": span["last"],
    }


# ---------------------------------------------------------------------------
# Scheduling artifact
# ---------------------------------------------------------------------------

def _validate_hhmm(value: str) -> Any:
    text = (value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise _lib.CommandError("invalid_input", "--at-time must look like HH:MM")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise _lib.CommandError("invalid_input", "--at-time must look like HH:MM")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise _lib.CommandError("invalid_input", "--at-time must be a valid 24-hour time")
    return hour, minute


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _script_path(path_mode: str) -> str:
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if path_mode == "abs":
        return os.path.join(skill_dir, "scripts", "reports.py")
    if path_mode == "relative":
        return os.path.join("scripts", "reports.py")
    return "{skillDir}/scripts/reports.py"


def _base_command(python: str, script: str, db_path: str) -> str:
    return python + " " + script + ' due --as-of "$(date +%F)" --db ' + db_path


def cmd_schedule_hint(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    target = args.target
    path_mode = args.path_mode or ("abs" if target in ABS_DEFAULT_TARGETS else "skill")
    if path_mode not in ("abs", "relative", "skill"):
        raise _lib.CommandError("invalid_input", "--path-mode must be abs, relative, or skill")
    tz = args.tz or _lib.effective_setting(conn, "tz") or os.environ.get("TZ") or _lib.DEFAULT_TZ
    name = args.name or "habit-tracker-daily"
    script = _script_path(path_mode)
    db_path = str(_lib.resolve_db_path(args.db))
    today = _lib.resolve_today(conn, args).isoformat()
    action = getattr(args, "action", "add") or "add"
    if action != "add":
        return _lib.manage_artifact(
            action,
            getattr(args, "job", None),
            target=target,
            family=(
                "chat"
                if target == "nanobot"
                else "cli"
                if target == "hermes"
                else "host"
                if target in ("generic", "claude", "codex", "kilo")
                else "os"
            ),
            cli_name="hermes",
            path_mode=path_mode,
            tz=tz,
            name=name,
            script=script,
            store=db_path,
            generated_at=today,
            skill_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            prog="habit-tracker",
            service="habit-tracker-due.service",
            timer="habit-tracker-due.timer",
            plist="com.habit-tracker.due.plist",
            add_command=_base_command("python3", script, db_path),
            add_note="The emitted command is a read-only report, so re-adding is harmless.",
        )
    hour, minute = _validate_hhmm(args.at_time or "08:00")
    cron_expr = "%d %d * * *" % (minute, hour)
    python = "/usr/bin/env python3" if target in OS_TARGETS else "python3"
    read_cmd = _base_command(python, script, db_path)
    quiet_cmd = read_cmd + " --quiet"

    base: Dict[str, Any] = {
        "target": target,
        "path_mode": path_mode,
        "generated_at": today,
        "action": "add",
        "skill_dir": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "script": script,
        "store": db_path,
        "name": name,
        "db": db_path,
        "cron_expr": cron_expr,
        "tz": tz,
        "commands": [
            {
                "step": "report",
                "description": "List habits due today (read-only)",
                "command": read_cmd,
            }
        ],
        "installs_nothing": True,
        "read_only": True,
    }

    if target in ("generic", "claude", "codex", "kilo"):
        base["instructions"] = (
            "Register a recurring task with your host's scheduling mechanism (a cron "
            "tool, reminders, a task runner, or an OS scheduler such as the crontab, "
            "systemd, or launchd targets). On each trigger, run the report command and "
            "surface the habits that are due. Stay quiet when nothing is due. The "
            "command is read-only and the script owns all cadence arithmetic."
        )
        base["notes"] = [
            "This target installs nothing; the agent or user registers it.",
            "Due dates and streaks are resolved by reports.py, not by the scheduler.",
            "Re-triggering is safe: the report never writes.",
        ]
        if target in ("claude", "codex", "kilo"):
            base["fallback"] = (
                "If this host has no native scheduler, use the crontab, launchd, or "
                "systemd target and register the emitted artifact."
            )
        return base

    if target == "nanobot":
        message = (
            "$habit-tracker Check which habits are due today and report them. Run: "
            + read_cmd
            + " ; then tell me what is due. Stay silent if nothing is due."
        )
        base["name"] = name
        base["message"] = message
        base["cron_tool"] = {
            "action": "add",
            "name": name,
            "message": message,
            "cron_expr": cron_expr,
            "tz": tz,
        }
        base["instructions"] = (
            "Create this job with your host's built-in cron tool using the cron_tool "
            "fields above. Create it from a live chat session. Keep cron_expr and tz "
            "together; the tool rejects tz without cron_expr."
        )
        base["notes"] = [
            "This is the only target that uses the $habit-tracker explicit invocation.",
            "The report command is read-only, so duplicate fires are harmless.",
            "Remove the job through the cron tool; that does not touch the habits.",
        ]
        return base

    if target == "hermes":
        hermes_script = _script_path("abs") + ' due --as-of "$(date +%F)" --format json'
        message = "$habit-tracker Check which habits are due today and report them."
        base["name"] = name
        base["message"] = message
        base["skills"] = ["habit-tracker"]
        base["script"] = hermes_script
        base["cron_tool"] = {
            "action": "add",
            "tool": "cronjob",
            "name": name,
            "message": message,
            "cron_expr": cron_expr,
            "tz": tz,
            "skills": ["habit-tracker"],
            "script": hermes_script,
        }
        base["hermes_cli"] = (
            "hermes cron add --name %s --schedule '%s' --skills habit-tracker" % (name, cron_expr)
        )
        base["instructions"] = (
            "Create the job with the cronjob tool (or the equivalent hermes cron add "
            "command). Hermes injects the pre-run script's stdout into the prompt. "
            "Register one job if the host accepts the cron expression."
        )
        base["notes"] = [
            "skills:[habit-tracker] makes the skill available to the cron session.",
            "The script is read-only, so duplicate fires are harmless.",
        ]
        return base

    if target == "crontab":
        cron_cmd = (
            python
            + " "
            + script
            + ' due --as-of "$(date +\\%F)" --db '
            + db_path
            + " --quiet"
        )
        base["install"] = {"type": "crontab", "lines": ["%d %d * * * %s" % (minute, hour, cron_cmd)]}
        base["instructions"] = (
            "Append this line to your crontab (crontab -e). It runs the script directly "
            "and produces no chat notification. Remove it with crontab -e; that does not "
            "change the habits."
        )
        base["notes"] = [
            "The line is read-only, so catching up never double-logs anything.",
            "--quiet keeps an empty day from generating cron email.",
        ]
        return base

    if target == "systemd":
        service_cmd = (
            "/usr/bin/env python3 "
            + script
            + ' due --as-of "$(date +%%F)" --db '
            + db_path
            + " --quiet"
        )
        service = (
            "[Unit]\n"
            "Description=Check habit-tracker habits due today\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/bin/sh -c '%s'\n" % service_cmd
        )
        timer = (
            "[Unit]\n"
            "Description=Daily habit-tracker due check\n\n"
            "[Timer]\n"
            "OnCalendar=*-*-* %02d:%02d:00\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n" % (hour, minute)
        )
        base["install"] = {
            "type": "systemd",
            "files": {
                "habit-tracker-due.service": service,
                "habit-tracker-due.timer": timer,
            },
            "commands": [
                "systemctl --user daemon-reload",
                "systemctl --user enable --now habit-tracker-due.timer",
            ],
        }
        base["instructions"] = (
            "Write both files to ~/.config/systemd/user/, then run the install commands. "
            "This produces no chat notification; remove with systemctl --user disable --now "
            "habit-tracker-due.timer."
        )
        base["notes"] = [
            "Persistent=true catches up runs missed while the machine was off.",
            "The service is read-only and writes nothing to chat.",
        ]
        return base

    run_cmd = (
        "/usr/bin/env python3 "
        + script
        + ' due --as-of "$(date +%F)" --db '
        + db_path
        + " --quiet"
    )
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "  <key>Label</key>\n"
        "  <string>com.habit-tracker.due</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        "    <string>/bin/sh</string>\n"
        "    <string>-c</string>\n"
        "    <string>%s</string>\n"
        "  </array>\n"
        "  <key>StartCalendarInterval</key>\n"
        "  <dict>\n"
        "    <key>Hour</key>\n"
        "    <integer>%d</integer>\n"
        "    <key>Minute</key>\n"
        "    <integer>%d</integer>\n"
        "  </dict>\n"
        "</dict>\n"
        "</plist>\n" % (_xml_escape(run_cmd), hour, minute)
    )
    base["install"] = {
        "type": "launchd",
        "files": {"com.habit-tracker.due.plist": plist},
        "commands": [
            "cp com.habit-tracker.due.plist ~/Library/LaunchAgents/",
            "launchctl load ~/Library/LaunchAgents/com.habit-tracker.due.plist",
        ],
    }
    base["instructions"] = (
        "Write the plist to ~/Library/LaunchAgents/ and load it with launchctl. This "
        "produces no chat notification; unload with launchctl unload."
    )
    base["notes"] = [
        "launchd runs missed jobs on wake when the machine was asleep.",
        "The job is read-only and writes nothing to chat.",
    ]
    return base


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="reports.py", description="Habit reports and scheduling.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    today = subparsers.add_parser(
        "today",
        help="due and status per active habit",
        description="Show each active habit's status and whether it is due (read-only).",
        parents=[common],
    )
    today.add_argument("--as-of", help="reference date YYYY-MM-DD (default today)")
    today.set_defaults(func=cmd_today, verb="today")

    due = subparsers.add_parser(
        "due",
        help="due habits plus a forward window",
        description="List habits that are due, plus interval habits due within a window (read-only).",
        parents=[common],
    )
    due.add_argument("--as-of", help="reference date YYYY-MM-DD (default today)")
    due.add_argument("--within", type=int, default=7, help="days ahead for interval habits")
    due.set_defaults(func=cmd_due, verb="due")

    streaks = subparsers.add_parser(
        "streaks",
        help="current and longest streaks",
        description="Show current streak, longest streak, last done, and adherence per habit.",
        parents=[common],
    )
    streaks.add_argument("--habit", help="limit to one habit id or name")
    streaks.add_argument("--as-of", help="reference date YYYY-MM-DD (default today)")
    streaks.set_defaults(func=cmd_streaks, verb="streaks")

    adherence = subparsers.add_parser(
        "adherence",
        help="adherence over a date range",
        description="Compute done/fail/miss counts and adherence percentage over a range.",
        parents=[common],
    )
    adherence.add_argument("--from", dest="from_date", required=True)
    adherence.add_argument("--to", dest="to_date", required=True)
    adherence.add_argument("--habit", help="limit to one habit id or name")
    adherence.set_defaults(func=cmd_adherence, verb="adherence")

    history = subparsers.add_parser(
        "history",
        help="check-in history for a habit",
        description="Show a habit's check-ins, newest first.",
        parents=[common],
    )
    history.add_argument("--habit", required=True)
    history.add_argument("--from", dest="from_date")
    history.add_argument("--to", dest="to_date")
    history.add_argument("--limit", type=int, help="maximum rows (default 50)")
    history.set_defaults(func=cmd_history, verb="history")

    stats = subparsers.add_parser(
        "stats",
        help="database totals",
        description="Show habit and check-in totals.",
        parents=[common],
    )
    stats.set_defaults(func=cmd_stats, verb="stats")

    hint = subparsers.add_parser(
        "schedule-hint",
        help="emit a scheduling artifact (never installs)",
        description="Emit an installable scheduling artifact for a chosen host or OS scheduler.",
        parents=[common],
    )
    hint.add_argument("--target", choices=list(SCHEDULE_TARGETS), default="generic")
    hint.add_argument("--path-mode", choices=("abs", "relative", "skill"))
    hint.add_argument("--at-time", default="08:00", help="daily time HH:MM (default 08:00)")
    hint.add_argument("--name", help="job name for agent targets")
    _lib.add_action_flags(hint)
    hint.set_defaults(func=cmd_schedule_hint, verb="schedule-hint")

    return parser


def main() -> None:
    _lib.run_script("reports", build_parser())


if __name__ == "__main__":
    main()
