#!/usr/bin/env python3
"""Shared helpers for the daily-insight skill scripts.

This module is NOT an entry point. Domain scripts import it directly
(``import _lib``) because Python places the script's own directory on
``sys.path[0]``.

Only the standard library is imported at module load. The heavy optional
dependencies (``chromadb``, ``pypdf``, ``python-docx``) are imported lazily so
that the read-only reporting verbs keep working on a host that has a data root
but none of the optional packages installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DEFAULT_HOME_DIR = "~/.local/share/daily-insight"
DEFAULT_DB_NAME = "daily-insight.db"
CHROMA_DIR_NAME = "chroma"
OUTBOX_DIR_NAME = "outbox"
COLLECTION_NAME = "chunks"
SCHEMA_VERSION = 1

PERIODS = ("day", "week")
STRATEGIES = ("coverage", "similarity", "random")
EMBED_MODES = ("hash", "remote")
# "openai" means any OpenAI-compatible API (OpenAI, OpenRouter, vLLM, ...).
# Anthropic is supported for chat/generation only: Anthropic has no embeddings API.
API_PROVIDERS = ("openai", "anthropic")
EMBED_PROVIDERS = ("openai",)
CHAT_PROVIDERS = ("openai", "anthropic")
DEFAULT_EMBED_PROVIDER = "openai"
DEFAULT_CHAT_PROVIDER = "openai"
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_MAX_TOKENS = 700

DEFAULT_BUDGET = 5
DEFAULT_WAKE = "08:00-22:00"
DEFAULT_TZ = "UTC"
DEFAULT_STRATEGY = "coverage"
DEFAULT_EMBED_MODE = "hash"
DEFAULT_EMBED_DIM = 256
DEFAULT_EMBED_API_KEY_ENV = "DAILY_INSIGHT_EMBED_API_KEY"
DEFAULT_CHAT_API_KEY_ENV = "DAILY_INSIGHT_CHAT_API_KEY"
DEFAULT_COOLDOWN_DAYS = 30
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_DEDUP_THRESHOLD = 0.92
DEDUP_RECENT = 10
RELATED_COUNT = 4

# meta defaults; every setting is stored as text in the meta table.
SETTING_DEFAULTS: Dict[str, str] = {
    "budget": str(DEFAULT_BUDGET),
    "wake": DEFAULT_WAKE,
    "tz": DEFAULT_TZ,
    "strategy": DEFAULT_STRATEGY,
    "embed_mode": DEFAULT_EMBED_MODE,
    "embed_provider": DEFAULT_EMBED_PROVIDER,
    "embed_base_url": "",
    "embed_model": "",
    "embed_api_key_env": DEFAULT_EMBED_API_KEY_ENV,
    "embed_dim": str(DEFAULT_EMBED_DIM),
    "chat_provider": DEFAULT_CHAT_PROVIDER,
    "chat_base_url": "",
    "chat_model": "",
    "chat_api_key_env": DEFAULT_CHAT_API_KEY_ENV,
    "cooldown_days": str(DEFAULT_COOLDOWN_DAYS),
    "chunk_size": str(DEFAULT_CHUNK_SIZE),
    "chunk_overlap": str(DEFAULT_CHUNK_OVERLAP),
    "dedup_threshold": str(DEFAULT_DEDUP_THRESHOLD),
}

SECRET_SETTING_KEYS = ()  # settings only ever hold env-var *names*, never secrets

# Namespaced host environment overrides. A set variable wins over the stored
# setting for that call; the skill reads its configuration entirely from the
# host environment (or the data-root settings), never from another app's config.
ENV_OVERRIDES: Dict[str, str] = {
    "budget": "DAILY_INSIGHT_BUDGET",
    "wake": "DAILY_INSIGHT_WAKE",
    "tz": "DAILY_INSIGHT_TZ",
    "strategy": "DAILY_INSIGHT_STRATEGY",
    "cooldown_days": "DAILY_INSIGHT_COOLDOWN_DAYS",
    "chunk_size": "DAILY_INSIGHT_CHUNK_SIZE",
    "chunk_overlap": "DAILY_INSIGHT_CHUNK_OVERLAP",
    "dedup_threshold": "DAILY_INSIGHT_DEDUP_THRESHOLD",
    "embed_mode": "DAILY_INSIGHT_EMBED_MODE",
    "embed_provider": "DAILY_INSIGHT_EMBED_PROVIDER",
    "embed_base_url": "DAILY_INSIGHT_EMBED_BASE_URL",
    "embed_model": "DAILY_INSIGHT_EMBED_MODEL",
    "embed_api_key_env": "DAILY_INSIGHT_EMBED_API_KEY_ENV",
    "embed_dim": "DAILY_INSIGHT_EMBED_DIM",
    "chat_provider": "DAILY_INSIGHT_CHAT_PROVIDER",
    "chat_base_url": "DAILY_INSIGHT_CHAT_BASE_URL",
    "chat_model": "DAILY_INSIGHT_CHAT_MODEL",
    "chat_api_key_env": "DAILY_INSIGHT_CHAT_API_KEY_ENV",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS materials (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL UNIQUE,
    source_path    TEXT,
    source_hash    TEXT,
    cadence_count  INTEGER NOT NULL DEFAULT 1,
    cadence_period TEXT NOT NULL DEFAULT 'day'
                     CHECK (cadence_period IN ('day','week')),
    priority       INTEGER NOT NULL DEFAULT 100,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    chunk_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS chunks (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id        INTEGER NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
    ordinal            INTEGER NOT NULL,
    text               TEXT NOT NULL,
    token_est          INTEGER NOT NULL DEFAULT 0,
    text_hash          TEXT NOT NULL,
    delivered_count    INTEGER NOT NULL DEFAULT 0,
    last_delivered_at  TEXT,
    UNIQUE (material_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_chunks_material ON chunks(material_id);
CREATE INDEX IF NOT EXISTS idx_chunks_last_delivered ON chunks(last_delivered_at);
CREATE INDEX IF NOT EXISTS idx_chunks_text_hash ON chunks(text_hash);

CREATE TABLE IF NOT EXISTS day_slots (
    date         TEXT NOT NULL,
    slot_index   INTEGER NOT NULL,
    material_id  INTEGER NOT NULL REFERENCES materials(id),
    due_at       TEXT,
    status       TEXT NOT NULL DEFAULT 'planned'
                   CHECK (status IN ('planned','delivered','skipped')),
    chunk_id     INTEGER REFERENCES chunks(id),
    delivered_at TEXT,
    generated    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, slot_index)
);

CREATE TABLE IF NOT EXISTS deliveries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT NOT NULL,
    slot_index   INTEGER NOT NULL,
    material_id  INTEGER NOT NULL REFERENCES materials(id),
    chunk_id     INTEGER REFERENCES chunks(id),
    delivered_at TEXT,
    generated    INTEGER NOT NULL DEFAULT 0,
    insight_text TEXT,
    UNIQUE (date, slot_index)
);

CREATE INDEX IF NOT EXISTS idx_deliveries_date ON deliveries(date);
CREATE INDEX IF NOT EXISTS idx_deliveries_material ON deliveries(material_id);
"""


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
    elif os.environ.get("DAILY_INSIGHT_HOME"):
        raw = os.environ["DAILY_INSIGHT_HOME"]
    else:
        raw = DEFAULT_HOME_DIR
    return Path(os.path.expanduser(raw))


def resolve_db_path(home: Path) -> Path:
    return Path(home) / DEFAULT_DB_NAME


def resolve_chroma_path(home: Path) -> Path:
    return Path(home) / CHROMA_DIR_NAME


def resolve_outbox_path(home: Path) -> Path:
    return Path(home) / OUTBOX_DIR_NAME


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
    """The stored setting, unless a namespaced host env var overrides it."""
    env_name = ENV_OVERRIDES.get(key)
    if env_name:
        value = os.environ.get(env_name)
        if value is not None and value.strip() != "":
            return value
    return get_setting(conn, key)


def active_env_overrides() -> Dict[str, str]:
    """Setting keys currently overridden by the host environment (no secrets)."""
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


def setting_float(conn: sqlite3.Connection, key: str, default: float = 0.0) -> float:
    raw = effective_setting(conn, key)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return float(default)


def settings_snapshot(conn: sqlite3.Connection) -> Dict[str, str]:
    snapshot = dict(SETTING_DEFAULTS)
    for row in conn.execute("SELECT key, value FROM meta"):
        snapshot[row["key"]] = row["value"]
    return snapshot


# ---------------------------------------------------------------------------
# Hashing / chunking
# ---------------------------------------------------------------------------

def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def stable_int(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(), 16)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _split_long(paragraph: str, size: int, overlap: int) -> List[str]:
    words = paragraph.split()
    pieces: List[str] = []
    current: List[str] = []
    length = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and length + extra > size:
            pieces.append(" ".join(current))
            tail: List[str] = []
            tail_len = 0
            if overlap > 0:
                for w in reversed(current):
                    if tail_len + len(w) + 1 > overlap:
                        break
                    tail.insert(0, w)
                    tail_len += len(w) + 1
            current = list(tail)
            length = sum(len(w) + 1 for w in current)
        current.append(word)
        length += extra
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk_text(text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> List[str]:
    """Split text into deterministic, roughly ``size``-char chunks.

    Paragraph boundaries are preferred; a paragraph longer than ``size`` is
    split on word boundaries with ``overlap`` characters of carry-over.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    size = max(20, int(size))
    overlap = max(0, min(int(overlap), size // 2))
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    chunks: List[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current.strip():
            chunks.append(current.strip())
        current = ""

    for paragraph in paragraphs:
        if len(paragraph) > size:
            flush()
            for piece in _split_long(paragraph, size, overlap):
                if len(piece) <= size:
                    chunks.append(piece)
                else:
                    for start in range(0, len(piece), max(1, size - overlap)):
                        chunks.append(piece[start:start + size])
            continue
        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= size:
            current = current + "\n\n" + paragraph
        else:
            carry = overlap_from_tail(current, overlap)
            flush()
            current = (carry + "\n\n" + paragraph).strip() if carry else paragraph
    flush()
    if not chunks and normalized:
        chunks = [normalized[:size]]
    return chunks


def overlap_from_tail(text: str, overlap: int) -> str:
    if overlap <= 0:
        return ""
    tail = text[-overlap:]
    space = tail.find(" ")
    if space > 0:
        tail = tail[space + 1:]
    return tail.strip()


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def hash_embed(texts: Sequence[str], dim: int = DEFAULT_EMBED_DIM) -> List[List[float]]:
    """A deterministic, offline bag-of-token embedder for tests and small hosts."""
    dim = max(8, int(dim))
    vectors: List[List[float]] = []
    for text in texts:
        vec = [0.0] * dim
        for token in re.findall(r"[a-z0-9]+", (text or "").lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            vec[0] = 1.0
            norm = 1.0
        vectors.append([v / norm for v in vec])
    return vectors


def _endpoint(base_url: str, suffix: str) -> str:
    return "%s/%s" % (base_url.rstrip("/"), suffix.lstrip("/"))


def provider_base(provider: str) -> str:
    return DEFAULT_ANTHROPIC_BASE if provider == "anthropic" else DEFAULT_OPENAI_BASE


def _post_json(
    url: str,
    payload: Dict[str, Any],
    api_key: Optional[str],
    error_code: str,
    extra_headers: Optional[Dict[str, str]] = None,
    bearer_auth: bool = True,
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    if api_key and bearer_auth:
        headers["Authorization"] = "Bearer %s" % api_key
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise CommandError(error_code, "endpoint returned HTTP %s for %s" % (exc.code, url))
    except urllib.error.URLError as exc:
        raise CommandError(error_code, "could not reach endpoint %s: %s" % (url, exc.reason))
    except TimeoutError:
        raise CommandError(error_code, "timed out calling %s" % url)
    try:
        return json.loads(raw)
    except ValueError:
        raise CommandError(error_code, "endpoint returned invalid JSON from %s" % url)


def _api_key_for(conn: sqlite3.Connection, key_env_name: str, fallback_key: str) -> Optional[str]:
    """Read key material from the host environment only (never from storage)."""
    env_name = effective_setting(conn, key_env_name) or fallback_key
    return os.environ.get(env_name) or None


def embed_texts(conn: sqlite3.Connection, texts: Sequence[str]) -> List[List[float]]:
    """Embed texts with the configured backend (``hash`` offline or ``remote``)."""
    texts = list(texts)
    if not texts:
        return []
    mode = effective_setting(conn, "embed_mode") or DEFAULT_EMBED_MODE
    if mode == "hash":
        return hash_embed(texts, setting_int(conn, "embed_dim", DEFAULT_EMBED_DIM))
    if mode != "remote":
        raise CommandError("invalid_input", "unknown embed mode %r" % mode)
    provider = effective_setting(conn, "embed_provider") or DEFAULT_EMBED_PROVIDER
    if provider not in EMBED_PROVIDERS:
        raise CommandError(
            "embedding_not_configured",
            "embeddings support the OpenAI-compatible API only (Anthropic has no "
            "embeddings endpoint); set --embed-provider openai and point "
            "--embed-base-url at an OpenAI-compatible service",
        )
    base_url = effective_setting(conn, "embed_base_url") or provider_base(provider)
    model = effective_setting(conn, "embed_model")
    if not model:
        raise CommandError(
            "embedding_not_configured",
            "remote embeddings need --embed-model (or switch to --embed-mode hash); "
            "run settings.py show",
        )
    api_key = _api_key_for(conn, "embed_api_key_env", DEFAULT_EMBED_API_KEY_ENV)
    vectors: List[List[float]] = []
    batch = 64
    for start in range(0, len(texts), batch):
        window = texts[start:start + batch]
        payload = {"model": model, "input": window}
        response = _post_json(_endpoint(base_url, "embeddings"), payload, api_key, "embedding_error")
        data = response.get("data")
        if not isinstance(data, list) or len(data) != len(window):
            raise CommandError("embedding_error", "embedding response shape was unexpected")
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        for item in ordered:
            vector = item.get("embedding")
            if not isinstance(vector, list):
                raise CommandError("embedding_error", "embedding response item had no vector")
            vectors.append([float(v) for v in vector])
    return vectors


def generate_text(
    conn: sqlite3.Connection,
    prompt: str,
    system: Optional[str] = None,
) -> str:
    """Call the configured chat endpoint (OpenAI- or Anthropic-compatible)."""
    provider = effective_setting(conn, "chat_provider") or DEFAULT_CHAT_PROVIDER
    if provider not in CHAT_PROVIDERS:
        raise CommandError("generate_error", "unknown chat provider %r" % provider)
    base_url = effective_setting(conn, "chat_base_url") or provider_base(provider)
    model = effective_setting(conn, "chat_model")
    if not model:
        raise CommandError(
            "generate_error",
            "no chat model configured; set --chat-model to use --generate",
        )
    api_key = _api_key_for(conn, "chat_api_key_env", DEFAULT_CHAT_API_KEY_ENV)

    if provider == "anthropic":
        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": ANTHROPIC_MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        headers = {"anthropic-version": ANTHROPIC_VERSION}
        if api_key:
            headers["x-api-key"] = api_key
        response = _post_json(
            _endpoint(base_url, "messages"),
            payload,
            api_key,
            "generate_error",
            extra_headers=headers,
            bearer_auth=False,
        )
        blocks = response.get("content")
        if not isinstance(blocks, list):
            raise CommandError("generate_error", "chat response contained no content")
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text.strip():
            raise CommandError("generate_error", "chat response contained no text")
        return text.strip()

    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages, "temperature": 0.4}
    response = _post_json(
        _endpoint(base_url, "chat/completions"), payload, api_key, "generate_error"
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise CommandError("generate_error", "chat response contained no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise CommandError("generate_error", "chat response contained no text")
    return content.strip()


# ---------------------------------------------------------------------------
# Optional dependency loading + Chroma
# ---------------------------------------------------------------------------

def deps_status() -> Dict[str, bool]:
    status: Dict[str, bool] = {}
    for module in ("chromadb", "pypdf", "docx"):
        try:
            __import__(module)
            status[module] = True
        except Exception:
            status[module] = False
    return status


def load_chromadb() -> Tuple[Any, Any]:
    try:
        import chromadb  # type: ignore
        from chromadb.config import Settings  # type: ignore
        return chromadb, Settings
    except Exception:
        return None, None


def open_collection(home: Path) -> Any:
    """Open (creating if needed) the persistent ``chunks`` collection."""
    chromadb, settings_cls = load_chromadb()
    if chromadb is None:
        raise CommandError(
            "dependency_missing",
            "the vector store needs the optional dependencies: "
            "pip install -r requirements.txt",
        )
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "False")
    path = resolve_chroma_path(home)
    path.mkdir(parents=True, exist_ok=True)
    try:
        client = chromadb.PersistentClient(
            path=str(path),
            settings=settings_cls(anonymized_telemetry=False, allow_reset=True),
        )
        collection = client.get_or_create_collection(
            COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )
    except CommandError:
        raise
    except Exception as exc:  # pragma: no cover - depends on chromadb internals
        raise CommandError("vector_store_error", "could not open the vector store: %s" % exc)
    return collection


def chroma_ids(material_id: int, ordinals: Iterable[int]) -> List[str]:
    return ["%d:%d" % (int(material_id), int(o)) for o in ordinals]


def chroma_add(
    collection: Any,
    material_id: int,
    ordinals: Sequence[int],
    texts: Sequence[str],
    embeddings: Sequence[Sequence[float]],
    text_hashes: Sequence[str],
) -> int:
    if not ordinals:
        return 0
    try:
        collection.add(
            ids=chroma_ids(material_id, ordinals),
            embeddings=[list(v) for v in embeddings],
            documents=list(texts),
            metadatas=[
                {"material_id": int(material_id), "ordinal": int(o), "text_hash": h}
                for o, h in zip(ordinals, text_hashes)
            ],
        )
    except Exception as exc:  # pragma: no cover
        raise CommandError("vector_store_error", "could not write vectors: %s" % exc)
    return len(ordinals)


def chroma_delete_material(collection: Any, material_id: int) -> None:
    try:
        collection.delete(where={"material_id": int(material_id)})
    except Exception as exc:  # pragma: no cover
        raise CommandError("vector_store_error", "could not delete vectors: %s" % exc)


def chroma_get_embeddings(collection: Any, ids: Sequence[str]) -> Dict[str, List[float]]:
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        return {}
    try:
        got = collection.get(ids=unique_ids, include=["embeddings"])
    except Exception as exc:  # pragma: no cover
        raise CommandError("vector_store_error", "could not read vectors: %s" % exc)
    result: Dict[str, List[float]] = {}
    got_ids = got.get("ids") or []
    got_vectors = got.get("embeddings")
    if got_vectors is None:
        return result
    for ident, vector in zip(got_ids, got_vectors):
        if vector is not None:
            result[ident] = [float(v) for v in vector]
    return result


def chroma_query(
    collection: Any,
    embedding: Sequence[float],
    material_id: int,
    n_results: int = 5,
) -> List[Tuple[str, float]]:
    try:
        result = collection.query(
            query_embeddings=[list(embedding)],
            n_results=max(1, int(n_results)),
            where={"material_id": int(material_id)},
        )
    except Exception as exc:  # pragma: no cover
        raise CommandError("vector_store_error", "could not query vectors: %s" % exc)
    ids = (result.get("ids") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    out: List[Tuple[str, float]] = []
    for ident, distance in zip(ids, distances):
        score = 1.0 - float(distance)
        out.append((ident, score))
    return out


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


# ---------------------------------------------------------------------------
# Dates, times, and the day plan
# ---------------------------------------------------------------------------

def validate_date(value: str, field: str = "date") -> str:
    text = (value or "").strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise CommandError("invalid_date", "invalid %s %r, expected YYYY-MM-DD" % (field, value))


def parse_hhmm(value: str, field: str = "time") -> int:
    text = (value or "").strip()
    parts = text.split(":")
    if len(parts) != 2:
        raise CommandError("invalid_input", "invalid %s %r, expected HH:MM" % (field, value))
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise CommandError("invalid_input", "invalid %s %r, expected HH:MM" % (field, value))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise CommandError("invalid_input", "invalid %s %r, expected a 24-hour time" % (field, value))
    return hour * 60 + minute


def fmt_hhmm(minutes: int) -> str:
    minutes = int(minutes) % (24 * 60)
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def parse_wake(value: str) -> Tuple[int, int]:
    text = (value or "").strip()
    if "-" not in text:
        raise CommandError("invalid_input", "wake window must look like 08:00-22:00")
    left, right = text.split("-", 1)
    start = parse_hhmm(left, "wake start")
    end = parse_hhmm(right, "wake end")
    if end <= start:
        raise CommandError("invalid_input", "wake end must be after wake start")
    return start, end


def spread_times(start: int, end: int, count: int) -> List[str]:
    if count <= 0:
        return []
    if count == 1:
        return [fmt_hhmm(start)]
    step = (end - start) / float(count - 1)
    return [fmt_hhmm(int(round(start + step * i))) for i in range(count)]


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
    tz_name = getattr(args, "tz", None) or get_setting(conn, "tz") or DEFAULT_TZ
    return now_local(tz_name).date()


def weekly_weekdays(material_id: int, count: int) -> List[int]:
    count = max(1, min(7, int(count)))
    offset = stable_int("week:%d" % int(material_id)) % 7
    step = 7.0 / count
    chosen: List[int] = []
    for index in range(count):
        day = (offset + int(index * step)) % 7
        while day in chosen:
            day = (day + 1) % 7
        chosen.append(day)
    return chosen


def material_due_count(material: sqlite3.Row, day: date) -> int:
    count = int(material["cadence_count"] or 0)
    if count <= 0:
        return 0
    if material["cadence_period"] == "day":
        return count
    weekdays = weekly_weekdays(int(material["id"]), count)
    return 1 if day.weekday() in weekdays else 0


def build_plan(
    conn: sqlite3.Connection,
    day: date,
    budget: Optional[int] = None,
    wake: Optional[str] = None,
) -> Dict[str, Any]:
    """Deterministic day plan: interleaved slots, trimmed to the daily budget."""
    if budget is None:
        budget = setting_int(conn, "budget", DEFAULT_BUDGET)
    budget = max(0, int(budget))
    if wake is None:
        wake = effective_setting(conn, "wake") or DEFAULT_WAKE
    start, end = parse_wake(wake)
    materials = conn.execute(
        "SELECT * FROM materials WHERE active = 1 ORDER BY priority, id"
    ).fetchall()

    pools: List[List[int]] = []
    names: Dict[int, str] = {}
    for material in materials:
        names[int(material["id"])] = material["name"]
        due = material_due_count(material, day)
        if due:
            pools.append([int(material["id"])] * due)

    order: List[int] = []
    active_pools = [pool for pool in pools]
    while any(active_pools):
        for pool in active_pools:
            if pool:
                order.append(pool.pop(0))

    kept = order[:budget]
    dropped_ids = order[budget:]
    times = spread_times(start, end, len(kept))
    slots = [
        {
            "index": index,
            "material_id": material_id,
            "material_name": names.get(material_id),
            "due_at": times[index],
        }
        for index, material_id in enumerate(kept)
    ]
    dropped = [
        {"material_id": material_id, "material_name": names.get(material_id)}
        for material_id in dropped_ids
    ]
    return {
        "date": day.isoformat(),
        "budget": budget,
        "wake": wake,
        "slots": slots,
        "dropped": dropped,
        "planned_total": len(order),
    }


def ensure_day_plan(conn: sqlite3.Connection, day: date) -> Dict[str, Any]:
    plan = build_plan(conn, day)
    for slot in plan["slots"]:
        conn.execute(
            "INSERT OR IGNORE INTO day_slots (date, slot_index, material_id, due_at, status) "
            "VALUES (?, ?, ?, ?, 'planned')",
            (plan["date"], slot["index"], slot["material_id"], slot["due_at"]),
        )
    conn.commit()
    return plan


def day_slots(conn: sqlite3.Connection, day: str) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM day_slots WHERE date = ? ORDER BY slot_index", (day,)
    ).fetchall()


# ---------------------------------------------------------------------------
# Material / chunk helpers
# ---------------------------------------------------------------------------

def resolve_material(
    conn: sqlite3.Connection,
    ident: Any,
    field: str = "material",
    allow_archived: bool = False,
) -> sqlite3.Row:
    if ident is None or not str(ident).strip():
        raise CommandError("not_found", "%s is required" % field)
    text = str(ident).strip()
    row = None
    if text.isdigit():
        row = conn.execute("SELECT * FROM materials WHERE id = ?", (int(text),)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM materials WHERE name = ? COLLATE NOCASE", (text,)
        ).fetchone()
    if row is None:
        raise CommandError("not_found", "no %s matches %r" % (field, text))
    if not allow_archived and not row["active"]:
        raise CommandError("not_found", "%s %r is archived" % (field, row["name"]))
    return row


def material_dict(conn: sqlite3.Connection, row: sqlite3.Row, detail: bool = False) -> Dict[str, Any]:
    delivered = conn.execute(
        "SELECT COUNT(DISTINCT chunk_id) AS n FROM deliveries WHERE material_id = ?",
        (row["id"],),
    ).fetchone()["n"]
    total = int(row["chunk_count"] or 0)
    coverage = round((delivered / total) * 100.0, 1) if total else 0.0
    data: Dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "active": bool(row["active"]),
        "cadence_count": int(row["cadence_count"]),
        "cadence_period": row["cadence_period"],
        "cadence": "%d/%s" % (int(row["cadence_count"]), row["cadence_period"]),
        "priority": int(row["priority"]),
        "chunk_count": total,
        "delivered_chunks": int(delivered),
        "coverage_pct": coverage,
        "source_path": row["source_path"],
        "created_at": row["created_at"],
    }
    if detail:
        data["source_hash"] = row["source_hash"]
    return data


def chunk_dict(row: sqlite3.Row, include_text: bool = True) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": row["id"],
        "material_id": row["material_id"],
        "ordinal": int(row["ordinal"]),
        "token_est": int(row["token_est"]),
        "delivered_count": int(row["delivered_count"]),
        "last_delivered_at": row["last_delivered_at"],
    }
    if include_text:
        data["text"] = row["text"]
    return data


def candidate_chunks(
    conn: sqlite3.Connection,
    material_id: int,
    cooldown_days: int,
    today: date,
) -> List[sqlite3.Row]:
    cutoff = (today - timedelta(days=max(0, cooldown_days))).isoformat()
    order = (
        "ORDER BY CASE WHEN last_delivered_at IS NULL THEN 0 ELSE 1 END, "
        "last_delivered_at ASC, ordinal ASC"
    )
    rows = conn.execute(
        "SELECT * FROM chunks WHERE material_id = ? "
        "AND (last_delivered_at IS NULL OR substr(last_delivered_at, 1, 10) < ?) " + order,
        (material_id, cutoff),
    ).fetchall()
    if rows:
        return rows
    return conn.execute(
        "SELECT * FROM chunks WHERE material_id = ? " + order, (material_id,)
    ).fetchall()


def recent_delivered_chunks(conn: sqlite3.Connection, material_id: int, limit: int = DEDUP_RECENT) -> List[sqlite3.Row]:
    rows = conn.execute(
        "SELECT c.* FROM deliveries d JOIN chunks c ON c.id = d.chunk_id "
        "WHERE d.material_id = ? AND d.chunk_id IS NOT NULL "
        "ORDER BY d.delivered_at DESC, d.id DESC",
        (material_id,),
    ).fetchall()
    seen = set()
    unique: List[sqlite3.Row] = []
    for row in rows:
        if int(row["id"]) in seen:
            continue
        seen.add(int(row["id"]))
        unique.append(row)
        if len(unique) >= int(limit):
            break
    return unique


def select_chunk(
    conn: sqlite3.Connection,
    collection: Any,
    material: sqlite3.Row,
    strategy: str,
    query: Optional[str],
    cooldown_days: int,
    dedup_threshold: float,
    today: date,
) -> sqlite3.Row:
    candidates = candidate_chunks(conn, int(material["id"]), cooldown_days, today)
    if not candidates:
        raise CommandError("not_found", "material %r has no chunks to deliver" % material["name"])

    if strategy == "random":
        return random.choice(candidates)

    vectors: Dict[str, List[float]] = {}
    if collection is not None:
        try:
            vectors = chroma_get_embeddings(
                collection, chroma_ids(int(material["id"]), [int(c["ordinal"]) for c in candidates])
            )
        except CommandError:
            vectors = {}

    if strategy == "similarity":
        topic = (query or material["name"] or "").strip()
        if topic:
            query_vector = embed_texts(conn, [topic])[0]
            ranked = []
            for candidate in candidates:
                key = "%d:%d" % (int(material["id"]), int(candidate["ordinal"]))
                vector = vectors.get(key)
                score = cosine(query_vector, vector) if vector else 0.0
                ranked.append((score, int(candidate["ordinal"]), candidate))
            ranked.sort(key=lambda item: (-item[0], item[1]))
            return ranked[0][2]

    recent = recent_delivered_chunks(conn, int(material["id"]), DEDUP_RECENT)
    if collection is not None and recent:
        recent_vectors = chroma_get_embeddings(
            collection, chroma_ids(int(material["id"]), [int(c["ordinal"]) for c in recent])
        )
        if recent_vectors:
            filtered: List[sqlite3.Row] = []
            for candidate in candidates:
                key = "%d:%d" % (int(material["id"]), int(candidate["ordinal"]))
                vector = vectors.get(key)
                if vector is None:
                    filtered.append(candidate)
                    continue
                worst = max(cosine(vector, rv) for rv in recent_vectors.values())
                if worst <= dedup_threshold:
                    filtered.append(candidate)
            if filtered:
                candidates = filtered
    return candidates[0]


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


def run_script(domain: str, parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args()
    fmt = getattr(args, "format", "json")
    quiet = getattr(args, "quiet", False)
    verb = getattr(args, "verb", domain)
    handler = getattr(args, "func", None)
    if handler is None:
        parser.print_help(sys.stderr)
        sys.exit(2)
    home = resolve_home(getattr(args, "home", None))
    try:
        home.mkdir(parents=True, exist_ok=True)
        conn = connect(resolve_db_path(home))
        try:
            migrate(conn)
            data = handler(conn, home, args)
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
    parser = subparsers.add_parser(
        name, help=help_text, description=help_text, parents=list(parents)
    )
    parser.set_defaults(verb=name)
    return parser
