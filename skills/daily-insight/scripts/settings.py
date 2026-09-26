#!/usr/bin/env python3
"""Read and change daily-insight settings.

Secrets are never stored or echoed: the API-key settings hold *environment
variable names* only, and the actual key material is read from the environment
when a remote call is made.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from typing import Any, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lib  # noqa: E402


def _counts(conn: sqlite3.Connection) -> Dict[str, int]:
    tables = ("materials", "chunks", "day_slots", "deliveries")
    counts = {}
    for table in tables:
        counts[table] = conn.execute("SELECT COUNT(*) AS n FROM %s" % table).fetchone()["n"]
    return counts


def _public_settings(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Effective settings: host env override first, then the stored value."""
    eff = _lib.effective_setting
    return {
        "budget": _lib.setting_int(conn, "budget", _lib.DEFAULT_BUDGET),
        "wake": eff(conn, "wake"),
        "tz": eff(conn, "tz"),
        "strategy": eff(conn, "strategy"),
        "embed_mode": eff(conn, "embed_mode"),
        "embed_provider": eff(conn, "embed_provider"),
        "embed_base_url": eff(conn, "embed_base_url"),
        "embed_model": eff(conn, "embed_model"),
        "embed_api_key_env": eff(conn, "embed_api_key_env"),
        "embed_dim": _lib.setting_int(conn, "embed_dim", _lib.DEFAULT_EMBED_DIM),
        "chat_provider": eff(conn, "chat_provider"),
        "chat_base_url": eff(conn, "chat_base_url"),
        "chat_model": eff(conn, "chat_model"),
        "chat_api_key_env": eff(conn, "chat_api_key_env"),
        "cooldown_days": _lib.setting_int(conn, "cooldown_days", _lib.DEFAULT_COOLDOWN_DAYS),
        "chunk_size": _lib.setting_int(conn, "chunk_size", _lib.DEFAULT_CHUNK_SIZE),
        "chunk_overlap": _lib.setting_int(conn, "chunk_overlap", _lib.DEFAULT_CHUNK_OVERLAP),
        "dedup_threshold": _lib.setting_float(conn, "dedup_threshold", _lib.DEFAULT_DEDUP_THRESHOLD),
    }


def _api_key_available(conn: sqlite3.Connection, setting_key: str, fallback: str) -> bool:
    env_name = _lib.effective_setting(conn, setting_key) or fallback
    return bool(os.environ.get(env_name))


def cmd_show(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    deps = _lib.deps_status()
    values = _public_settings(conn)
    return {
        "home": str(home),
        "db": str(_lib.resolve_db_path(home)),
        "chroma": str(_lib.resolve_chroma_path(home)),
        "schema_version": conn.execute("PRAGMA user_version").fetchone()[0],
        "initialized": _lib.get_meta(conn, "initialized") == "1",
        "settings": values,
        "embedding_configured": (
            values["embed_mode"] == "hash"
            or bool(values["embed_model"] and values["embed_provider"] == "openai")
        ),
        "embedding_key_available": _api_key_available(
            conn, "embed_api_key_env", _lib.DEFAULT_EMBED_API_KEY_ENV
        ),
        "generate_configured": bool(values["chat_model"]),
        "generate_key_available": _api_key_available(
            conn, "chat_api_key_env", _lib.DEFAULT_CHAT_API_KEY_ENV
        ),
        "env_overrides": _lib.active_env_overrides(),
        "dependencies": deps,
        "counts": _counts(conn),
    }


def cmd_get(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    if not args.key:
        return {
            "home": str(home),
            "db": str(_lib.resolve_db_path(home)),
            "settings": _public_settings(conn),
        }
    key = args.key.strip()
    if key in ("home", "data_home"):
        return {"key": "home", "value": str(home)}
    if key in ("db", "db_path"):
        return {"key": "db", "value": str(_lib.resolve_db_path(home))}
    if key in ("chroma", "chroma_path"):
        return {"key": "chroma", "value": str(_lib.resolve_chroma_path(home))}
    if key in ("schema_version", "user_version"):
        return {"key": "schema_version", "value": conn.execute("PRAGMA user_version").fetchone()[0]}
    if key in ("initialized",):
        return {"key": "initialized", "value": _lib.get_meta(conn, "initialized") == "1"}
    values = _public_settings(conn)
    if key in values:
        return {"key": key, "value": values[key]}
    raise _lib.CommandError("not_found", "no setting named %r" % key)


def _validate_positive_int(value: int, field: str, minimum: int = 0) -> int:
    if value < minimum:
        raise _lib.CommandError("invalid_input", "%s must be %d or greater" % (field, minimum))
    return value


def cmd_set(conn: sqlite3.Connection, home, args: argparse.Namespace) -> Dict[str, Any]:
    updates: Dict[str, Tuple[str, Any]] = {}

    if args.budget is not None:
        updates["budget"] = ("budget", _validate_positive_int(args.budget, "--budget", 0))
    if args.wake is not None:
        _lib.parse_wake(args.wake)
        updates["wake"] = ("wake", args.wake.strip())
    if args.strategy is not None:
        if args.strategy not in _lib.STRATEGIES:
            raise _lib.CommandError("invalid_input", "--strategy must be one of: %s" % ", ".join(_lib.STRATEGIES))
        updates["strategy"] = ("strategy", args.strategy)
    if args.tz is not None:
        _lib.tzinfo_for(args.tz)
        updates["tz"] = ("tz", args.tz.strip())
    if args.embed_base_url is not None:
        updates["embed_base_url"] = ("embed_base_url", args.embed_base_url.strip())
    if args.embed_model is not None:
        updates["embed_model"] = ("embed_model", args.embed_model.strip())
    if args.embed_mode is not None:
        if args.embed_mode not in _lib.EMBED_MODES:
            raise _lib.CommandError("invalid_input", "--embed-mode must be one of: %s" % ", ".join(_lib.EMBED_MODES))
        updates["embed_mode"] = ("embed_mode", args.embed_mode)
    if args.embed_provider is not None:
        if args.embed_provider not in _lib.EMBED_PROVIDERS:
            raise _lib.CommandError(
                "invalid_input",
                "embeddings support only the OpenAI-compatible API (got %r); Anthropic "
                "has no embeddings endpoint" % args.embed_provider,
            )
        updates["embed_provider"] = ("embed_provider", args.embed_provider)
    if args.chat_provider is not None:
        if args.chat_provider not in _lib.CHAT_PROVIDERS:
            raise _lib.CommandError(
                "invalid_input", "--chat-provider must be one of: %s" % ", ".join(_lib.CHAT_PROVIDERS)
            )
        updates["chat_provider"] = ("chat_provider", args.chat_provider)
    if args.embed_api_key_env is not None:
        updates["embed_api_key_env"] = ("embed_api_key_env", args.embed_api_key_env.strip())
    if args.embed_dim is not None:
        updates["embed_dim"] = ("embed_dim", _validate_positive_int(args.embed_dim, "--embed-dim", 8))
    if args.chat_base_url is not None:
        updates["chat_base_url"] = ("chat_base_url", args.chat_base_url.strip())
    if args.chat_model is not None:
        updates["chat_model"] = ("chat_model", args.chat_model.strip())
    if args.chat_api_key_env is not None:
        updates["chat_api_key_env"] = ("chat_api_key_env", args.chat_api_key_env.strip())
    if args.cooldown_days is not None:
        updates["cooldown_days"] = (
            "cooldown_days",
            _validate_positive_int(args.cooldown_days, "--cooldown-days", 0),
        )
    if args.chunk_size is not None:
        updates["chunk_size"] = ("chunk_size", _validate_positive_int(args.chunk_size, "--chunk-size", 20))
    if args.chunk_overlap is not None:
        updates["chunk_overlap"] = (
            "chunk_overlap",
            _validate_positive_int(args.chunk_overlap, "--chunk-overlap", 0),
        )
    if args.dedup_threshold is not None:
        if not (0.0 <= args.dedup_threshold <= 1.0):
            raise _lib.CommandError("invalid_input", "--dedup-threshold must be between 0 and 1")
        updates["dedup_threshold"] = ("dedup_threshold", args.dedup_threshold)

    if not updates:
        raise _lib.CommandError(
            "usage",
            "set needs at least one setting, e.g. settings.py set --budget 5 --wake 08:00-22:00",
        )

    changed: Dict[str, Any] = {}
    for key, (meta_key, value) in updates.items():
        previous = _lib.get_setting(conn, meta_key)
        _lib.set_meta(conn, meta_key, value)
        changed[key] = {"previous": previous, "value": value}
    _lib.set_meta(conn, "initialized", "1")

    return {
        "changed": changed,
        "settings": _public_settings(conn),
        "note": "Settings are stored in the data root; namespaced host env vars "
                "(DAILY_INSIGHT_*) override them per call. API keys are read from the "
                "environment named by *_api_key_env; no secret is stored.",
    }


def build_parser() -> argparse.ArgumentParser:
    common = _lib.common_parser()
    parser = argparse.ArgumentParser(
        prog="settings.py", description="Show or change daily-insight settings."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser(
        "show", help="show settings, paths, and row counts", parents=[common],
        description="Show resolved paths, settings, dependency status, and counts.",
    )
    show.set_defaults(func=cmd_show, verb="show")

    get = subparsers.add_parser(
        "get", help="read one setting or all settings", parents=[common],
        description="Read a single setting value or the whole settings snapshot.",
    )
    get.add_argument("--key", help="setting name, e.g. budget")
    get.set_defaults(func=cmd_get, verb="get")

    set_cmd = subparsers.add_parser(
        "set", help="change one or more settings", parents=[common],
        description="Change daily-insight settings (budget, wake window, endpoints, chunking).",
    )
    set_cmd.add_argument("--budget", type=int, help="global daily insight budget")
    set_cmd.add_argument("--wake", help="wake window HH:MM-HH:MM")
    set_cmd.add_argument("--strategy", choices=list(_lib.STRATEGIES))
    set_cmd.add_argument("--embed-provider", choices=list(_lib.EMBED_PROVIDERS))
    set_cmd.add_argument("--embed-base-url")
    set_cmd.add_argument("--embed-model")
    set_cmd.add_argument("--embed-mode", choices=list(_lib.EMBED_MODES))
    set_cmd.add_argument("--embed-api-key-env", help="env var name holding the embedding key")
    set_cmd.add_argument("--embed-dim", type=int, help="dimension for the hash embedder")
    set_cmd.add_argument("--chat-provider", choices=list(_lib.CHAT_PROVIDERS))
    set_cmd.add_argument("--chat-base-url")
    set_cmd.add_argument("--chat-model")
    set_cmd.add_argument("--chat-api-key-env", help="env var name holding the chat key")
    set_cmd.add_argument("--cooldown-days", type=int)
    set_cmd.add_argument("--chunk-size", type=int)
    set_cmd.add_argument("--chunk-overlap", type=int)
    set_cmd.add_argument("--dedup-threshold", type=float)
    set_cmd.set_defaults(func=cmd_set, verb="set")

    return parser


def main() -> None:
    _lib.run_script("settings", build_parser())


if __name__ == "__main__":
    main()
