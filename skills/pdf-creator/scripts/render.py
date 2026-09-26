#!/usr/bin/env python3
"""Render document specs to PDF and emit scheduling artifacts.

Verbs:

- ``render`` — render a stored document (``--doc``) or a spec file (``--spec``)
  to a PDF, optionally substituting ``{{var}}`` placeholders.
- ``check`` — validate a spec without rendering; ``--strict`` also resolves
  fonts, images, and every block through the engine.
- ``from-markdown`` — convert a Markdown file to a PDF.
- ``schedule-hint`` — emit a scheduler artifact that re-renders a document.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _engine
import _lib
import _markdown

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_TARGETS = ("generic", "nanobot", "hermes", "claude", "codex", "kilo", "crontab", "systemd", "launchd")
ABS_DEFAULT_TARGETS = ("nanobot", "hermes", "crontab", "systemd", "launchd")
OS_TARGETS = ("crontab", "systemd", "launchd")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_vars(pairs: Optional[List[str]]) -> Dict[str, str]:
    variables: Dict[str, str] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise _lib.CommandError("invalid_input", "--var expects NAME=VALUE, got %r" % pair)
        name, value = pair.split("=", 1)
        variables[name.strip()] = value
    return variables


def _parse_tags(value: Optional[str]) -> str:
    if not value:
        return ""
    tags = [tag.strip() for tag in str(value).split(",") if tag.strip()]
    return ",".join(dict.fromkeys(tags))


def _load_spec_for(conn: sqlite3.Connection, args: argparse.Namespace) -> Tuple[Dict[str, Any], Path, Optional[sqlite3.Row]]:
    variables = _parse_vars(getattr(args, "var", None))
    if args.doc:
        row = conn.execute("SELECT * FROM documents WHERE name = ?", (args.doc,)).fetchone()
        if row is None:
            raise _lib.CommandError("not_found", "no stored document named %r" % args.doc)
        spec = _lib.substitute_vars(json.loads(row["spec"]), variables) if variables else json.loads(row["spec"])
        spec, _ = _lib.validate_spec(spec)
        return spec, Path.cwd(), row
    if args.spec:
        path = Path(args.spec).expanduser()
        spec = _lib.load_spec(path, variables)
        spec, _ = _lib.validate_spec(spec)
        return spec, path.resolve().parent, None
    raise _lib.CommandError("invalid_input", "pass --doc NAME or --spec FILE")


def _resolve_out(conn: sqlite3.Connection, home: Path, args: argparse.Namespace, doc_row: Optional[sqlite3.Row], default_name: str) -> Path:
    if args.out:
        out_path = Path(args.out).expanduser()
        if out_path.is_dir():
            out_path = out_path / ("%s.pdf" % default_name)
        return out_path
    return _lib.resolve_output_dir(conn, home) / ("%s.pdf" % _lib.slugify(default_name))


def _record_render(conn: sqlite3.Connection, doc_row: Optional[sqlite3.Row], name: str, result: Dict[str, Any]) -> int:
    cursor = conn.execute(
        "INSERT INTO renders (document_id, name, out_path, pages, bytes, sha256, width_pt, height_pt, warnings, rendered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            doc_row["id"] if doc_row is not None else None,
            name,
            result["out"],
            result["pages"],
            result["bytes"],
            result["sha256"],
            result["width_pt"],
            result["height_pt"],
            "; ".join(result.get("warnings") or []),
            _lib.now_iso(),
        ),
    )
    if doc_row is not None:
        conn.execute(
            "UPDATE documents SET render_count = render_count + 1, last_rendered_at = ?, last_output = ?, updated_at = ? WHERE id = ?",
            (_lib.now_iso(), result["out"], _lib.now_iso(), doc_row["id"]),
        )
    return int(cursor.lastrowid)


def _settings(conn: sqlite3.Connection) -> Dict[str, str]:
    return _lib.effective_settings(conn)


# ---------------------------------------------------------------------------
# render / check / from-markdown
# ---------------------------------------------------------------------------

def cmd_render(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    spec, base_dir, doc_row = _load_spec_for(conn, args)
    default_name = doc_row["name"] if doc_row is not None else Path(args.spec).stem
    out_path = _resolve_out(conn, home, args, doc_row, default_name)
    if out_path.exists() and not args.force:
        raise _lib.CommandError("conflict", "%s exists; pass --force to overwrite" % out_path)
    result = _engine.build_pdf(
        spec,
        out_path,
        home=home,
        base_dir=base_dir,
        settings=_settings(conn),
        allow_remote=args.allow_remote,
    )
    payload: Dict[str, Any] = dict(result)
    payload["document"] = doc_row["name"] if doc_row is not None else None
    payload["recipe"] = "spec" if doc_row is None else "document"
    if not args.no_record:
        payload["render_id"] = _record_render(conn, doc_row, doc_row["name"] if doc_row is not None else out_path.stem, result)
    return payload


def cmd_check(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if args.doc and not args.spec:
        row = conn.execute("SELECT * FROM documents WHERE name = ?", (args.doc,)).fetchone()
        if row is None:
            raise _lib.CommandError("not_found", "no stored document named %r" % args.doc)
        spec = json.loads(row["spec"])
    else:
        spec = _lib.load_spec(Path(args.spec).expanduser(), _parse_vars(getattr(args, "var", None)))
    spec, warnings = _lib.validate_spec(spec)
    payload: Dict[str, Any] = {
        "valid": True,
        "spec_version": spec.get("spec_version", _lib.SPEC_VERSION),
        "blocks": len(spec.get("content") or []),
        "theme": spec.get("theme"),
        "warnings": warnings,
        "strict": bool(args.strict),
    }
    if args.strict:
        base_dir = Path.cwd() if args.doc else Path(args.spec).expanduser().resolve().parent
        builder = _engine.Builder(spec, home=home, base_dir=base_dir, settings=_settings(conn))
        story = builder.story()
        payload["flowables"] = len(story)
        payload["warnings"] = warnings + builder.warnings
        payload["pages_hint"] = None
    return payload


def cmd_from_markdown(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    source = Path(args.input).expanduser()
    try:
        text = source.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise _lib.CommandError("not_found", "markdown file not found: %s" % source)
    except OSError as exc:
        raise _lib.CommandError("io_error", "could not read %s: %s" % (source, exc))

    blocks: List[Any] = _markdown.from_markdown(text)
    spec: Dict[str, Any] = {
        "spec_version": _lib.SPEC_VERSION,
        "meta": {"title": args.title or source.stem, "author": args.author or _lib.effective_setting(conn, "author")},
        "content": blocks,
    }
    if args.theme:
        spec["theme"] = args.theme
    if args.toc:
        spec["toc"] = {"title": args.toc_title, "depth": 2}
    if args.number_headings:
        spec["number_headings"] = True
    if args.header:
        spec["header"] = {"text": args.header, "align": "right", "divider": True}
    if args.footer:
        spec["footer"] = {"text": args.footer, "align": "center"}
    _lib.validate_spec(spec)

    out_path = Path(args.out).expanduser() if args.out else _lib.resolve_output_dir(conn, home) / ("%s.pdf" % _lib.slugify(source.stem))
    if out_path.exists() and not args.force:
        raise _lib.CommandError("conflict", "%s exists; pass --force to overwrite" % out_path)
    result = _engine.build_pdf(
        spec, out_path, home=home, base_dir=source.resolve().parent, settings=_settings(conn), allow_remote=args.allow_remote
    )
    payload: Dict[str, Any] = dict(result)
    payload["source"] = str(source)
    payload["blocks"] = len(blocks)
    payload["document"] = None
    payload["recipe"] = "markdown"
    if not args.no_record:
        payload["render_id"] = _record_render(conn, None, source.stem, result)
    return payload


# ---------------------------------------------------------------------------
# schedule-hint
# ---------------------------------------------------------------------------

def _script_path(script: str, path_mode: str) -> str:
    if path_mode == "abs":
        return os.path.join(SKILL_DIR, "scripts", script)
    if path_mode == "relative":
        return os.path.join("scripts", script)
    return "{skillDir}/scripts/%s" % script


def _validate_hhmm(value: str) -> Tuple[int, int]:
    parts = (value or "").strip().split(":")
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


def cmd_schedule_hint(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    target = args.target
    path_mode = args.path_mode or ("abs" if target in ABS_DEFAULT_TARGETS else "skill")
    if path_mode not in ("abs", "relative", "skill"):
        raise _lib.CommandError("invalid_input", "--path-mode must be abs, relative, or skill")
    tz = args.tz or os.environ.get("TZ") or "UTC"
    name = args.name or "pdf-creator-render"
    render_script = _script_path("render.py", path_mode)
    reports_script = _script_path("reports.py", path_mode)
    store = str(_lib.resolve_db_path(home))
    generated_at = _lib.today_iso()
    action = args.action or "add"

    source_flag = ""
    if args.doc:
        source_flag = " --doc " + args.doc
    elif args.spec:
        source_flag = " --spec " + args.spec
    else:
        raise _lib.CommandError("invalid_input", "pass --doc NAME or --spec FILE to schedule a render")
    out_flag = " --out " + args.out if args.out else ""
    base_command = "python3 " + render_script + " render" + source_flag + out_flag + " --force --quiet"
    report_command = "python3 " + reports_script + " history --limit 1"

    if action != "add":
        return _lib.manage_artifact(
            action,
            args.job,
            target=target,
            family=("chat" if target == "nanobot" else "cli" if target == "hermes" else "host" if target in ("generic", "claude", "codex", "kilo") else "os"),
            cli_name="hermes",
            path_mode=path_mode,
            tz=tz,
            name=name,
            script=render_script,
            store=store,
            generated_at=generated_at,
            skill_dir=SKILL_DIR,
            prog="pdf-creator",
            service="pdf-creator-render.service",
            timer="pdf-creator-render.timer",
            plist="com.pdf-creator.render.plist",
            add_command=base_command,
            add_note="The render command overwrites its output file; re-adding is harmless.",
        )

    hour, minute = _validate_hhmm(args.at_time or "08:00")
    cron_expr = "%d %d * * *" % (minute, hour)
    python = "/usr/bin/env python3" if target in OS_TARGETS else "python3"
    post_command = python + base_command[len("python3"):]
    report_command_full = python + report_command[len("python3"):]

    base: Dict[str, Any] = {
        "target": target,
        "path_mode": path_mode,
        "generated_at": generated_at,
        "action": "add",
        "skill_dir": SKILL_DIR,
        "script": render_script,
        "store": store,
        "name": name,
        "cron_expr": cron_expr,
        "tz": tz,
        "commands": [
            {"step": "post", "description": "Render the document (overwrites its output PDF)", "command": post_command},
            {"step": "report", "description": "Read the most recent render record (read-only)", "command": report_command_full},
        ],
        "installs_nothing": True,
        "read_only": False,
    }

    if target in ("generic", "claude", "codex", "kilo"):
        base["instructions"] = (
            "Register a recurring task with your host's scheduling mechanism. On each trigger, "
            "run the post command to refresh the PDF, then the report command to summarize what "
            "was produced. The post command only writes its output file."
        )
        base["notes"] = [
            "This target installs nothing; the agent or user registers it.",
            "The render is deterministic for a given spec, so a repeat simply rewrites the file.",
            "The report command is read-only and safe to re-run.",
        ]
        return base

    if target == "nanobot":
        message = "$pdf-creator Render the scheduled document and report the result. Run: " + post_command
        base["name"] = name
        base["message"] = message
        base["cron_tool"] = {"action": "add", "name": name, "message": message, "cron_expr": cron_expr, "tz": tz}
        base["instructions"] = (
            "Create this job with your host's built-in cron tool using the cron_tool fields above. "
            "Create it from a live chat session. Keep cron_expr and tz together."
        )
        base["notes"] = [
            "This is the only target that uses the $pdf-creator explicit invocation.",
            "The render overwrites its output file; duplicate fires are harmless.",
        ]
        return base

    if target == "hermes":
        message = "$pdf-creator Render the scheduled document and report the result."
        base["name"] = name
        base["message"] = message
        base["skills"] = ["pdf-creator"]
        base["script"] = os.path.join(SKILL_DIR, "scripts", "render.py") + source_flag + out_flag + " --force --quiet --format json"
        base["cron_tool"] = {
            "action": "add", "tool": "cronjob", "name": name, "message": message,
            "cron_expr": cron_expr, "tz": tz, "skills": ["pdf-creator"], "script": base["script"],
        }
        base["hermes_cli"] = "hermes cron add --name %s --schedule '%s' --skills pdf-creator" % (name, cron_expr)
        base["instructions"] = "Create the job with the cronjob tool (or the equivalent hermes cron add command)."
        return base

    if target == "crontab":
        cron_cmd = post_command.replace("$(date +%F)", "$(date +\\%F)")
        base["install"] = {"type": "crontab", "lines": ["%d %d * * * %s" % (minute, hour, cron_cmd)]}
        base["instructions"] = "Append this line to your crontab (crontab -e). It renders directly; remove it with crontab -e."
        base["notes"] = ["--quiet keeps cron email quiet; the render only writes its output file."]
        return base

    if target == "systemd":
        service = (
            "[Unit]\nDescription=Render a pdf-creator document\n\n[Service]\nType=oneshot\nExecStart=/bin/sh -c '%s'\n" % post_command
        )
        timer = (
            "[Unit]\nDescription=Recurring pdf-creator render\n\n[Timer]\n"
            "OnCalendar=*-*-* %02d:%02d:00\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n" % (hour, minute)
        )
        base["install"] = {
            "type": "systemd",
            "files": {"pdf-creator-render.service": service, "pdf-creator-render.timer": timer},
            "commands": ["systemctl --user daemon-reload", "systemctl --user enable --now pdf-creator-render.timer"],
        }
        base["instructions"] = "Write both files to ~/.config/systemd/user/, then run the install commands."
        return base

    run_cmd = post_command
    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n  <key>Label</key>\n  <string>com.pdf-creator.render</string>\n'
        "  <key>ProgramArguments</key>\n  <array>\n    <string>/bin/sh</string>\n    <string>-c</string>\n"
        "    <string>%s</string>\n  </array>\n  <key>StartCalendarInterval</key>\n  <dict>\n"
        "    <key>Hour</key>\n    <integer>%d</integer>\n    <key>Minute</key>\n    <integer>%d</integer>\n"
        "  </dict>\n</dict>\n</plist>\n" % (_xml_escape(run_cmd), hour, minute)
    )
    base["install"] = {
        "type": "launchd",
        "files": {"com.pdf-creator.render.plist": plist},
        "commands": [
            "cp com.pdf-creator.render.plist ~/Library/LaunchAgents/",
            "launchctl load ~/Library/LaunchAgents/com.pdf-creator.render.plist",
        ],
    }
    base["instructions"] = "Copy the plist to ~/Library/LaunchAgents/ and load it. Remove it with launchctl unload and rm."
    return base


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _add_render_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--doc", help="name of a stored document")
    parser.add_argument("--spec", help="path to a JSON spec file")
    parser.add_argument("--var", action="append", metavar="NAME=VALUE", help="substitute {{NAME}} in the spec; repeatable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="render.py", description="Render document specs to PDF.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="render a document or spec to PDF", parents=[_lib.common_parser()])
    _add_render_inputs(render)
    render.add_argument("--out", help="output PDF path (default: <home>/output/<name>.pdf)")
    render.add_argument("--force", action="store_true", help="overwrite an existing output file")
    render.add_argument("--allow-remote", action="store_true", help="allow fetching remote images")
    render.add_argument("--no-record", action="store_true", help="do not write a render-history row")
    render.set_defaults(func=cmd_render)

    check = subparsers.add_parser("check", help="validate a spec without rendering", parents=[_lib.common_parser()])
    _add_render_inputs(check)
    check.add_argument("--strict", action="store_true", help="also resolve fonts, images, and blocks via the engine")
    check.set_defaults(func=cmd_check)

    from_md = subparsers.add_parser("from-markdown", help="render a Markdown file to PDF", parents=[_lib.common_parser()])
    from_md.add_argument("--in", dest="input", required=True, help="input Markdown file")
    from_md.add_argument("--out", help="output PDF path")
    from_md.add_argument("--title", help="document title")
    from_md.add_argument("--author", help="document author")
    from_md.add_argument("--theme", help="theme name")
    from_md.add_argument("--header", help="running header text")
    from_md.add_argument("--footer", help="running footer text (supports {page} and {pages})")
    from_md.add_argument("--toc", action="store_true", help="insert a table of contents")
    from_md.add_argument("--toc-title", default="Contents", help="TOC heading (default: Contents)")
    from_md.add_argument("--number-headings", action="store_true", help="number headings")
    from_md.add_argument("--force", action="store_true", help="overwrite an existing output file")
    from_md.add_argument("--allow-remote", action="store_true", help="allow fetching remote images")
    from_md.add_argument("--no-record", action="store_true", help="do not write a render-history row")
    from_md.set_defaults(func=cmd_from_markdown)

    hint = subparsers.add_parser("schedule-hint", help="emit a scheduler artifact", parents=[_lib.common_parser()])
    _add_render_inputs(hint)
    hint.add_argument("--out", help="output PDF path for the scheduled render")
    hint.add_argument("--target", choices=list(SCHEDULE_TARGETS), default="generic")
    hint.add_argument("--path-mode", choices=("abs", "relative", "skill"))
    hint.add_argument("--at-time", default="08:00", help="daily trigger time, HH:MM (default 08:00)")
    hint.add_argument("--name", help="job name for agent targets")
    _lib.add_action_flags(hint)
    hint.set_defaults(func=cmd_schedule_hint)
    return parser


if __name__ == "__main__":
    _lib.run_script("render", build_parser())
