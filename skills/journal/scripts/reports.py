#!/usr/bin/env python3
"""Read-only journal reports plus a scheduling-artifact emitter.

The weekly verb returns a brief (ranges, counts, notable lines, top terms, and
a prompt) for the host model to turn into prose. It never writes, never calls a
model, and never touches the network. ``schedule-hint`` only emits an artifact;
it installs nothing.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

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


def _range(conn: sqlite3.Connection, args: argparse.Namespace) -> Tuple[date, date, Optional[str]]:
    if getattr(args, "week", None):
        start, end = _lib.parse_iso_week(args.week)
        return start, end, args.week.strip().upper()
    if args.from_date or args.to_date:
        if not (args.from_date and args.to_date):
            raise _lib.CommandError("invalid_input", "provide both --from and --to")
        start = date.fromisoformat(_lib.validate_date(args.from_date, "--from"))
        end = date.fromisoformat(_lib.validate_date(args.to_date, "--to"))
        if end < start:
            raise _lib.CommandError("invalid_input", "--to must not be before --from")
        return start, end, None
    today = _lib.resolve_today(conn, args)
    start, end = _lib.week_bounds(today, _lib.resolve_week_start(conn))
    return start, end, None


def _rows_in_range(conn: sqlite3.Connection, start: date, end: date) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM entries WHERE entry_date >= ? AND entry_date <= ? "
        "ORDER BY entry_date, id",
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def _week_label(start: date) -> str:
    iso = start.isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])


def cmd_week(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    start, end, label = _range(conn, args)
    rows = _rows_in_range(conn, start, end)
    as_of = _lib.resolve_today(conn, args)

    active_dates = {row["entry_date"] for row in rows}
    days_missing: List[str] = []
    cursor = start
    limit_end = min(end, as_of)
    while cursor <= limit_end:
        if cursor.isoformat() not in active_dates:
            days_missing.append(cursor.isoformat())
        cursor += timedelta(days=1)

    by_day: List[Dict[str, Any]] = []
    for entry_date in sorted(active_dates):
        day_rows = [row for row in rows if row["entry_date"] == entry_date]
        by_day.append(
            {
                "date": entry_date,
                "entries": len(day_rows),
                "words": sum(int(row["word_count"]) for row in day_rows),
            }
        )

    total_words = sum(int(row["word_count"]) for row in rows)
    body_pairs = [(row["entry_date"], row["body"]) for row in rows]
    term_pairs = [(row["title"], row["body"]) for row in rows]
    return {
        "range": {
            "week": label or _week_label(start),
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
        "entry_count": len(rows),
        "days_with_entries": len(active_dates),
        "days_missing": days_missing,
        "total_words": total_words,
        "by_day": by_day,
        "notable_lines": _lib.notable_lines(body_pairs),
        "top_terms": _lib.top_terms(term_pairs),
        "read_only": True,
        "prompt": _lib.effective_setting(conn, "review_prompt"),
    }


def cmd_stats(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    start, end, _label = _range(conn, args)
    as_of = _lib.resolve_today(conn, args)
    rows = _rows_in_range(conn, start, end)
    active = [date.fromisoformat(row["entry_date"]) for row in rows]
    current_run, longest_run = _lib.day_run(active, min(end, as_of))
    return {
        "read_only": True,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "entry_count": len(rows),
        "total_words": sum(int(row["word_count"]) for row in rows),
        "active_days": len(set(active)),
        "current_run": current_run,
        "longest_run": longest_run,
        "first_entry": rows[0]["entry_date"] if rows else None,
        "last_entry": rows[-1]["entry_date"] if rows else None,
    }


# ---------------------------------------------------------------------------
# Scheduling artifact
# ---------------------------------------------------------------------------

def _validate_hhmm(value: str) -> Tuple[int, int]:
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


def cmd_schedule_hint(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    target = args.target
    path_mode = args.path_mode or ("abs" if target in ABS_DEFAULT_TARGETS else "skill")
    if path_mode not in ("abs", "relative", "skill"):
        raise _lib.CommandError("invalid_input", "--path-mode must be abs, relative, or skill")
    tz = args.tz or _lib.effective_setting(conn, "tz") or os.environ.get("TZ") or _lib.DEFAULT_TZ
    name = args.name or "journal-weekly"
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
            prog="journal",
            service="journal-weekly.service",
            timer="journal-weekly.timer",
            plist="com.journal.weekly.plist",
            add_command="python3 " + script + " week --db " + db_path,
            add_note="The emitted command is a read-only report, so re-adding is harmless.",
        )
    hour, minute = _validate_hhmm(args.at_time or "08:00")
    cron_expr = "%d %d * * *" % (minute, hour)
    python = "/usr/bin/env python3" if target in OS_TARGETS else "python3"
    week_cmd = python + " " + script + " week --db " + db_path

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
                "description": "Build the weekly review brief (read-only)",
                "command": week_cmd,
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
            "compose a short weekly review from the returned brief only. The command is "
            "read-only and the script owns every count."
        )
        base["notes"] = [
            "This target installs nothing; the agent or user registers it.",
            "The weekly brief carries counts, notable lines, top terms, and a prompt.",
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
            "$journal Build the weekly review brief and write the review from it. Run: "
            + week_cmd
            + " ; then compose 3-6 sentences from the brief only."
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
            "This is the only target that uses the $journal explicit invocation.",
            "The report command is read-only, so duplicate fires are harmless.",
            "Remove the job through the cron tool; that does not touch the entries.",
        ]
        return base

    if target == "hermes":
        hermes_script = _script_path("abs") + " week --format json"
        message = "$journal Build the weekly review brief and write the review from it."
        base["name"] = name
        base["message"] = message
        base["skills"] = ["journal"]
        base["script"] = hermes_script
        base["cron_tool"] = {
            "action": "add",
            "tool": "cronjob",
            "name": name,
            "message": message,
            "cron_expr": cron_expr,
            "tz": tz,
            "skills": ["journal"],
            "script": hermes_script,
        }
        base["hermes_cli"] = (
            "hermes cron add --name %s --schedule '%s' --skills journal" % (name, cron_expr)
        )
        base["instructions"] = (
            "Create the job with the cronjob tool (or the equivalent hermes cron add "
            "command). Hermes injects the pre-run script's stdout into the prompt."
        )
        base["notes"] = [
            "skills:[journal] makes the skill available to the cron session.",
            "The script is read-only, so duplicate fires are harmless.",
        ]
        return base

    if target == "crontab":
        cron_cmd = python + " " + script + " week --db " + db_path + " --quiet"
        base["install"] = {"type": "crontab", "lines": ["%d %d * * 0 %s" % (minute, hour, cron_cmd)]}
        base["instructions"] = (
            "Append this line to your crontab (crontab -e). It runs the script directly "
            "and produces no chat notification. Remove it with crontab -e."
        )
        base["notes"] = [
            "The line is read-only, so catching up never rewrites anything.",
            "--quiet keeps an empty week from generating cron email.",
        ]
        return base

    if target == "systemd":
        service_cmd = (
            "/usr/bin/env python3 " + script + " week --db " + db_path + " --quiet"
        )
        service = (
            "[Unit]\n"
            "Description=Build the journal weekly review brief\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/bin/sh -c '%s'\n" % service_cmd
        )
        timer = (
            "[Unit]\n"
            "Description=Weekly journal review brief\n\n"
            "[Timer]\n"
            "OnCalendar=*-*-* %02d:%02d:00\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n" % (hour, minute)
        )
        base["install"] = {
            "type": "systemd",
            "files": {
                "journal-weekly.service": service,
                "journal-weekly.timer": timer,
            },
            "commands": [
                "systemctl --user daemon-reload",
                "systemctl --user enable --now journal-weekly.timer",
            ],
        }
        base["instructions"] = (
            "Write both files to ~/.config/systemd/user/, then run the install commands. "
            "This produces no chat notification; remove with systemctl --user disable --now "
            "journal-weekly.timer."
        )
        base["notes"] = [
            "Persistent=true catches up runs missed while the machine was off.",
            "The service is read-only.",
        ]
        return base

    run_cmd = "/usr/bin/env python3 " + script + " week --db " + db_path + " --quiet"
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "  <key>Label</key>\n"
        "  <string>com.journal.weekly</string>\n"
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
        "files": {"com.journal.weekly.plist": plist},
        "commands": [
            "cp com.journal.weekly.plist ~/Library/LaunchAgents/",
            "launchctl load ~/Library/LaunchAgents/com.journal.weekly.plist",
        ],
    }
    base["instructions"] = (
        "Write the plist to ~/Library/LaunchAgents/ and load it with launchctl. This "
        "produces no chat notification; unload with launchctl unload."
    )
    base["notes"] = [
        "launchd runs missed jobs on wake when the machine was asleep.",
        "The job is read-only.",
    ]
    return base


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="reports.py", description="Journal reports and scheduling.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    week = subparsers.add_parser(
        "week",
        help="build the weekly review brief",
        description="Return a read-only weekly brief for the host model to compose from.",
        parents=[common],
    )
    week.add_argument("--week", help="ISO week YYYY-Www")
    week.add_argument("--from", dest="from_date")
    week.add_argument("--to", dest="to_date")
    week.set_defaults(func=cmd_week, verb="week")

    stats = subparsers.add_parser(
        "stats",
        help="totals and consecutive-day runs",
        description="Show entry totals and day-run statistics (read-only).",
        parents=[common],
    )
    stats.add_argument("--week", help="ISO week YYYY-Www")
    stats.add_argument("--from", dest="from_date")
    stats.add_argument("--to", dest="to_date")
    stats.set_defaults(func=cmd_stats, verb="stats")

    hint = subparsers.add_parser(
        "schedule-hint",
        help="emit a scheduling artifact (never installs)",
        description="Emit an installable scheduling artifact for a chosen host or OS scheduler.",
        parents=[common],
    )
    hint.add_argument("--target", choices=list(SCHEDULE_TARGETS), default="generic")
    hint.add_argument("--path-mode", choices=("abs", "relative", "skill"))
    hint.add_argument("--at-time", default="08:00", help="trigger time HH:MM (default 08:00)")
    hint.add_argument("--name", help="job name for agent targets")
    _lib.add_action_flags(hint)
    hint.set_defaults(func=cmd_schedule_hint, verb="schedule-hint")

    return parser


def main() -> None:
    _lib.run_script("reports", build_parser())


if __name__ == "__main__":
    main()
