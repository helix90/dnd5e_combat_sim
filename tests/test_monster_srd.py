"""The monsters corrected against the SRD 5.1 stat blocks keep the SRD's numbers: to-hit
bonuses, damage, defenses and the riders on their hits."""

import copy
import json
from unittest.mock import patch

import pytest

from models.actions import AttackAction
from models.character import Character
from models.monster_builder import build_monster
from utils.paths import data_path

MONSTERS = {
    m["name"]: m for m in json.load(open(data_path("monsters.json")))["monsters"]
}
FAIL = {"save_success": False, "total_save": 1}


def monster(name):
    return build_monster(copy.deepcopy(MONSTERS[name]))


def attack(creature, name):
    return next(a for a in creature.actions if a.name == name)


@pytest.mark.parametrize(
    "name, action, to_hit, dice, damage_type",
    [
        ("Kobold", "Dagger", 4, "1d4+2", "piercing"),
        ("Kobold", "Sling", 4, "1d4+2", "bludgeoning"),
        ("Ghoul", "Bite", 2, "2d6+2", "piercing"),
        ("Ghoul", "Claws", 4, "2d4+2", "slashing"),
        ("Wight", "Longsword", 4, "1d8+2", "slashing"),
        ("Wight", "Life Drain", 4, "1d6+2", "necrotic"),
        ("Wight", "Longbow", 4, "1d8+2", "piercing"),
        ("Wraith", "Life Drain", 6, "4d8+3", "necrotic"),
        ("Hill Giant", "Greatclub", 8, "3d8+5", "bludgeoning"),
        ("Hill Giant", "Rock", 8, "3d10+5", "bludgeoning"),
        ("Vampire Spawn", "Bite", 6, "1d6+3", "piercing"),
        ("Mummy", "Rotting Fist", 5, "2d6+3", "bludgeoning"),
    ],
)
def test_attacks_match_the_srd(name, action, to_hit, dice, damage_type):
    creature = monster(name)
    a = attack(creature, action)
    assert a.hit_bonus(creature) == to_hit
    assert (a.damage_dice, a.damage_type) == (dice, damage_type)


@pytest.mark.parametrize(
    "name, action, extra",
    [
        ("Vampire Spawn", "Bite", {"dice": "2d6", "type": "necrotic"}),
        ("Mummy", "Rotting Fist", {"dice": "3d6", "type": "necrotic"}),
        ("Erinyes", "Longsword", {"dice": "3d8", "type": "poison"}),
    ],
)
def test_extra_damage_matches_the_srd(name, action, extra):
    assert attack(monster(name), action).extra_damage == extra


def test_defenses_match_the_srd():
    assert MONSTERS["Ghoul"]["damage_resistances"] == []
    assert set(MONSTERS["Wight"]["damage_resistances"]) == {
        "necrotic",
        "bludgeoning",
        "piercing",
        "slashing",
    }
    assert MONSTERS["Vampire Spawn"]["damage_immunities"] == []


def test_ghoul_claws_paralyze_but_not_undead_and_the_bite_never_does():
    ghoul = monster("Ghoul")
    assert attack(ghoul, "Bite").on_hit is None
    claws = attack(ghoul, "Claws")
    undead = build_monster(copy.deepcopy(MONSTERS["Zombie"]))
    undead.hp = 100  # survives the hit, so its immunity is what stops the paralysis
    hero = Character(
        "Hero",
        5,
        "Fighter",
        "Human",
        {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        hp=40,
        ac=10,
        proficiency_bonus=3,
    )
    with patch("models.actions.roll_saving_throw", return_value=FAIL), patch(
        "models.rolls.random.randint", return_value=15
    ):
        assert claws.execute(ghoul, undead)["effect_immune"] is True
        assert claws.execute(ghoul, hero)["condition_applied"] == "Paralyzed"


def test_every_monster_attack_builds():
    for name in MONSTERS:
        for a in monster(name).actions:
            if isinstance(a, AttackAction):
                assert a.damage_dice
