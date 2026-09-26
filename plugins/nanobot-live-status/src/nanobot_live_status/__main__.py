"""Diagnostics CLI: ``python -m nanobot_live_status`` / ``nanobot-live-status``.

Nothing here prints the Telegram token; only whether it is configured.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__
from .phrases import ThinkingPhrases


def _import_nanobot() -> tuple[str | None, str | None]:
    try:
        import nanobot
    except Exception as exc:
        return None, type(exc).__name__
    return str(getattr(nanobot, "__version__", "unknown")), None


def _entry_points() -> list[str]:
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - stdlib always present
        return []
    try:
        eps = entry_points(group="nanobot.tools")
    except Exception:
        return []
    return sorted(ep.name for ep in eps)


def _telegram_configured() -> bool | None:
    try:
        from nanobot.config.loader import load_config
    except Exception:
        return None
    try:
        config = load_config()
    except Exception:
        return None
    channels = getattr(config, "channels", None)
    telegram = getattr(channels, "telegram", None)
    if telegram is None:
        return False
    if isinstance(telegram, dict):
        return bool(telegram.get("enabled")) and bool(telegram.get("token"))
    return bool(getattr(telegram, "enabled", False)) and bool(getattr(telegram, "token", None))


def _runtime_events_available() -> bool:
    try:
        from nanobot.bus import runtime_events  # noqa: F401
    except Exception:
        return False
    return True


def cmd_doctor(args: argparse.Namespace) -> int:
    del args
    print(f"nanobot-live-status {__version__}")

    nanobot_version, import_error = _import_nanobot()
    if nanobot_version is None:
        print(f"nanobot: NOT importable ({import_error})")
        print("  run this from nanobot's own environment, e.g.:")
        print('    "$(uv tool dir)/nanobot-ai/bin/nanobot-live-status" doctor')
    else:
        print(f"nanobot: {nanobot_version}")
        print(f"runtime events importable: {'yes' if _runtime_events_available() else 'no'}")
        configured = _telegram_configured()
        if configured is None:
            print("telegram configured: unknown (config not loadable)")
        else:
            print(f"telegram configured: {'yes' if configured else 'no'}")

    names = _entry_points()
    print(f"nanobot.tools entry points: {', '.join(names) if names else '(none)'}")
    print(f"live_status registered: {'yes' if 'live_status' in names else 'no'}")
    return 0


def cmd_phrases(args: argparse.Namespace) -> int:
    source = ThinkingPhrases()
    count = max(1, args.count)
    for _ in range(count):
        print(source.next())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nanobot-live-status",
        description="Rotating live-status middleware plugin for nanobot.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    doctor = sub.add_parser("doctor", help="show plugin/host diagnostics")
    doctor.set_defaults(func=cmd_doctor)

    phrases = sub.add_parser("phrases", help="print sample status phrases")
    phrases.add_argument("-n", "--count", type=int, default=10, help="how many to print")
    phrases.set_defaults(func=cmd_phrases)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return int(func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
