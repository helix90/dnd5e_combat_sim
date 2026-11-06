"""Tests for Undead Fortitude and Pack Tactics."""

from unittest.mock import patch

import pytest

from models.actions import AttackAction
from models.buffs import create_paralyzed_condition
from models.character import Character
from models.combat import Combat
from models.damage import apply_damage
from models.monster import Monster

SCORES = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def make_zombie(hp=5):
    zombie = Monster(
        "Zombie", "1/4", 22, 8, SCORES, special_abilities=["Undead Fortitude"]
    )
    zombie.hp = hp
    return zombie


def make_kobold(name="Kobold"):
    dagger = AttackAction(
        name="Dagger",
        description="",
        weapon_name="Dagger",
        damage_dice="1d4+2",
        damage_type="piercing",
        weapon_type="finesse",
    )
    return Monster(
        name, "1/8", 5, 12, SCORES, special_abilities=["Pack Tactics"], actions=[dagger]
    )


def make_hero(name="Hero"):
    return Character(
        name, 1, "Fighter", "Human", SCORES, hp=30, ac=5, proficiency_bonus=2
    )


@pytest.mark.parametrize("save_roll, hp_after", [(20, 1), (2, 0)])
def test_undead_fortitude_save(save_roll, hp_after):
    zombie = make_zombie()
    with patch("random.randint", return_value=save_roll):
        assert apply_damage(zombie, 7, "slashing") == 7
    assert zombie.hp == hp_after
    entry = zombie.pending_log_entries[0]
    assert (
        entry["action"] == "Undead Fortitude" and "DC 12" in entry["description"]
    )  # 5 + 7 damage


@pytest.mark.parametrize(
    "damage_type, critical", [("radiant", False), ("slashing", True)]
)
def test_no_undead_fortitude_against_radiant_or_crits(damage_type, critical):
    zombie = make_zombie()
    with patch("random.randint", return_value=20):
        apply_damage(zombie, 7, damage_type, critical)
    assert zombie.hp == 0 and zombie.pending_log_entries == []


def test_no_undead_fortitude_when_not_dropped_to_zero_or_already_down():
    zombie = make_zombie(hp=10)
    apply_damage(zombie, 3, "slashing")
    downed = make_zombie(hp=0)
    apply_damage(downed, 3, "slashing")
    assert zombie.hp == 7 and downed.hp == 0
    assert zombie.pending_log_entries == [] and downed.pending_log_entries == []


def test_undead_fortitude_is_logged_after_the_attack():
    hero, zombie = make_hero(), make_zombie()
    sword = AttackAction(
        name="Longsword",
        description="",
        weapon_name="Longsword",
        damage_dice="1d8",
        damage_type="slashing",
    )
    hero.actions = [sword]
    combat = Combat([hero, zombie])
    combat.initiative_order = [hero, zombie]
    combat.current_round = 3
    # d20 to hit, 1d8 damage, then the zombie's CON save
    with patch("random.randint", side_effect=[15, 6, 20]):
        combat.next_turn()
    log = [e for e in combat.get_combat_log() if e["type"] == "action"]
    assert [e["actor"] for e in log[-2:]] == ["Hero", "Zombie"]
    assert log[-1]["result"]["condition"] == "undead_fortitude" and zombie.hp == 1
    assert not combat.is_combat_over()


def attack_with(combat, kobold, target):
    return combat._execute_action(
        kobold, {"type": "attack", "action": kobold.actions[0], "target": target}
    )


def test_pack_tactics_gives_advantage_with_an_ally():
    kobold, ally, hero = make_kobold(), make_kobold("Kobold 2"), make_hero()
    combat = Combat([hero, kobold, ally])
    with patch("random.randint", side_effect=[3, 18, 2]):
        result = attack_with(combat, kobold, hero)
    assert result["advantage"] and result["attack_roll"] == 18


def test_no_pack_tactics_alone_or_with_incapacitated_ally():
    kobold, hero = make_kobold(), make_hero()
    combat = Combat([hero, kobold])
    with patch("random.randint", side_effect=[3, 2]):
        assert not attack_with(combat, kobold, hero)["advantage"]

    ally = make_kobold("Kobold 2")
    ally.buffs.add_buff(create_paralyzed_condition("Ghoul", "con", 10))
    combat = Combat([hero, kobold, ally])
    with patch("random.randint", side_effect=[3, 2]):
        assert not attack_with(combat, kobold, hero)["advantage"]


def test_monsters_without_pack_tactics_roll_normally():
    goblin, ally, hero = make_kobold("Goblin"), make_kobold("Goblin 2"), make_hero()
    goblin.special_abilities = []
    combat = Combat([hero, goblin, ally])
    with patch("random.randint", side_effect=[3, 2]):
        assert not attack_with(combat, goblin, hero)["advantage"]
