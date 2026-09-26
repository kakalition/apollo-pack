#!/usr/bin/env python3
"""Render chart specs to PNG and emit scheduling artifacts.

Verbs:

- ``render`` — render a stored chart (``--doc``) or a spec file (``--spec``) to
  a PNG, optionally substituting ``{{var}}`` placeholders.
- ``check`` — validate a spec without rendering; ``--strict`` also verifies
  Node, the esbuild bundle, and Chromium.
- ``component`` — emit the equivalent shadcn/Recharts JSX.
- ``schedule-hint`` — emit a scheduler artifact that re-renders a chart.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _html
import _lib

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCREENSHOT_SCRIPT = os.path.join(SKILL_DIR, "scripts", "screenshot.mjs")
SCHEDULE_TARGETS = ("generic", "nanobot", "hermes", "claude", "codex", "kilo", "crontab", "systemd", "launchd")
ABS_DEFAULT_TARGETS = ("nanobot", "hermes", "crontab", "systemd", "launchd")
OS_TARGETS = ("crontab", "systemd", "launchd")
SELECTOR = "#chart-root"


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


def _load_spec_for(conn: sqlite3.Connection, args: argparse.Namespace) -> Tuple[Dict[str, Any], Path, Optional[sqlite3.Row]]:
    variables = _parse_vars(getattr(args, "var", None))
    if args.doc:
        row = conn.execute("SELECT * FROM charts WHERE name = ?", (args.doc,)).fetchone()
        if row is None:
            raise _lib.CommandError("not_found", "no stored chart named %r" % args.doc)
        spec = json.loads(row["spec"])
        if variables:
            spec = _lib.substitute_vars(spec, variables)
        spec, _ = _lib.validate_spec(spec)
        return spec, Path.cwd(), row
    if args.spec:
        path = Path(args.spec).expanduser()
        spec = _lib.load_spec(path, variables)
        spec, _ = _lib.validate_spec(spec)
        return spec, path.resolve().parent, None
    raise _lib.CommandError("invalid_input", "pass --doc NAME or --spec FILE")


def _resolve_out(conn: sqlite3.Connection, home: Path, args: argparse.Namespace, default_name: str) -> Path:
    if args.out:
        out_path = Path(args.out).expanduser()
        if out_path.is_dir():
            out_path = out_path / ("%s.png" % default_name)
        return out_path
    return _lib.resolve_output_dir(conn, home) / ("%s.png" % _lib.slugify(default_name))


def _transparent(spec: Dict[str, Any], override: bool) -> bool:
    background = spec.get("background", "transparent")
    return bool(override) or not background or background == "transparent"


def _run_screenshot(html_path: Path, out_path: Path, spec: Dict[str, Any], transparent: bool) -> Dict[str, Any]:
    node = shutil.which("node")
    if node is None:
        raise _lib.CommandError(
            "dependency_missing",
            "Node.js is required to render charts; install Node 20+ then run: %s" % _lib.INSTALL_HINT,
        )
    bundle = _lib.bundle_path()
    if not bundle.is_file():
        raise _lib.CommandError(
            "dependency_missing",
            "the chart bundle is missing (%s); run: %s" % (bundle, _lib.INSTALL_HINT),
        )
    command = [
        node,
        SCREENSHOT_SCRIPT,
        str(html_path),
        str(out_path),
        "--width", str(spec["width"]),
        "--height", str(spec["height"]),
        "--scale", str(spec["scale"]),
        "--selector", SELECTOR,
    ]
    if transparent:
        command.append("--transparent")
    completed = subprocess.run(command, capture_output=True, text=True)
    payload: Optional[Dict[str, Any]] = None
    for line in reversed((completed.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                break
            except ValueError:
                continue
    if payload is None:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        raise _lib.CommandError(
            "render_failed",
            "Chromium render produced no result: %s" % (detail[-1] if detail else "no output"),
        )
    if not payload.get("ok"):
        error = payload.get("error") or {}
        raise _lib.CommandError(
            error.get("code", "render_failed"),
            error.get("message", "render failed"),
        )
    return payload


def _record_render(conn: sqlite3.Connection, chart_row: Optional[sqlite3.Row], name: str, result: Dict[str, Any]) -> int:
    cursor = conn.execute(
        "INSERT INTO renders (chart_id, name, out_path, width_px, height_px, scale, bytes, sha256, warnings, rendered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            chart_row["id"] if chart_row is not None else None,
            name,
            result["out"],
            result["width"],
            result["height"],
            result["scale"],
            result["bytes"],
            result["sha256"],
            "; ".join(result.get("warnings") or []),
            _lib.now_iso(),
        ),
    )
    if chart_row is not None:
        conn.execute(
            "UPDATE charts SET render_count = render_count + 1, last_rendered_at = ?, last_output = ?, updated_at = ? WHERE id = ?",
            (_lib.now_iso(), result["out"], _lib.now_iso(), chart_row["id"]),
        )
    return int(cursor.lastrowid)


def _resolve_pdf_home(args: argparse.Namespace) -> Path:
    cli = getattr(args, "pdf_home", None)
    if cli:
        raw = cli
    elif os.environ.get("PDF_CREATOR_HOME"):
        raw = os.environ["PDF_CREATOR_HOME"]
    else:
        raw = "~/.local/share/pdf-creator"
    return Path(os.path.expanduser(raw))


def _register_asset(args: argparse.Namespace, out_path: Path) -> Dict[str, Any]:
    assets = _resolve_pdf_home(args) / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    target = assets / out_path.name
    shutil.copy2(str(out_path), str(target))
    return {"pdf_home": str(_resolve_pdf_home(args)), "asset": target.name, "asset_path": str(target)}


def render_spec(
    conn: sqlite3.Connection,
    home: Path,
    spec: Dict[str, Any],
    out_path: Path,
    *,
    force: bool,
    transparent: bool = False,
    keep_html: bool = False,
    no_record: bool = False,
    chart_row: Optional[sqlite3.Row] = None,
    name: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Render a validated spec to a PNG and (optionally) record the render."""
    spec = _lib.apply_settings(spec, _lib.effective_settings(conn))
    spec, warnings = _lib.validate_spec(spec)
    if out_path.exists() and not force:
        raise _lib.CommandError("conflict", "%s exists; pass --force to overwrite" % out_path)
    is_transparent = _transparent(spec, transparent)
    html = _html.build_html(
        spec,
        _lib.bundle_path(),
        base_dir=base_dir or out_path.parent,
        transparent=is_transparent,
    )
    html_path = _lib.resolve_tmp_path(home) / ("%s.html" % _lib.slugify(name or out_path.stem))
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    try:
        _run_screenshot(html_path, out_path, spec, is_transparent)
    finally:
        if not keep_html:
            try:
                html_path.unlink()
            except OSError:
                pass
    info = _lib.png_info(out_path)
    expected_w = spec["width"] * spec["scale"]
    expected_h = spec["height"] * spec["scale"]
    if info["width"] != expected_w or info["height"] != expected_h:
        warnings.append(
            "PNG is %dx%d but %dx%d was requested" % (info["width"], info["height"], expected_w, expected_h)
        )
    result: Dict[str, Any] = {
        "out": str(out_path),
        "bytes": out_path.stat().st_size,
        "sha256": _lib.sha256_file(out_path),
        "width": info["width"],
        "height": info["height"],
        "scale": spec["scale"],
        "family": spec["chart"],
        "theme": spec.get("theme"),
        "background": "transparent" if is_transparent else spec.get("background"),
        "html": str(html_path) if keep_html else None,
        "warnings": warnings,
    }
    if not no_record:
        result["render_id"] = _record_render(conn, chart_row, name or out_path.stem, result)
    return result


# ---------------------------------------------------------------------------
# render / check / component
# ---------------------------------------------------------------------------

def cmd_render(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    spec, base_dir, chart_row = _load_spec_for(conn, args)
    default_name = chart_row["name"] if chart_row is not None else Path(args.spec).stem
    out_path = _resolve_out(conn, home, args, default_name)
    if args.scale is not None:
        try:
            spec["scale"] = int(args.scale)
        except (TypeError, ValueError):
            raise _lib.CommandError("invalid_input", "--scale must be an integer")
    if args.theme:
        spec["theme"] = args.theme
    spec, _ = _lib.validate_spec(spec)
    result = render_spec(
        conn,
        home,
        spec,
        out_path,
        force=args.force,
        transparent=args.transparent,
        keep_html=args.keep_html,
        no_record=args.no_record,
        chart_row=chart_row,
        name=default_name,
        base_dir=base_dir,
    )
    payload: Dict[str, Any] = dict(result)
    payload["chart"] = chart_row["name"] if chart_row is not None else None
    payload["recipe"] = "spec" if chart_row is None else "chart"
    if args.register:
        payload["register"] = _register_asset(args, out_path)
    return payload


def cmd_check(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    if args.doc and not args.spec:
        row = conn.execute("SELECT * FROM charts WHERE name = ?", (args.doc,)).fetchone()
        if row is None:
            raise _lib.CommandError("not_found", "no stored chart named %r" % args.doc)
        spec = json.loads(row["spec"])
    else:
        spec = _lib.load_spec(Path(args.spec).expanduser(), _parse_vars(getattr(args, "var", None)))
    spec = _lib.apply_settings(spec, _lib.effective_settings(conn))
    spec, warnings = _lib.validate_spec(spec)
    payload = _html.build_payload(spec)
    result: Dict[str, Any] = {
        "valid": True,
        "spec_version": spec.get("spec_version", _lib.SPEC_VERSION),
        "family": spec["chart"],
        "series": len(payload["series"]),
        "points": len(payload["rows"]) or len(payload["pie"]),
        "width": spec["width"],
        "height": spec["height"],
        "scale": spec["scale"],
        "palette": payload["palette"],
        "theme": spec.get("theme"),
        "layout": payload["layout"],
        "warnings": warnings,
        "strict": bool(args.strict),
    }
    if args.strict:
        dependencies = _lib.dependency_report()
        if dependencies["node"] and dependencies["playwright"]:
            node = shutil.which("node")
            completed = subprocess.run(
                [node, SCREENSHOT_SCRIPT, "--check"], capture_output=True, text=True
            )
            for line in reversed((completed.stdout or "").strip().splitlines()):
                if line.strip().startswith("{"):
                    check_payload = json.loads(line)
                    dependencies["chromium"] = bool((check_payload.get("data") or {}).get("chromium"))
                    break
        result["dependencies"] = dependencies
        result["renderable"] = all(
            dependencies.get(key) for key in ("node", "bundle", "playwright", "chromium")
        )
    return result


def cmd_component(conn: sqlite3.Connection, home: Path, args: argparse.Namespace) -> Dict[str, Any]:
    spec, base_dir, chart_row = _load_spec_for(conn, args)
    spec = _lib.apply_settings(spec, _lib.effective_settings(conn))
    spec, _ = _lib.validate_spec(spec)
    component = _html.build_component(spec, base_dir)
    name = chart_row["name"] if chart_row is not None else Path(args.spec).stem
    if args.out:
        out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(component, encoding="utf-8")
        return {"name": name, "family": spec["chart"], "out": str(out_path), "bytes": out_path.stat().st_size}
    return {"name": name, "family": spec["chart"], "component": component}


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
    name = args.name or "charting-render"
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
            prog="charting",
            service="charting-render.service",
            timer="charting-render.timer",
            plist="com.charting.render.plist",
            add_command=base_command,
            add_note="The render overwrites its output PNG; re-adding is harmless.",
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
            {"step": "post", "description": "Render the chart (overwrites its output PNG)", "command": post_command},
            {"step": "report", "description": "Read the most recent render record (read-only)", "command": report_command_full},
        ],
        "installs_nothing": True,
        "read_only": False,
    }

    if target in ("generic", "claude", "codex", "kilo"):
        base["instructions"] = (
            "Register a recurring task with your host's scheduling mechanism. On each trigger, "
            "run the post command to refresh the PNG, then the report command to summarize what "
            "was produced. The post command only writes its output file."
        )
        base["notes"] = [
            "This target installs nothing; the agent or user registers it.",
            "The render is deterministic for a given spec, so a repeat simply rewrites the file.",
            "The report command is read-only and safe to re-run.",
        ]
        return base

    if target == "nanobot":
        message = "$charting Render the scheduled chart and report the result. Run: " + post_command
        base["message"] = message
        base["cron_tool"] = {"action": "add", "name": name, "message": message, "cron_expr": cron_expr, "tz": tz}
        base["instructions"] = (
            "Create this job with your host's built-in cron tool using the cron_tool fields above. "
            "Create it from a live chat session. Keep cron_expr and tz together."
        )
        base["notes"] = [
            "This is the only target that uses the $charting explicit invocation.",
            "The render overwrites its output file; duplicate fires are harmless.",
        ]
        return base

    if target == "hermes":
        message = "$charting Render the scheduled chart and report the result."
        base["message"] = message
        base["skills"] = ["charting"]
        base["script"] = os.path.join(SKILL_DIR, "scripts", "render.py") + source_flag + out_flag + " --force --quiet --format json"
        base["cron_tool"] = {
            "action": "add", "tool": "cronjob", "name": name, "message": message,
            "cron_expr": cron_expr, "tz": tz, "skills": ["charting"], "script": base["script"],
        }
        base["hermes_cli"] = "hermes cron add --name %s --schedule '%s' --skills charting" % (name, cron_expr)
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
            "[Unit]\nDescription=Render a charting chart\n\n[Service]\nType=oneshot\nExecStart=/bin/sh -c '%s'\n" % post_command
        )
        timer = (
            "[Unit]\nDescription=Recurring charting render\n\n[Timer]\n"
            "OnCalendar=*-*-* %02d:%02d:00\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n" % (hour, minute)
        )
        base["install"] = {
            "type": "systemd",
            "files": {"charting-render.service": service, "charting-render.timer": timer},
            "commands": ["systemctl --user daemon-reload", "systemctl --user enable --now charting-render.timer"],
        }
        base["instructions"] = "Write both files to ~/.config/systemd/user/, then run the install commands."
        return base

    plist = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n<dict>\n  <key>Label</key>\n  <string>com.charting.render</string>\n'
        "  <key>ProgramArguments</key>\n  <array>\n    <string>/bin/sh</string>\n    <string>-c</string>\n"
        "    <string>%s</string>\n  </array>\n  <key>StartCalendarInterval</key>\n  <dict>\n"
        "    <key>Hour</key>\n    <integer>%d</integer>\n    <key>Minute</key>\n    <integer>%d</integer>\n"
        "  </dict>\n</dict>\n</plist>\n" % (_xml_escape(post_command), hour, minute)
    )
    base["install"] = {
        "type": "launchd",
        "files": {"com.charting.render.plist": plist},
        "commands": [
            "cp com.charting.render.plist ~/Library/LaunchAgents/",
            "launchctl load ~/Library/LaunchAgents/com.charting.render.plist",
        ],
    }
    base["instructions"] = "Copy the plist to ~/Library/LaunchAgents/ and load it. Remove it with launchctl unload and rm."
    return base


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _add_render_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--doc", help="name of a stored chart")
    parser.add_argument("--spec", help="path to a JSON spec file")
    parser.add_argument("--var", action="append", metavar="NAME=VALUE", help="substitute {{NAME}} in the spec; repeatable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="render.py", description="Render chart specs to PNG.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="render a chart or spec to PNG", parents=[_lib.common_parser()])
    _add_render_inputs(render)
    render.add_argument("--out", help="output PNG path (default: <home>/output/<name>.png)")
    render.add_argument("--scale", type=int, help="device scale factor override (1-4)")
    render.add_argument("--theme", choices=list(_lib.THEMES), help="theme override")
    render.add_argument("--transparent", action="store_true", help="force a transparent background")
    render.add_argument("--register", action="store_true", help="also copy the PNG into the pdf-creator asset store")
    render.add_argument("--pdf-home", help="pdf-creator data root for --register")
    render.add_argument("--force", action="store_true", help="overwrite an existing output file")
    render.add_argument("--keep-html", action="store_true", help="keep the generated HTML in <home>/tmp")
    render.add_argument("--no-record", action="store_true", help="do not write a render-history row")
    render.set_defaults(func=cmd_render)

    check = subparsers.add_parser("check", help="validate a spec without rendering", parents=[_lib.common_parser()])
    _add_render_inputs(check)
    check.add_argument("--strict", action="store_true", help="also verify Node, the bundle, and Chromium")
    check.set_defaults(func=cmd_check)

    component = subparsers.add_parser("component", help="emit the equivalent shadcn/Recharts JSX", parents=[_lib.common_parser()])
    _add_render_inputs(component)
    component.add_argument("--out", help="write the JSX to this path instead of printing")
    component.set_defaults(func=cmd_component)

    hint = subparsers.add_parser("schedule-hint", help="emit a scheduler artifact", parents=[_lib.common_parser()])
    _add_render_inputs(hint)
    hint.add_argument("--out", help="output PNG path for the scheduled render")
    hint.add_argument("--target", choices=list(SCHEDULE_TARGETS), default="generic")
    hint.add_argument("--path-mode", choices=("abs", "relative", "skill"))
    hint.add_argument("--at-time", default="08:00", help="daily trigger time, HH:MM (default 08:00)")
    hint.add_argument("--name", help="job name for agent targets")
    _lib.add_action_flags(hint)
    hint.set_defaults(func=cmd_schedule_hint)
    return parser


if __name__ == "__main__":
    _lib.run_script("render", build_parser())
