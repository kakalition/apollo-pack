from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from nanobot_live_status import status as status_mod
from nanobot_live_status.phrases import ThinkingPhrases
from nanobot_live_status.status import (
    LiveStatusController,
    StatusConfig,
    TelegramAPIError,
    TelegramStatusSink,
    TurnStatus,
    load_status_config,
)


class FakeSink:
    def __init__(self, *, fail_edit: bool = False) -> None:
        self.sent: list[str] = []
        self.edits: list[tuple[Any, str]] = []
        self.deleted: list[Any] = []
        self.closed = False
        self.fail_edit = fail_edit
        self._next_id = 0

    async def send(self, text: str) -> Any:
        self._next_id += 1
        self.sent.append(text)
        return self._next_id

    async def edit(self, message_id: Any, text: str) -> None:
        if self.fail_edit:
            raise RuntimeError("edit boom")
        self.edits.append((message_id, text))

    async def delete(self, message_id: Any) -> None:
        self.deleted.append(message_id)

    async def aclose(self) -> None:
        self.closed = True


class FakeBus:
    def __init__(self) -> None:
        self.handlers: list[tuple[Any, Any]] = []

    def subscribe(self, handler: Any, event_type: Any = None) -> Any:
        entry = (handler, event_type)
        self.handlers.append(entry)

        def unsubscribe() -> None:
            self.handlers.remove(entry)

        return unsubscribe

    async def publish(self, event: Any) -> None:
        for handler, event_type in list(self.handlers):
            if event_type is None or isinstance(event, event_type):
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result


# --------------------------------------------------------------------------- #
# Config resolution
# --------------------------------------------------------------------------- #


def test_config_disabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOBOT_LIVE_STATUS_DISABLED", "1")
    monkeypatch.setenv("NANOBOT_LIVE_STATUS_TOKEN", "tok")
    assert load_status_config() is None


def test_config_uses_env_token_and_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NANOBOT_LIVE_STATUS_DISABLED", raising=False)
    monkeypatch.setenv("NANOBOT_LIVE_STATUS_TOKEN", "tok")
    monkeypatch.setenv("NANOBOT_LIVE_STATUS_INTERVAL", "4.5")
    monkeypatch.setenv("NANOBOT_LIVE_STATUS_PHRASES", "a|b")
    monkeypatch.setenv("NANOBOT_LIVE_STATUS_KEEP", "true")
    config = load_status_config()
    assert config is not None
    assert config.token == "tok"
    assert config.interval_s == 4.5
    assert config.phrases == ("a", "b")
    assert config.keep_message is True


def test_config_clamps_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NANOBOT_LIVE_STATUS_TOKEN", "tok")
    monkeypatch.setenv("NANOBOT_LIVE_STATUS_INTERVAL", "0.1")
    config = load_status_config()
    assert config is not None
    assert config.interval_s == 1.0


def test_config_none_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NANOBOT_LIVE_STATUS_TOKEN", raising=False)
    monkeypatch.setattr(status_mod, "_telegram_token_from_nanobot", lambda: "")
    assert load_status_config() is None


# --------------------------------------------------------------------------- #
# TurnStatus
# --------------------------------------------------------------------------- #


async def test_turn_status_edits_and_deletes() -> None:
    sink = FakeSink()
    turn = TurnStatus(sink, ThinkingPhrases(["p1", "p2", "p3"]), interval_s=0.01)
    await turn.start()
    assert sink.sent == ["p1"]
    await asyncio.sleep(0.05)
    assert turn.message_id == 1
    assert len(sink.edits) >= 1
    assert all(message_id == 1 for message_id, _ in sink.edits)
    await turn.stop()
    assert sink.deleted == [1]
    assert sink.closed is True
    edits_after = len(sink.edits)
    await asyncio.sleep(0.02)
    assert len(sink.edits) == edits_after


async def test_turn_status_keep_message() -> None:
    sink = FakeSink()
    turn = TurnStatus(sink, ThinkingPhrases(["p"]), interval_s=5, keep_message=True)
    await turn.start()
    await turn.stop()
    assert sink.deleted == []
    assert sink.closed is True


async def test_turn_status_survives_edit_failure() -> None:
    sink = FakeSink(fail_edit=True)
    turn = TurnStatus(sink, ThinkingPhrases(["p1", "p2"]), interval_s=0.01)
    await turn.start()
    await asyncio.sleep(0.05)
    await turn.stop()
    assert sink.deleted == [1]


async def test_turn_status_no_send_no_ticker() -> None:
    class FailingSink(FakeSink):
        async def send(self, text: str) -> Any:
            raise RuntimeError("send boom")

    sink = FailingSink()
    turn = TurnStatus(sink, ThinkingPhrases(["p"]), interval_s=0.01)
    await turn.start()
    assert turn.message_id is None
    await turn.stop()
    assert sink.deleted == []


# --------------------------------------------------------------------------- #
# Controller
# --------------------------------------------------------------------------- #


async def test_controller_start_and_stop_turn() -> None:
    sinks: list[tuple[str, FakeSink]] = []

    def factory(token: str, chat_id: str) -> FakeSink:
        sink = FakeSink()
        sinks.append((chat_id, sink))
        return sink

    config = StatusConfig(token="t", interval_s=10)
    controller = LiveStatusController(config, sink_factory=factory)
    await controller.start_turn("telegram", "42", "sk")
    await asyncio.sleep(0.01)
    assert sinks[0][0] == "42"
    assert sinks[0][1].sent
    await controller.stop_turn("sk")
    assert sinks[0][1].deleted == [1]
    await controller.aclose()


async def test_controller_handles_turn_events() -> None:
    sinks: list[FakeSink] = []

    def factory(token: str, chat_id: str) -> FakeSink:
        sink = FakeSink()
        sinks.append(sink)
        return sink

    controller = LiveStatusController(StatusConfig(token="t", interval_s=10), sink_factory=factory)
    event = SimpleNamespace(
        context=SimpleNamespace(channel="telegram", chat_id="7", session_key="sk7")
    )
    await controller._on_turn_started(event)
    await asyncio.sleep(0.01)
    assert len(sinks) == 1
    await controller._on_turn_completed(event)
    assert sinks[0].deleted == [1]
    await controller.aclose()


async def test_controller_ignores_other_channels() -> None:
    sinks: list[FakeSink] = []

    def factory(token: str, chat_id: str) -> FakeSink:
        sink = FakeSink()
        sinks.append(sink)
        return sink

    controller = LiveStatusController(StatusConfig(token="t", interval_s=10), sink_factory=factory)
    event = SimpleNamespace(context=SimpleNamespace(channel="cli", chat_id="7", session_key="sk7"))
    await controller._on_turn_started(event)
    await asyncio.sleep(0.01)
    assert sinks == []
    await controller.aclose()


async def test_controller_restarts_same_session() -> None:
    sinks: list[FakeSink] = []

    def factory(token: str, chat_id: str) -> FakeSink:
        sink = FakeSink()
        sinks.append(sink)
        return sink

    controller = LiveStatusController(StatusConfig(token="t", interval_s=10), sink_factory=factory)
    await controller.start_turn("telegram", "7", "sk")
    await asyncio.sleep(0.01)
    await controller.start_turn("telegram", "7", "sk")
    await asyncio.sleep(0.01)
    assert len(sinks) == 2
    assert sinks[0].deleted == [1]
    await controller.aclose()


def test_controller_subscribe_registers_handlers() -> None:
    pytest.importorskip("nanobot")
    controller = LiveStatusController(StatusConfig(token="t"))
    bus = FakeBus()
    assert controller.subscribe(bus) is True
    assert len(bus.handlers) == 2


# --------------------------------------------------------------------------- #
# TelegramStatusSink
# --------------------------------------------------------------------------- #


async def test_sink_sends_edits_and_deletes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 11}})
        return httpx.Response(200, json={"ok": True, "result": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = TelegramStatusSink("SECRET", "5", client=client)
    assert await sink.send("hi") == 11
    await sink.edit(11, "bye")
    await sink.delete(11)
    assert [json.loads(r.content)["chat_id"] for r in seen] == ["5", "5", "5"]
    await client.aclose()


async def test_sink_ignores_not_modified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"ok": False, "description": "Bad Request: message is not modified"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = TelegramStatusSink("SECRET", "5", client=client)
    await sink.edit(1, "same")
    await client.aclose()


async def test_sink_retries_after_rate_limit() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 0}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 3}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = TelegramStatusSink("SECRET", "5", client=client)
    assert await sink.send("hi") == 3
    assert calls["n"] == 2
    await client.aclose()


async def test_sink_errors_never_leak_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_mod, "_MAX_ATTEMPTS", 1)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "failed https://api.telegram.org/botSECRET/sendMessage", request=request
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    sink = TelegramStatusSink("SECRET", "5", client=client)
    with pytest.raises(TelegramAPIError) as excinfo:
        await sink.send("hi")
    assert "SECRET" not in str(excinfo.value)
    await client.aclose()
