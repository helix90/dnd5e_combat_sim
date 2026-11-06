"""Tests for party weapons, Extra Attack, Sneak Attack and cantrip use."""

import json
import os
from unittest.mock import patch

import pytest

from ai.strategy import PartyAIStrategy
from models.actions import AttackAction
from models.character import Character
from models.character_builder import build_character
from models.combat import Combat
from models.monster import Monster
from models.spell_manager import SpellManager
from models.weapons import weapon_type_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}
CHARACTERS = json.load(open(os.path.join(ROOT, "data", "characters.json")))
SPELLS = SpellManager(os.path.join(ROOT, "data", "spells.json"))


def character_data(name, level):
    entry = next(e for e in CHARACTERS if e["level"] == level)
    return next(c for c in entry["party"] if c["name"] == name)


def make_character(name="Hero", features=(), dex=10, str_=10):
    scores = dict(SCORES, dex=dex, str=str_)
    return Character(
        name,
        5,
        "Rogue",
        "Human",
        scores,
        hp=40,
        ac=12,
        proficiency_bonus=3,
        class_features=list(features),
    )


def make_goblin(name="Goblin", hp=50):
    return Monster(name, "1/4", hp, 10, SCORES)


def weapon(name="Shortsword", dice="1d6", weapon_type="finesse"):
    return AttackAction(
        name=name,
        description=name,
        weapon_name=name,
        damage_dice=dice,
        damage_type="piercing",
        weapon_type=weapon_type,
    )


def attack(combat, attacker, action, target):
    return combat._execute_action(
        attacker, {"type": "attack", "action": action, "target": target}
    )


@pytest.mark.parametrize(
    "name, cls, expected",
    [
        ("Shortsword", "Rogue", "finesse"),
        ("Rapier", "Bard", "finesse"),
        ("Longbow", "Ranger", "ranged"),
        ("Light Crossbow", "Fighter", "ranged"),
        ("Longsword", "Fighter", "melee"),
        ("Quarterstaff", "Wizard", "melee"),
        ("Quarterstaff", "Monk", "finesse"),
        ("Unarmed Strike", "Monk", "finesse"),
    ],
)
def test_weapon_types(name, cls, expected):
    assert weapon_type_for(name, cls) == expected


@pytest.mark.parametrize(
    "features, expected", [([], 1), (["Extra Attack"], 2), (["Extra Attack (2)"], 3)]
)
def test_attacks_per_action(features, expected):
    assert make_character(features=features).attacks_per_action() == expected


def test_sneak_attack_dice():
    assert make_character(features=["Sneak Attack (3d6)"]).sneak_attack_dice() == "3d6"
    assert (
        make_character(features=["Sneak Attack"]).sneak_attack_dice() == "3d6"
    )  # level 5
    assert make_character().sneak_attack_dice() is None


def test_level_5_party_built_from_data():
    aldric = build_character(character_data("Aldric", 5), SPELLS)
    assert aldric.attacks_per_action() == 2
    longsword = aldric.actions[0]
    assert (longsword.name, longsword.weapon_type, longsword.hit_bonus(aldric)) == (
        "Longsword",
        "melee",
        7,
    )

    dax = build_character(character_data("Dax", 5), SPELLS)
    assert dax.sneak_attack_dice() == "3d6"
    assert {a.name: a.weapon_type for a in dax.actions} == {
        "Shortsword": "finesse",
        "Shortbow": "ranged",
    }
    assert all(a.hit_bonus(dax) == 7 for a in dax.actions)

    # Fire Bolt is cast as a spell, not swung as a weapon
    calyra = build_character(character_data("Calyra", 5), SPELLS)
    assert [a.name for a in calyra.actions] == ["Quarterstaff"]
    assert calyra.spells["Fire Bolt"].level == 0


def test_every_character_has_a_weapon():
    for entry in CHARACTERS:
        for data in entry["party"]:
            assert build_character(
                data, SPELLS
            ).actions, f"{data['name']} level {entry['level']}"


def test_wizard_casts_fire_bolt_after_opening_rounds():
    calyra = build_character(character_data("Calyra", 5), SPELLS)
    action = PartyAIStrategy().choose_action(
        calyra, {"allies": [calyra], "enemies": [make_goblin()], "round": 6}
    )
    assert action["type"] == "cast_spell" and action["spell"].spell.name == "Fire Bolt"


def test_rogue_picks_higher_damage_weapon_on_tie():
    dax = build_character(character_data("Dax", 5), SPELLS)
    action = PartyAIStrategy().choose_action(
        dax, {"allies": [dax], "enemies": [make_goblin()], "round": 1}
    )
    assert action["action"].name in ("Shortsword", "Shortbow")  # both 1d6, +7


def test_extra_attack_makes_two_attacks():
    fighter, goblin = make_character(features=["Extra Attack"], str_=16), make_goblin()
    combat = Combat([fighter, goblin])
    with patch("random.randint", side_effect=[15, 5, 15, 6]):
        result = attack(combat, fighter, weapon("Longsword", "1d8", "melee"), goblin)
    assert result["extra_attack"] and len(result["attacks"]) == 2
    assert result["damage"] == (5 + 3) + (6 + 3) and goblin.hp == 50 - 17


def test_extra_attack_moves_to_next_enemy_when_target_drops():
    fighter = make_character(features=["Extra Attack"], str_=16)
    weak, other = make_goblin("Goblin 1", hp=5), make_goblin("Goblin 2")
    combat = Combat([fighter, weak, other])
    with patch("random.randint", side_effect=[15, 5, 15, 6]):
        result = attack(combat, fighter, weapon("Longsword", "1d8", "melee"), weak)
    assert weak.hp == 0 and other.hp == 50 - 9
    assert result["target"] == "Goblin 1, Goblin 2"


def test_sneak_attack_with_an_ally_once_per_turn():
    rogue = make_character(features=["Sneak Attack (3d6)", "Extra Attack"], dex=18)
    ally, goblin = make_character("Ally"), make_goblin()
    combat = Combat([rogue, ally, goblin])
    # hit (1d6=3) + sneak 3d6 (1+2+3), then a second hit with no sneak attack (1d6=4)
    with patch("random.randint", side_effect=[15, 3, 1, 2, 3, 15, 4]):
        result = attack(combat, rogue, weapon(), goblin)
    assert result["sneak_attack"] == 6
    assert result["damage"] == (3 + 4 + 6) + (4 + 4)


def test_no_sneak_attack_without_ally_or_advantage():
    rogue, goblin = (
        make_character(features=["Sneak Attack (3d6)"], dex=18),
        make_goblin(),
    )
    combat = Combat([rogue, goblin])
    with patch("random.randint", side_effect=[15, 3]):
        result = attack(combat, rogue, weapon(), goblin)
    assert "sneak_attack" not in result and result["damage"] == 7


def test_no_sneak_attack_with_heavy_melee_weapon():
    rogue, ally, goblin = (
        make_character(features=["Sneak Attack (3d6)"], str_=16),
        make_character("Ally"),
        make_goblin(),
    )
    combat = Combat([rogue, ally, goblin])
    with patch("random.randint", side_effect=[15, 3]):
        result = attack(combat, rogue, weapon("Greatclub", "1d8", "melee"), goblin)
    assert "sneak_attack" not in result
