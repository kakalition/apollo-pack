"""Live turn status for nanobot: one rotating sentence, edited in place.

The controller subscribes to the local nanobot bus, and for every Telegram turn
it sends a single status message and then edits that same message with a new
phrase every few seconds. On turn completion the message is removed (or kept,
if configured). Nothing else is shown: no step list, no elapsed time, no tool
names, no commands.

All nanobot imports happen lazily inside functions and are guarded: if the host
internals have drifted, the plugin logs once and no-ops instead of crashing the
host.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from .phrases import ThinkingPhrases, parse_phrases

__all__ = [
    "LiveStatusController",
    "StatusConfig",
    "TelegramStatusSink",
    "TurnStatus",
    "load_status_config",
]

logger = logging.getLogger("nanobot_live_status")

_TELEGRAM_API_BASE = "https://api.telegram.org"
_DEFAULT_INTERVAL_S = 3.0
_MIN_INTERVAL_S = 1.0
_MAX_INTERVAL_S = 60.0
_MAX_TEXT_LEN = 3500
_MAX_ATTEMPTS = 3
_MAX_RETRY_AFTER_S = 5.0


@dataclass(frozen=True)
class StatusConfig:
    """Resolved settings for the live-status middleware."""

    token: str
    interval_s: float = _DEFAULT_INTERVAL_S
    phrases: tuple[str, ...] = ()
    keep_message: bool = False

    @property
    def phrase_source(self) -> ThinkingPhrases:
        return ThinkingPhrases(self.phrases)


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("live-status: ignoring non-numeric %s=%r", name, raw)
        return default


def _telegram_token_from_nanobot() -> str:
    """Read the Telegram bot token from nanobot's config, never logging it."""
    try:
        from nanobot.config.loader import load_config, resolve_env_refs
    except Exception as exc:  # pragma: no cover - exercised only on drifted hosts
        logger.warning("live-status: nanobot config internals unavailable (%s); disabled", exc)
        return ""

    try:
        config = load_config()
    except Exception as exc:  # pragma: no cover - host-specific
        logger.warning("live-status: could not load nanobot config (%s); disabled", exc)
        return ""

    channels = getattr(config, "channels", None)
    telegram = getattr(channels, "telegram", None)
    if telegram is None:
        return ""

    if isinstance(telegram, dict):
        enabled = bool(telegram.get("enabled"))
        raw_token = telegram.get("token")
    else:
        enabled = bool(getattr(telegram, "enabled", False))
        raw_token = getattr(telegram, "token", None)

    if not enabled or not isinstance(raw_token, str) or not raw_token.strip():
        return ""
    resolved = resolve_env_refs(raw_token)
    return resolved.strip() if isinstance(resolved, str) else ""


def load_status_config() -> StatusConfig | None:
    """Resolve the live-status config, or ``None`` when it should stay off."""
    if _env_flag("NANOBOT_LIVE_STATUS_DISABLED"):
        return None

    token = os.environ.get("NANOBOT_LIVE_STATUS_TOKEN", "").strip()
    if not token:
        token = _telegram_token_from_nanobot()
    if not token:
        logger.info("live-status: no Telegram token configured; middleware disabled")
        return None

    interval = _env_float("NANOBOT_LIVE_STATUS_INTERVAL", _DEFAULT_INTERVAL_S)
    interval = max(_MIN_INTERVAL_S, min(_MAX_INTERVAL_S, interval))

    return StatusConfig(
        token=token,
        interval_s=interval,
        phrases=parse_phrases(os.environ.get("NANOBOT_LIVE_STATUS_PHRASES")),
        keep_message=_env_flag("NANOBOT_LIVE_STATUS_KEEP"),
    )


class TelegramAPIError(RuntimeError):
    """A Telegram Bot API call failed. The message never contains the token."""


@runtime_checkable
class StatusSink(Protocol):
    """Minimal sink the ticker needs: send one message, edit it, delete it."""

    async def send(self, text: str) -> Any: ...

    async def edit(self, message_id: Any, text: str) -> None: ...

    async def delete(self, message_id: Any) -> None: ...


def _retry_after_seconds(payload: dict[str, Any]) -> float:
    params = payload.get("parameters")
    if isinstance(params, dict):
        with contextlib.suppress(TypeError, ValueError):
            return float(params.get("retry_after", 1.0))
    return 1.0


class TelegramStatusSink:
    """Talks to the Telegram Bot API directly over httpx."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        client: httpx.AsyncClient | None = None,
        api_base: str = _TELEGRAM_API_BASE,
    ) -> None:
        self._token = token
        self._chat_id = str(chat_id)
        self._client = client
        self._owns_client = client is None
        self._api_base = api_base.rstrip("/")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        return self._client

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        url = f"{self._api_base}/bot{self._token}/{method}"
        last_error = "unknown error"

        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await client.post(url, json=payload)
            except httpx.HTTPError as exc:
                # Never surface the URL: it embeds the bot token.
                last_error = f"network error ({type(exc).__name__})"
                await asyncio.sleep(0.4 * (attempt + 1))
                continue

            data = self._json(response)
            if response.status_code == 429:
                await asyncio.sleep(min(_retry_after_seconds(data), _MAX_RETRY_AFTER_S))
                last_error = "rate limited"
                continue
            if response.status_code >= 500:
                await asyncio.sleep(0.4 * (attempt + 1))
                last_error = f"server error {response.status_code}"
                continue

            description = str(data.get("description") or "")
            if response.status_code == 400 and "not modified" in description.lower():
                return {"ok": True, "result": None}
            if data.get("ok"):
                return data
            last_error = description or f"http {response.status_code}"

        raise TelegramAPIError(f"{method}: {last_error}")

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    async def send(self, text: str) -> Any:
        data = await self._call(
            "sendMessage",
            {
                "chat_id": self._chat_id,
                "text": text[:_MAX_TEXT_LEN],
                "disable_notification": True,
                "disable_web_page_preview": True,
            },
        )
        result = data.get("result")
        return result.get("message_id") if isinstance(result, dict) else None

    async def edit(self, message_id: Any, text: str) -> None:
        if message_id is None:
            return
        await self._call(
            "editMessageText",
            {
                "chat_id": self._chat_id,
                "message_id": message_id,
                "text": text[:_MAX_TEXT_LEN],
                "disable_web_page_preview": True,
            },
        )

    async def delete(self, message_id: Any) -> None:
        if message_id is None:
            return
        await self._call(
            "deleteMessage",
            {"chat_id": self._chat_id, "message_id": message_id},
        )

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None and self._owns_client:
            with contextlib.suppress(Exception):
                await client.aclose()


class TurnStatus:
    """One in-flight status message, edited in place until the turn ends."""

    def __init__(
        self,
        sink: StatusSink,
        phrases: ThinkingPhrases,
        *,
        interval_s: float = _DEFAULT_INTERVAL_S,
        keep_message: bool = False,
    ) -> None:
        self._sink = sink
        self._phrases = phrases
        self._interval_s = interval_s
        self._keep_message = keep_message
        self._message_id: Any = None
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._lock = asyncio.Lock()

    @property
    def message_id(self) -> Any:
        return self._message_id

    async def start(self) -> None:
        try:
            self._message_id = await self._sink.send(self._phrases.next())
        except Exception as exc:
            logger.debug("live-status: initial send failed: %s", exc)
            self._message_id = None
            return
        if self._message_id is None:
            return
        self._task = asyncio.create_task(self._tick(), name="nanobot-live-status")

    async def _tick(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval_s)
                if self._stopped:
                    return
                async with self._lock:
                    if self._stopped or self._message_id is None:
                        return
                    try:
                        await self._sink.edit(self._message_id, self._phrases.next())
                    except Exception as exc:
                        logger.debug("live-status: edit failed: %s", exc)
        except asyncio.CancelledError:
            return

    async def stop(self, *, delete: bool | None = None) -> None:
        self._stopped = True
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        remove = (not self._keep_message) if delete is None else delete
        message_id, self._message_id = self._message_id, None
        if remove and message_id is not None:
            try:
                await self._sink.delete(message_id)
            except Exception as exc:
                logger.debug("live-status: delete failed: %s", exc)

        aclose = getattr(self._sink, "aclose", None)
        if callable(aclose):
            with contextlib.suppress(Exception):
                await aclose()


class LiveStatusController:
    """Maps Telegram turn events to per-session ``TurnStatus`` instances."""

    def __init__(
        self,
        config: StatusConfig,
        *,
        sink_factory: Callable[[str, str], StatusSink] | None = None,
    ) -> None:
        self._config = config
        self._sink_factory = sink_factory or (
            lambda token, chat_id: TelegramStatusSink(token, chat_id)
        )
        self._turns: dict[str, TurnStatus] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._unsubscribers: list[Callable[[], None]] = []
        self._closed = False

    @property
    def config(self) -> StatusConfig:
        return self._config

    def subscribe(self, bus: Any) -> bool:
        """Subscribe to turn events on ``bus``; return ``True`` when wired."""
        if self._closed:
            return False
        try:
            from nanobot.bus.runtime_events import SessionTurnStarted, TurnCompleted
        except Exception as exc:  # pragma: no cover - drifted host
            logger.warning("live-status: runtime events unavailable (%s); disabled", exc)
            return False
        try:
            self._unsubscribers.append(bus.subscribe(self._on_turn_started, SessionTurnStarted))
            self._unsubscribers.append(bus.subscribe(self._on_turn_completed, TurnCompleted))
        except Exception as exc:  # pragma: no cover - drifted host
            logger.warning("live-status: could not subscribe to bus (%s); disabled", exc)
            return False
        return True

    @staticmethod
    def _context(event: Any) -> Any:
        return getattr(event, "context", None)

    @staticmethod
    def _key(channel: str, chat_id: str, session_key: str | None) -> str:
        return session_key or f"{channel}:{chat_id}"

    async def _on_turn_started(self, event: Any) -> None:
        if self._closed:
            return
        context = self._context(event)
        if context is None:
            return
        channel = str(getattr(context, "channel", "") or "")
        chat_id = str(getattr(context, "chat_id", "") or "")
        if channel != "telegram" or not chat_id:
            return
        session_key = getattr(context, "session_key", None)
        await self.start_turn(channel, chat_id, session_key)

    async def _on_turn_completed(self, event: Any) -> None:
        context = self._context(event)
        if context is None:
            return
        channel = str(getattr(context, "channel", "") or "")
        chat_id = str(getattr(context, "chat_id", "") or "")
        await self.stop_turn(self._key(channel, chat_id, getattr(context, "session_key", None)))

    async def start_turn(
        self,
        channel: str,
        chat_id: str,
        session_key: str | None,
        *,
        phrase_source: ThinkingPhrases | None = None,
    ) -> None:
        """Start (or restart) the status for one turn."""
        if self._closed or channel != "telegram" or not chat_id:
            return
        key = self._key(channel, chat_id, session_key)
        await self.stop_turn(key)
        status = TurnStatus(
            self._sink_factory(self._config.token, chat_id),
            phrase_source or self._config.phrase_source,
            interval_s=self._config.interval_s,
            keep_message=self._config.keep_message,
        )
        self._turns[key] = status
        self._spawn(status.start())

    async def stop_turn(self, key: str) -> None:
        status = self._turns.pop(key, None)
        if status is not None:
            await status.stop()

    def _spawn(self, coro: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        task = loop.create_task(coro, name="nanobot-live-status-start")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        for unsubscribe in self._unsubscribers:
            with contextlib.suppress(Exception):
                unsubscribe()
        self._unsubscribers.clear()
        keys = list(self._turns)
        for key in keys:
            with contextlib.suppress(Exception):
                await self.stop_turn(key)
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            with contextlib.suppress(Exception):
                await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
