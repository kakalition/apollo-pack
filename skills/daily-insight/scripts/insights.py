#!/usr/bin/env python3
"""Deliver insights: day planning, chunk selection, and scheduling hints.

``due`` previews the deterministic day plan, ``next`` delivers exactly one due
insight, ``run`` catches up every slot due by a time, and ``schedule-hint``
emits a host artifact (installing nothing). Delivery is idempotent: the
``deliveries`` primary key ``(date, slot_index)`` makes a repeated call a
no-op.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import date, datetime, time as dtime, timedelta
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

BRIEF_PROMPT = (
    "Compose a short, skimmable insight (3-6 sentences) in the user's language, "
    "using only the excerpt and the related passages below. Name the material it "
    "came from. Do not invent facts that are not in the excerpts."
)

SYSTEM_PROMPT = (
    "You turn source excerpts into brief, faithful insights. Never add facts that "
    "are not present in the provided excerpts."
)


# ---------------------------------------------------------------------------
# Brief construction
# ---------------------------------------------------------------------------

def _related_chunks(
    conn: sqlite3.Connection,
    collection: Any,
    material_id: int,
    chunk: sqlite3.Row,
    count: int = _lib.RELATED_COUNT,
) -> List[Dict[str, Any]]:
    if collection is None:
        return []
    chunk_id = "%d:%d" % (int(material_id), int(chunk["ordinal"]))
    vectors = _lib.chroma_get_embeddings(collection, [chunk_id])
    vector = vectors.get(chunk_id)
    if vector is None:
        return []
    recent_ids = {
        int(row["id"]) for row in _lib.recent_delivered_chunks(conn, int(material_id), _lib.DEDUP_RECENT)
    }
    related: List[Dict[str, Any]] = []
    for ident, score in _lib.chroma_query(collection, vector, int(material_id), count + 3):
        try:
            _, ordinal_text = ident.split(":", 1)
            ordinal = int(ordinal_text)
        except (ValueError, AttributeError):
            continue
        if ordinal == int(chunk["ordinal"]):
            continue
        row = conn.execute(
            "SELECT * FROM chunks WHERE material_id = ? AND ordinal = ?",
            (int(material_id), ordinal),
        ).fetchone()
        if row is None or int(row["id"]) in recent_ids:
            continue
        related.append(
            {
                "ordinal": ordinal,
                "text": row["text"],
                "score": round(float(score), 4),
            }
        )
        if len(related) >= count:
            break
    return related


def build_brief(
    conn: sqlite3.Connection,
    collection: Any,
    slot: Dict[str, Any],
    material: sqlite3.Row,
    chunk: sqlite3.Row,
) -> Dict[str, Any]:
    total = int(material["chunk_count"] or 0)
    delivered = conn.execute(
        "SELECT COUNT(DISTINCT chunk_id) AS n FROM deliveries WHERE material_id = ?",
        (material["id"],),
    ).fetchone()["n"]
    coverage = round((delivered / total) * 100.0, 1) if total else 0.0
    related = _related_chunks(conn, collection, int(material["id"]), chunk)
    return {
        "slot": {"date": slot["date"], "index": slot["index"], "due_at": slot["due_at"]},
        "material": {
            "id": material["id"],
            "name": material["name"],
            "cadence": "%d/%s" % (int(material["cadence_count"]), material["cadence_period"]),
        },
        "chunk": {
            "ordinal": int(chunk["ordinal"]),
            "text": chunk["text"],
            "token_est": int(chunk["token_est"]),
        },
        "related": related,
        "novelty": {
            "material_delivered": int(delivered),
            "material_total": total,
            "coverage_pct": coverage,
        },
        "prompt": BRIEF_PROMPT,
    }


def _generate_for_brief(conn: sqlite3.Connection, brief: Dict[str, Any]) -> str:
    excerpt = brief["chunk"]["text"]
    related_blocks = []
    for item in brief["related"]:
        related_blocks.append("[%d] %s" % (item["ordinal"], item["text"]))
    related_text = "\n\n".join(related_blocks) if related_blocks else "(none)"
    prompt = (
        "Material: %s\n\nExcerpt:\n%s\n\nRelated passages:\n%s\n\n%s"
        % (brief["material"]["name"], excerpt, related_text, brief["prompt"])
    )
    return _lib.generate_text(conn, prompt, SYSTEM_PROMPT)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

def _settings_for_delivery(conn: sqlite3.Connection, args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "strategy": getattr(args, "strategy", None) or _lib.effective_setting(conn, "strategy") or _lib.DEFAULT_STRATEGY,
        "query": getattr(args, "query", None),
        "cooldown_days": (
            args.cooldown_days if getattr(args, "cooldown_days", None) is not None
            else _lib.setting_int(conn, "cooldown_days", _lib.DEFAULT_COOLDOWN_DAYS)
        ),
        "dedup_threshold": (
            args.dedup_threshold if getattr(args, "dedup_threshold", None) is not None
            else _lib.setting_float(conn, "dedup_threshold", _lib.DEFAULT_DEDUP_THRESHOLD)
        ),
    }


def _append_outbox(home, brief: Dict[str, Any], insight_text: Optional[str], due_at: str) -> str:
    outbox = _lib.resolve_outbox_path(home)
    outbox.mkdir(parents=True, exist_ok=True)
    target = outbox / ("%s.md" % brief["slot"]["date"])
    body = insight_text or brief["chunk"]["text"]
    block = (
        "\n## %s — %s\n\n%s\n\n_Source: %s, chunk %d._\n"
        % (
            brief["material"]["name"],
            due_at,
            body.strip(),
            brief["material"]["name"],
            brief["chunk"]["ordinal"],
        )
    )
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(block)
    return str(target)


def _deliver_slot(
    conn: sqlite3.Connection,
    home,
    collection: Any,
    slot_row: sqlite3.Row,
    options: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Claim and deliver one slot. Returns the brief, or None if already claimed."""
    material = _lib.resolve_material(conn, int(slot_row["material_id"]), allow_archived=True)
    chunk = _lib.select_chunk(
        conn,
        collection,
        material,
        options["strategy"],
        options["query"],
        options["cooldown_days"],
        options["dedup_threshold"],
        options["today"],
    )
    slot = {
        "date": slot_row["date"],
        "index": int(slot_row["slot_index"]),
        "due_at": slot_row["due_at"],
    }
    brief = build_brief(conn, collection, slot, material, chunk)

    insight_text: Optional[str] = None
    if options["generate"]:
        insight_text = _generate_for_brief(conn, brief)

    delivered_at = _lib.now_local(options["tz_name"]).isoformat(timespec="seconds")
    cursor = conn.execute(
        "UPDATE day_slots SET status = 'delivered', chunk_id = ?, delivered_at = ?, generated = ? "
        "WHERE date = ? AND slot_index = ? AND status = 'planned'",
        (
            int(chunk["id"]),
            delivered_at,
            1 if options["generate"] else 0,
            slot["date"],
            slot["index"],
        ),
    )
    if cursor.rowcount != 1:
        return None  # another trigger claimed the slot first

    conn.execute(
        "INSERT OR IGNORE INTO deliveries "
        "(date, slot_index, material_id, chunk_id, delivered_at, generated, insight_text) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            slot["date"],
            slot["index"],
            int(material["id"]),
            int(chunk["id"]),
            delivered_at,
            1 if options["generate"] else 0,
            insight_text,
        ),
    )
    conn.execute(
        "UPDATE chunks SET delivered_count = delivered_count + 1, last_delivered_at = ? WHERE id = ?",
        (delivered_at, int(chunk["id"])),
    )
    brief["delivered_at"] = delivered_at
    if insight_text:
        brief["insight_text"] = insight_text
    if options.get("outbox"):
        brief["outbox"] = _append_outbox(home, brief, insight_text, slot["due_at"])
    return brief


def _slot_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    material = conn.execute("SELECT name FROM materials WHERE id = ?", (row["material_id"],)).fetchone()
    return {
        "index": int(row["slot_index"]),
        "material_id": row["material_id"],
        "material": material["name"] if material else None,
        "due_at": row["due_at"],
        "status": row["status"],
        "chunk_id": row["chunk_id"],
        "delivered_at": row["delivered_at"],
        "generated": bool(row["generated"]),
    }


# ---------------------------------------------------------------------------
# Verbs
# ---------------------------------------------------------------------------

def cmd_due(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    day = date.fromisoformat(_lib.validate_date(args.date)) if args.date else _lib.resolve_today(conn, args)
    today = day.isoformat()
    plan = _lib.ensure_day_plan(conn, day)
    rows = _lib.day_slots(conn, today)
    slots = [_slot_dict(conn, row) for row in rows]
    remaining = sum(1 for row in rows if row["status"] == "planned")
    delivered = sum(1 for row in rows if row["status"] == "delivered")

    upcoming: List[Dict[str, Any]] = []
    days = args.days if args.days is not None else 7
    if days > 0:
        for offset in range(1, days + 1):
            day = date.fromisoformat(today) + timedelta(days=offset)
            future = _lib.build_plan(conn, day)
            if future["planned_total"]:
                upcoming.append(
                    {
                        "date": day.isoformat(),
                        "planned_total": future["planned_total"],
                        "materials": [slot["material_name"] for slot in future["slots"]],
                    }
                )

    return {
        "date": today,
        "budget": plan["budget"],
        "wake": plan["wake"],
        "planned_total": plan["planned_total"],
        "remaining": remaining,
        "delivered": delivered,
        "slots": slots,
        "dropped": plan["dropped"],
        "upcoming": upcoming,
    }


def _next_deliverable(conn: sqlite3.Connection, day: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM day_slots WHERE date = ? AND status = 'planned' "
        "ORDER BY slot_index LIMIT 1",
        (day,),
    ).fetchone()


def cmd_next(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    day = date.fromisoformat(_lib.validate_date(args.date)) if args.date else _lib.resolve_today(conn, args)
    today = day.isoformat()
    plan = _lib.ensure_day_plan(conn, day)
    tz_name = args.tz or _lib.effective_setting(conn, "tz") or _lib.DEFAULT_TZ
    options = _settings_for_delivery(conn, args)
    options.update(
        {
            "generate": bool(args.generate),
            "outbox": bool(args.outbox),
            "today": day,
            "tz_name": tz_name,
        }
    )
    collection = None
    if _lib.deps_status().get("chromadb"):
        try:
            collection = _lib.open_collection(home)
        except _lib.CommandError:
            collection = None

    row = _next_deliverable(conn, today)
    if row is None:
        delivered = conn.execute(
            "SELECT COUNT(*) AS n FROM day_slots WHERE date = ? AND status = 'delivered'", (today,)
        ).fetchone()["n"]
        return {
            "status": "nothing_due",
            "date": today,
            "budget": plan["budget"],
            "delivered": int(delivered),
            "remaining": 0,
            "message": "all of today's slots are delivered; trigger again tomorrow",
        }

    brief = _deliver_slot(conn, home, collection, row, options)
    if brief is None:
        # Lost a race for this slot; report nothing rather than double-deliver.
        return {
            "status": "nothing_due",
            "date": today,
            "budget": plan["budget"],
            "remaining": len(_lib.day_slots(conn, today)),
            "message": "slot was claimed concurrently",
        }
    brief["status"] = "delivered"
    brief["date"] = today
    brief["budget"] = plan["budget"]
    return brief


def _parse_until(conn: sqlite3.Connection, args: argparse.Namespace) -> Tuple[str, str]:
    """Return (date, cutoff HH:MM) for ``run --until``."""
    explicit_date = getattr(args, "date", None)
    today = date.fromisoformat(explicit_date) if explicit_date else _lib.resolve_today(conn, args)
    raw = (args.until or "").strip()
    if not raw:
        now = _lib.now_local(args.tz or _lib.effective_setting(conn, "tz") or _lib.DEFAULT_TZ)
        return today.isoformat(), now.strftime("%H:%M")
    if "T" in raw or (" " in raw and "-" in raw):
        text = raw.replace("Z", "")
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            raise _lib.CommandError("invalid_date", "invalid --until %r" % raw)
        return moment.date().isoformat(), moment.strftime("%H:%M")
    if "-" in raw:
        day = _lib.validate_date(raw, "--until")
        return day, "23:59"
    minutes = _lib.parse_hhmm(raw, "--until")
    return today.isoformat(), _lib.fmt_hhmm(minutes)


def cmd_run(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    day_str, cutoff = _parse_until(conn, args)
    day = date.fromisoformat(day_str)
    _lib.ensure_day_plan(conn, day)
    tz_name = args.tz or _lib.effective_setting(conn, "tz") or _lib.DEFAULT_TZ
    options = _settings_for_delivery(conn, args)
    options.update(
        {
            "generate": bool(args.generate),
            "outbox": bool(args.outbox),
            "today": day,
            "tz_name": tz_name,
        }
    )
    collection = None
    if _lib.deps_status().get("chromadb"):
        try:
            collection = _lib.open_collection(home)
        except _lib.CommandError:
            collection = None

    cutoff_minutes = _lib.parse_hhmm(cutoff, "--until")
    real_today = _lib.resolve_today(conn, args)
    rows = _lib.day_slots(conn, day_str)
    briefs: List[Dict[str, Any]] = []
    for row in rows:
        if row["status"] != "planned":
            continue
        if day > real_today:
            continue
        due_minutes = _lib.parse_hhmm(row["due_at"] or "00:00", "due_at")
        if day == real_today and due_minutes > cutoff_minutes:
            continue
        brief = _deliver_slot(conn, home, collection, row, options)
        if brief is not None:
            briefs.append(brief)

    remaining = conn.execute(
        "SELECT COUNT(*) AS n FROM day_slots WHERE date = ? AND status = 'planned'", (day_str,)
    ).fetchone()["n"]
    return {
        "date": day_str,
        "until": cutoff,
        "delivered_count": len(briefs),
        "remaining": int(remaining),
        "briefs": briefs,
    }


# ---------------------------------------------------------------------------
# Scheduling artifact
# ---------------------------------------------------------------------------

def _script_path(path_mode: str) -> str:
    skill_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if path_mode == "abs":
        return os.path.join(skill_dir, "scripts", "insights.py")
    if path_mode == "relative":
        return os.path.join("scripts", "insights.py")
    return "{skillDir}/scripts/insights.py"


def _xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cron_expr(times: List[str]) -> str:
    hours = sorted({int(t.split(":")[0]) for t in times})
    minutes = sorted({int(t.split(":")[1]) for t in times})
    return "%s %s * * *" % (",".join(str(m) for m in minutes), ",".join(str(h) for h in hours))


def _deliver_flags(generate: bool, outbox: bool) -> str:
    flags = "next --format json"
    if generate:
        flags += " --generate"
    if outbox:
        flags += " --outbox"
    return flags


def cmd_schedule_hint(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    target = args.target
    path_mode = args.path_mode or ("abs" if target in ABS_DEFAULT_TARGETS else "skill")
    if path_mode not in ("abs", "relative", "skill"):
        raise _lib.CommandError("invalid_input", "--path-mode must be abs, relative, or skill")
    budget = args.budget if args.budget is not None else _lib.setting_int(conn, "budget", _lib.DEFAULT_BUDGET)
    wake = args.wake or _lib.effective_setting(conn, "wake") or _lib.DEFAULT_WAKE
    _lib.parse_wake(wake)
    tz = args.tz or _lib.effective_setting(conn, "tz") or os.environ.get("TZ") or _lib.DEFAULT_TZ
    name = args.name or "daily-insight"
    script = _script_path(path_mode)
    home_path = str(home)
    python = "/usr/bin/env python3" if target in OS_TARGETS else "python3"
    generate = bool(args.generate)
    outbox = bool(args.outbox) or target in OS_TARGETS

    today = _lib.resolve_today(conn, args)
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
            store=home_path,
            generated_at=today.isoformat(),
            skill_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            prog="daily-insight",
            service="daily-insight.service",
            timer="daily-insight.timer",
            plist="com.daily-insight.deliver.plist",
            add_command="%s %s %s --home %s"
            % (python, script, _deliver_flags(generate, outbox), home_path),
            add_note="Delivery is idempotent per (date, slot); re-adding is harmless.",
        )
    plan = _lib.build_plan(conn, today, budget=budget, wake=wake)
    times = [slot["due_at"] for slot in plan["slots"]]
    if not times:
        start, end = _lib.parse_wake(wake)
        times = _lib.spread_times(start, end, max(1, budget))
    if args.at_time:
        times = [_lib.fmt_hhmm(_lib.parse_hhmm(args.at_time, "--at-time"))]

    def command_for(slot_time: str) -> str:
        return "%s %s %s --home %s" % (
            python, script, _deliver_flags(generate, outbox), home_path
        )

    commands = [
        {
            "step": "post",
            "slot": index,
            "at": slot_time,
            "description": "Deliver the next due insight (idempotent per date and slot)",
            "command": command_for(slot_time),
        }
        for index, slot_time in enumerate(times)
    ]
    cron_expr = _cron_expr(times)

    base: Dict[str, Any] = {
        "target": target,
        "path_mode": path_mode,
        "generated_for": today.isoformat(),
        "generated_at": today.isoformat(),
        "action": "add",
        "skill_dir": os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "script": script,
        "store": home_path,
        "home": home_path,
        "budget": budget,
        "wake": wake,
        "slot_times": times,
        "cron_expr": cron_expr,
        "tz": tz,
        "commands": commands,
        "installs_nothing": True,
    }

    if target in ("generic", "claude", "codex", "kilo"):
        base["instructions"] = (
            "Register one recurring task per slot time with your host's scheduling "
            "mechanism, calling the emitted command. Each call delivers at most one "
            "insight and is idempotent, so repeat or catch-up triggers are safe. "
            "Render the returned brief in chat, or use --generate for finished prose. "
            "This target installs nothing; you register it."
        )
        base["notes"] = [
            "The script owns chunk selection; the scheduler only triggers it.",
            "Over-firing is harmless: an exhausted day returns nothing_due.",
            "Removing the trigger does not touch materials or cadences.",
        ]
        if target in ("claude", "codex", "kilo"):
            base["fallback"] = (
                "If this host has no native scheduler, use the crontab, launchd, or "
                "systemd target and register the emitted artifact."
            )
        return base

    if target == "nanobot":
        message = "$daily-insight Deliver the next due insight and render it for me."
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
            "This is the only target that uses the $daily-insight explicit invocation.",
            "Duplicate fires are no-ops because delivery is idempotent per (date, slot).",
            "Remove the job through the cron tool; that does not delete materials.",
        ]
        return base

    if target == "hermes":
        hermes_script = "%s next --format json" % _script_path("abs")
        message = "$daily-insight Deliver the next due insight and render it for me."
        base["name"] = name
        base["message"] = message
        base["skills"] = ["daily-insight"]
        base["script"] = hermes_script
        base["cron_tool"] = {
            "action": "add",
            "tool": "cronjob",
            "name": name,
            "message": message,
            "cron_expr": cron_expr,
            "tz": tz,
            "skills": ["daily-insight"],
            "script": hermes_script,
        }
        if generate:
            base["script"] = "%s --generate --outbox" % hermes_script
            base["cron_tool"]["script"] = base["script"]
            base["cron_tool"]["no_agent"] = True
        base["hermes_cli"] = (
            "hermes cron add --name %s --schedule '%s' --skills daily-insight%s"
            % (name, cron_expr, (" --script 'daily-insight/scripts/insights.py next --generate --outbox'"
                                 if generate else ""))
        )
        base["instructions"] = (
            "Create the job with the cronjob tool (or the equivalent hermes cron add "
            "command). Hermes injects the pre-run script's stdout into the prompt; with "
            "no_agent the script output is the whole job. Register one job per slot if "
            "the host cannot take a multi-time cron expression."
        )
        base["notes"] = [
            "skills:[daily-insight] makes the skill available to the cron session.",
            "Duplicate fires are no-ops because delivery is idempotent per (date, slot).",
        ]
        return base

    if target == "crontab":
        lines = [
            "%d %d * * * %s %s %s --home %s --quiet"
            % (
                int(slot_time.split(":")[1]),
                int(slot_time.split(":")[0]),
                python,
                script,
                _deliver_flags(generate, outbox),
                home_path,
            )
            for slot_time in times
        ]
        base["install"] = {"type": "crontab", "lines": lines}
        base["instructions"] = (
            "Append these lines to your crontab (crontab -e). They run the script "
            "directly and produce no chat notification. Remove them with crontab -e; "
            "that does not change materials or cadences."
        )
        base["notes"] = [
            "--generate --outbox appends finished insights to <home>/outbox/<date>.md.",
            "--quiet keeps an exhausted day silent.",
        ]
        return base

    if target == "systemd":
        service_cmd = (
            "/usr/bin/env python3 %s %s --home %s --quiet"
            % (script, _deliver_flags(generate, outbox), home_path)
        )
        service = (
            "[Unit]\n"
            "Description=Deliver a daily-insight insight\n\n"
            "[Service]\n"
            "Type=oneshot\n"
            "ExecStart=/bin/sh -c '%s'\n" % service_cmd
        )
        on_calendar = "\n".join(
            "OnCalendar=*-*-* %02d:%02d:00" % (int(t.split(":")[0]), int(t.split(":")[1]))
            for t in times
        )
        timer = (
            "[Unit]\n"
            "Description=Daily-insight delivery schedule\n\n"
            "[Timer]\n"
            "%s\n"
            "Persistent=true\n\n"
            "[Install]\n"
            "WantedBy=timers.target\n" % on_calendar
        )
        base["install"] = {
            "type": "systemd",
            "files": {
                "daily-insight.service": service,
                "daily-insight.timer": timer,
            },
            "commands": [
                "systemctl --user daemon-reload",
                "systemctl --user enable --now daily-insight.timer",
            ],
        }
        base["instructions"] = (
            "Write both files to ~/.config/systemd/user/, then run the install commands. "
            "This produces no chat notification."
        )
        base["notes"] = [
            "Persistent=true catches up runs missed while the machine was off.",
            "The service runs the script directly and writes to the outbox, not to chat.",
        ]
        return base

    # launchd
    run_cmd = "/usr/bin/env python3 %s %s --home %s --quiet" % (
        script, _deliver_flags(generate, outbox), home_path
    )
    intervals = "".join(
        "    <dict>\n"
        "      <key>Hour</key><integer>%d</integer>\n"
        "      <key>Minute</key><integer>%d</integer>\n"
        "    </dict>\n" % (int(t.split(":")[0]), int(t.split(":")[1]))
        for t in times
    )
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "  <key>Label</key>\n"
        "  <string>com.daily-insight.deliver</string>\n"
        "  <key>ProgramArguments</key>\n"
        "  <array>\n"
        "    <string>/bin/sh</string>\n"
        "    <string>-c</string>\n"
        "    <string>%s</string>\n"
        "  </array>\n"
        "  <key>StartCalendarInterval</key>\n"
        "  <array>\n"
        "%s"
        "  </array>\n"
        "</dict>\n"
        "</plist>\n" % (_xml_escape(run_cmd), intervals)
    )
    base["install"] = {
        "type": "launchd",
        "files": {"com.daily-insight.deliver.plist": plist},
        "commands": [
            "cp com.daily-insight.deliver.plist ~/Library/LaunchAgents/",
            "launchctl load ~/Library/LaunchAgents/com.daily-insight.deliver.plist",
        ],
    }
    base["instructions"] = (
        "Write the plist to ~/Library/LaunchAgents/ and load it with launchctl. This "
        "produces no chat notification."
    )
    base["notes"] = [
        "launchd runs missed jobs on wake when the machine was asleep.",
        "The job runs the script directly and writes to the outbox, not to chat.",
    ]
    return base


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _add_delivery_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", help="target date YYYY-MM-DD (default today)")
    parser.add_argument("--strategy", choices=list(_lib.STRATEGIES))
    parser.add_argument("--query", help="topic for the similarity strategy")
    parser.add_argument("--cooldown-days", type=int)
    parser.add_argument("--dedup-threshold", type=float)
    parser.add_argument("--generate", "--save", dest="generate", action="store_true",
                        help="also generate finished insight prose via the chat endpoint")
    parser.add_argument("--outbox", action="store_true",
                        help="append the insight to <home>/outbox/<date>.md")


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(prog="insights.py", description="Deliver daily insights.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    due = _lib.add_subparser(subparsers, "due", "preview the day plan (delivers nothing)", [common])
    due.add_argument("--date", help="target date YYYY-MM-DD (default today)")
    due.add_argument("--days", type=int, help="upcoming window in days (default 7)")
    due.set_defaults(func=cmd_due)

    nxt = _lib.add_subparser(subparsers, "next", "deliver exactly one due insight", [common])
    _add_delivery_flags(nxt)
    nxt.set_defaults(func=cmd_next)

    run = _lib.add_subparser(subparsers, "run", "deliver every slot due by a time (idempotent)", [common])
    _add_delivery_flags(run)
    run.add_argument("--until", help="cutoff: HH:MM, YYYY-MM-DD, or ISO datetime (default now)")
    run.set_defaults(func=cmd_run)

    hint = _lib.add_subparser(subparsers, "schedule-hint", "emit a scheduling artifact (never installs)", [common])
    hint.add_argument("--target", choices=list(SCHEDULE_TARGETS), default="generic")
    hint.add_argument("--path-mode", choices=("abs", "relative", "skill"))
    hint.add_argument("--budget", type=int)
    hint.add_argument("--wake", help="wake window HH:MM-HH:MM")
    hint.add_argument(
        "--at-time",
        help="single daily trigger time HH:MM (overrides the wake/budget spread)",
    )
    hint.add_argument("--name", help="job name")
    _lib.add_action_flags(hint)
    hint.add_argument("--generate", dest="generate", action="store_true")
    hint.add_argument("--outbox", action="store_true")
    hint.set_defaults(func=cmd_schedule_hint)

    return parser


def main() -> None:
    _lib.run_script("insights", build_parser())


if __name__ == "__main__":
    main()
