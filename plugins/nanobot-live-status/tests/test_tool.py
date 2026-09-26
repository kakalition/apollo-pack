from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("nanobot")

from nanobot_live_status import tool as tool_mod
from nanobot_live_status.status import LiveStatusController, StatusConfig
from nanobot_live_status.tool import LiveStatusTool, get_controller


class FakeSink:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.deleted: list[Any] = []

    async def send(self, text: str) -> Any:
        self.sent.append(text)
        return len(self.sent)

    async def edit(self, message_id: Any, text: str) -> None:
        return None

    async def delete(self, message_id: Any) -> None:
        self.deleted.append(message_id)

    async def aclose(self) -> None:
        return None


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


@pytest.fixture(autouse=True)
def _clean_controllers() -> Any:
    tool_mod._reset_controllers()
    yield
    tool_mod._reset_controllers()


def test_metadata_is_internal() -> None:
    tool = LiveStatusTool()
    assert tool.name == "live_status"
    assert "internal" in tool.description.lower()
    assert "do not call" in tool.description.lower()
    assert tool.parameters == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert tool.read_only is True
    assert "core" in LiveStatusTool._scopes


def test_enabled_requires_a_bus() -> None:
    assert LiveStatusTool.enabled(SimpleNamespace(bus=None)) is False
    assert LiveStatusTool.enabled(SimpleNamespace(bus=FakeBus())) is True


async def test_execute_is_a_benign_noop() -> None:
    result = await LiveStatusTool().execute()
    assert "internal" in result
    assert getattr(result, "is_error", False) is False


def test_create_without_bus_is_noop() -> None:
    assert isinstance(LiveStatusTool.create(SimpleNamespace(bus=None)), LiveStatusTool)


async def test_create_wires_one_controller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_mod, "load_status_config", lambda: StatusConfig(token="t"))
    bus = FakeBus()
    ctx = SimpleNamespace(bus=bus)

    assert isinstance(LiveStatusTool.create(ctx), LiveStatusTool)
    controller = get_controller(bus)
    assert controller is not None
    assert len(bus.handlers) == 2

    # A second construction sharing the bus must not double-subscribe.
    LiveStatusTool.create(ctx)
    assert get_controller(bus) is controller
    assert len(bus.handlers) == 2

    await controller.aclose()
    await bus.publish(SimpleNamespace(context=None))


async def test_create_without_config_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tool_mod, "load_status_config", lambda: None)
    bus = FakeBus()
    LiveStatusTool.create(SimpleNamespace(bus=bus))
    assert get_controller(bus) is None
    assert bus.handlers == []


async def test_first_turn_fallback_starts_status(monkeypatch: pytest.MonkeyPatch) -> None:
    import nanobot.agent.tools.context as nb_context

    request = SimpleNamespace(channel="telegram", chat_id="9", session_key="sk9")
    monkeypatch.setattr(nb_context, "current_request_context", lambda: request)

    sinks: list[FakeSink] = []

    def factory(token: str, chat_id: str) -> FakeSink:
        sink = FakeSink()
        sinks.append(sink)
        return sink

    controller = LiveStatusController(StatusConfig(token="t", interval_s=10), sink_factory=factory)
    LiveStatusTool._start_for_current_request(controller)
    await asyncio.sleep(0.01)
    assert len(sinks) == 1
    assert sinks[0].sent
    await controller.aclose()


async def test_first_turn_fallback_ignores_other_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import nanobot.agent.tools.context as nb_context

    request = SimpleNamespace(channel="cli", chat_id="9", session_key="sk9")
    monkeypatch.setattr(nb_context, "current_request_context", lambda: request)

    sinks: list[FakeSink] = []

    def factory(token: str, chat_id: str) -> FakeSink:
        sink = FakeSink()
        sinks.append(sink)
        return sink

    controller = LiveStatusController(StatusConfig(token="t", interval_s=10), sink_factory=factory)
    LiveStatusTool._start_for_current_request(controller)
    await asyncio.sleep(0.01)
    assert sinks == []
    await controller.aclose()
