"""Rotating status phrases.

There are deliberately no tool names, commands, counters or timing here: the
status is a single warm sentence that changes every few seconds. Phrases come
from a shuffled product of actions x objects x emoji, so the same line is
unlikely to repeat within a month.

Ported from ``lattice/channel/live_status.py`` (stdlib only).
"""

from __future__ import annotations

import random
from collections.abc import Sequence

__all__ = [
    "THINKING_DECK",
    "PhraseDeck",
    "ThinkingPhrases",
    "parse_phrases",
]


class PhraseDeck:
    """Endless, non-repeating shuffled sequence over actions x objects x emoji."""

    def __init__(
        self,
        actions: Sequence[str],
        objects: Sequence[str],
        emojis: Sequence[str],
        *,
        template: str = "{emoji} {action} {object}\u2026",
        seed: int | None = None,
    ) -> None:
        self._actions = tuple(actions)
        self._objects = tuple(objects)
        self._emojis = tuple(emojis)
        self._template = template
        self._count = len(self._actions) * len(self._objects) * len(self._emojis)
        self._rng = random.Random(seed)
        self._deck: list[int] = []

    @property
    def size(self) -> int:
        return self._count

    def next(self) -> str:
        if self._count == 0:
            return "thinking\u2026"
        if not self._deck:
            self._deck = list(range(self._count))
            self._rng.shuffle(self._deck)
        idx = self._deck.pop()
        per_action = len(self._objects)
        per_emoji = len(self._actions) * per_action
        emoji = idx // per_emoji
        rest = idx % per_emoji
        action = rest // per_action
        obj = rest % per_action
        return self._template.format(
            emoji=self._emojis[emoji], action=self._actions[action], object=self._objects[obj]
        )


_THINK_ACTIONS = (
    "mulling over",
    "scrolling through",
    "turning over",
    "sifting through",
    "noodling on",
    "poking at",
    "sketching out",
    "untangling",
    "weighing up",
    "lining up",
    "chewing on",
    "rummaging through",
    "piecing together",
    "double-checking",
    "tracing",
    "simmering on",
    "gathering",
    "polishing",
    "re-reading",
    "squinting at",
    "tidying up",
    "revisiting",
    "threading together",
    "mapping out",
    "puzzling over",
    "smoothing out",
    "shuffling",
    "plucking at",
    "brewing",
    "unpacking",
)
_THINK_OBJECTS = (
    "the details",
    "that thought",
    "the moving parts",
    "the fine print",
    "the pieces",
    "the options",
    "the angles",
    "the threads",
    "the possibilities",
    "the wording",
    "the next step",
    "the edges",
    "the plan",
    "the numbers",
    "the loose ends",
    "the shape of it",
    "the trade-offs",
    "the timing",
    "the bigger picture",
    "the small stuff",
    "the breadcrumbs",
    "the why",
    "the how",
    "the whole thing",
    "a few ideas",
    "the quiet parts",
    "the half-formed bits",
    "the shape of the answer",
)
_THINK_EMOJI = (
    "\U0001f9e0",
    "\u2728",
    "\U0001f914",
    "\U0001f300",
    "\U0001f4dd",
    "\U0001f50d",
    "\U0001f9e9",
    "\U0001f4ad",
    "\U0001f33f",
    "\u2699\ufe0f",
    "\U0001fa84",
    "\U0001f4da",
    "\U0001f5fa\ufe0f",
    "\U0001f570\ufe0f",
    "\U0001fae7",
    "\U0001f9f5",
    "\U0001f6e0\ufe0f",
    "\U0001f52e",
    "\U0001f31f",
    "\u2615",
    "\U0001f343",
    "\U0001f9ed",
    "\U0001fab6",
    "\U0001f3a8",
    "\U0001f9ee",
    "\U0001f4ce",
    "\U0001f324\ufe0f",
    "\U0001fab4",
    "\U0001fad6",
    "\U0001f9ca",
    "\U0001f56f\ufe0f",
    "\U0001f3a7",
    "\U0001f4a1",
    "\U0001f516",
    "\U0001f9f7",
    "\U0001f4d0",
    "\U0001f9ea",
    "\U0001f308",
    "\U0001fad0",
    "\U0001f338",
    "\U0001f9f8",
    "\U0001f390",
    "\U0001fa81",
)

THINKING_DECK = PhraseDeck(_THINK_ACTIONS, _THINK_OBJECTS, _THINK_EMOJI)


def parse_phrases(raw: str | None) -> tuple[str, ...]:
    """Parse a user-supplied phrase list.

    ``raw`` is split on ``|`` (pipe) so phrases may contain commas. Blank
    entries are dropped; surrounding whitespace is stripped.
    """
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split("|") if part.strip())


class ThinkingPhrases:
    """A phrase source that is either an explicit list or the shuffled deck."""

    def __init__(
        self,
        phrases: Sequence[str] | None = None,
        *,
        seed: int | None = None,
    ) -> None:
        explicit = tuple(phrases or ())
        self._explicit = explicit
        self._index = 0
        self._deck = PhraseDeck(_THINK_ACTIONS, _THINK_OBJECTS, _THINK_EMOJI, seed=seed)

    @property
    def size(self) -> int:
        return len(self._explicit) if self._explicit else self._deck.size

    def next(self) -> str:
        if self._explicit:
            phrase = self._explicit[self._index % len(self._explicit)]
            self._index += 1
            return phrase
        return self._deck.next()
