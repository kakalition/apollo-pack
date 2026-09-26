"""The ``nanobot.tools`` entry-point target.

The only external plugin surface nanobot exposes today is the ``nanobot.tools``
entry-point group, which *requires* a registered ``Tool`` subclass. Live status
is middleware, not a capability the model should ever call, so this tool is an
intentional no-op: its only real work happens in :meth:`create`, where it wires
the bus subscription that runs the status ticker.

``create`` runs exactly once, at loop construction and before any turn, and
receives ``ToolContext.bus``. That is what lets the very first turn after a
restart show the rotating sentence. ``_scopes = {"core"}`` keeps the tool out of
subagent registries.

If upstream ever exposes a ``nanobot.hooks`` entry-point group, this dummy tool
can be replaced by a hook with no behavior change.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

try:  # pragma: no cover - the host always provides these when the plugin loads
    from nanobot.agent.tools.base import Tool, ToolResult
except Exception:  # pragma: no cover - keeps a bare import from exploding

    class Tool:  # type: ignore[no-redef]
        """Minimal stand-in used only when nanobot is not importable."""

        config_key: str = ""
        _plugin_discoverable: bool = False
        _scopes: ClassVar[set[str]] = {"core"}

        @classmethod
        def enabled(cls, ctx: Any) -> bool:
            return False

        @classmethod
        def create(cls, ctx: Any) -> Tool:
            return cls()

        async def execute(self, **kwargs: Any) -> Any:
            return ""

    class ToolResult(str):  # type: ignore[no-redef]
        pass


from .status import LiveStatusController, load_status_config

__all__ = ["LiveStatusTool", "get_controller"]

logger = logging.getLogger("nanobot_live_status")

_INTERNAL_MESSAGE = "live_status is internal middleware; there is nothing to run."

# One controller per MessageBus instance, so repeated loop construction (e.g.
# gateway reloads sharing a bus) never double-subscribes or double-ticks.
_CONTROLLERS: dict[int, LiveStatusController] = {}

# Keeps fire-and-forget startup tasks alive until they finish.
_PENDING: set[asyncio.Task[None]] = set()


def get_controller(bus: Any) -> LiveStatusController | None:
    return _CONTROLLERS.get(id(bus)) if bus is not None else None


def _reset_controllers() -> None:
    """Test helper: forget all controllers without touching their buses."""
    _CONTROLLERS.clear()


class LiveStatusTool(Tool):
    """Internal, non-callable tool that installs the live-status middleware."""

    _plugin_discoverable = True
    _scopes: ClassVar[set[str]] = {"core"}

    @property
    def name(self) -> str:
        return "live_status"

    @property
    def description(self) -> str:
        return (
            "Internal nanobot-live-status middleware. Do not call: it performs no "
            "action and exists only to load the live-status plugin."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    @property
    def read_only(self) -> bool:
        return True

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return getattr(ctx, "bus", None) is not None

    @classmethod
    def create(cls, ctx: Any) -> LiveStatusTool:
        bus = getattr(ctx, "bus", None)
        if bus is None:
            return cls()

        try:
            config = load_status_config()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("live-status: config load failed (%s); disabled", exc)
            return cls()
        if config is None:
            return cls()

        if id(bus) in _CONTROLLERS:
            return cls()

        controller = LiveStatusController(config)
        if not controller.subscribe(bus):
            return cls()
        _CONTROLLERS[id(bus)] = controller

        # Lazily-constructed loop: the turn is already in flight and its
        # SessionTurnStarted event has passed, so start the status now.
        cls._start_for_current_request(controller)
        return cls()

    @staticmethod
    def _start_for_current_request(controller: LiveStatusController) -> None:
        try:
            from nanobot.agent.tools.context import current_request_context
        except Exception:  # pragma: no cover - drifted host
            return
        context = current_request_context()
        if context is None:
            return
        channel = str(getattr(context, "channel", "") or "")
        chat_id = str(getattr(context, "chat_id", "") or "")
        if channel != "telegram" or not chat_id:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - no loop at construction
            return
        coro = controller.start_turn(channel, chat_id, getattr(context, "session_key", None))
        task = loop.create_task(coro, name="nanobot-live-status-first-turn")
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)

    async def execute(self, **kwargs: Any) -> Any:
        return ToolResult(_INTERNAL_MESSAGE)
