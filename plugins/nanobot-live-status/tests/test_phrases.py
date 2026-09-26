from __future__ import annotations

import pytest

from nanobot_live_status.phrases import PhraseDeck, ThinkingPhrases, parse_phrases


def test_deck_size_is_product_of_dimensions() -> None:
    deck = PhraseDeck(["a", "b"], ["x", "y", "z"], ["1", "2"])
    assert deck.size == 12


def test_deck_formats_template() -> None:
    deck = PhraseDeck(["mulling over"], ["the plan"], ["*"], template="{emoji} {action} {object}")
    assert deck.next() == "* mulling over the plan"


def test_deck_never_repeats_within_a_full_pass() -> None:
    actions = [f"a{i}" for i in range(7)]
    objects = [f"o{i}" for i in range(11)]
    emojis = [f"e{i}" for i in range(5)]
    deck = PhraseDeck(actions, objects, emojis, seed=1234)
    seen = [deck.next() for _ in range(deck.size)]
    assert len(set(seen)) == deck.size
    assert all(deck.next() for _ in range(3))


def test_empty_deck_is_safe() -> None:
    assert PhraseDeck([], [], []).next() == "thinking\u2026"


def test_explicit_phrases_cycle() -> None:
    source = ThinkingPhrases(["one", "two"])
    assert [source.next() for _ in range(5)] == ["one", "two", "one", "two", "one"]
    assert source.size == 2


def test_default_source_uses_the_deck() -> None:
    source = ThinkingPhrases()
    assert source.size > 1000
    assert isinstance(source.next(), str)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ()),
        ("", ()),
        ("  ", ()),
        ("a | b |c", ("a", "b", "c")),
        ("keep, commas | two", ("keep, commas", "two")),
        ("||", ()),
    ],
)
def test_parse_phrases(raw: str | None, expected: tuple[str, ...]) -> None:
    assert parse_phrases(raw) == expected
