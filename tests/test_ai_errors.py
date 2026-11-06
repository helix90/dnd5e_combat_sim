"""An error in the AI fails tests (tests/conftest.py), but in the app the creature falls back to a
safe choice and the error is logged with its traceback."""

import logging

import pytest

from ai import errors
from ai.strategy import MonsterAIStrategy, PartyAIStrategy
from models.actions import AttackAction
from models.character import Character
from models.monster import Monster

SCORES = {"str": 14, "dex": 14, "con": 14, "int": 10, "wis": 10, "cha": 10}


def fighters():
    hero = Character(
        "Hero",
        5,
        "Fighter",
        "Human",
        SCORES,
        hp=40,
        ac=16,
        proficiency_bonus=3,
        actions=[AttackAction("Longsword", "", "Longsword", "1d8+2", "slashing")],
    )
    goblin = Monster(
        "Goblin",
        "1/4",
        7,
        15,
        SCORES,
        actions=[AttackAction("Scimitar", "", "Scimitar", "1d6", "slashing")],
    )
    return hero, goblin


def broken(creature):
    def is_alive():
        raise RuntimeError("a bug in the rules")

    creature.is_alive = is_alive
    return creature


@pytest.mark.parametrize(
    "strategy, side, fallback",
    [(PartyAIStrategy, "hero", "defend"), (MonsterAIStrategy, "goblin", "wait")],
)
def test_in_the_app_an_ai_error_falls_back_and_is_logged(
    monkeypatch, caplog, strategy, side, fallback
):
    monkeypatch.setattr(errors, "RAISE_ERRORS", False)
    hero, goblin = fighters()
    me, enemy = (hero, broken(goblin)) if side == "hero" else (goblin, broken(hero))
    with caplog.at_level(logging.ERROR, logger="ai.strategy"):
        action = strategy().choose_action(
            me, {"allies": [me], "enemies": [enemy], "round": 1}
        )
    assert action == {"type": fallback}
    assert any(
        r.exc_info and "a bug in the rules" in str(r.exc_info[1])
        for r in caplog.records
    )


def test_in_tests_an_ai_error_is_raised():
    hero, goblin = fighters()
    with pytest.raises(RuntimeError, match="a bug in the rules"):
        PartyAIStrategy().choose_action(
            hero, {"allies": [hero], "enemies": [broken(goblin)], "round": 1}
        )
