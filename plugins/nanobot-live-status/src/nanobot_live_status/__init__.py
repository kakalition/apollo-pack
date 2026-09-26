"""nanobot-live-status: one rotating status sentence while a nanobot turn runs.

Not affiliated with the nanobot project. See the README for installation.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .phrases import THINKING_DECK, PhraseDeck, ThinkingPhrases, parse_phrases
from .status import (
    LiveStatusController,
    StatusConfig,
    TelegramStatusSink,
    TurnStatus,
    load_status_config,
)
from .tool import LiveStatusTool

try:
    __version__ = version("nanobot-live-status")
except PackageNotFoundError:  # pragma: no cover - source checkout
    __version__ = "0.1.0"

__all__ = [
    "THINKING_DECK",
    "LiveStatusController",
    "LiveStatusTool",
    "PhraseDeck",
    "StatusConfig",
    "TelegramStatusSink",
    "ThinkingPhrases",
    "TurnStatus",
    "__version__",
    "load_status_config",
    "parse_phrases",
]
