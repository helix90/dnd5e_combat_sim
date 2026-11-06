"""Tests for d20 rolls with advantage and disadvantage."""

from unittest.mock import patch

from models.actions import AttackAction
from models.buffs import Buff, create_haste_buff, create_paralyzed_condition
from models.character import Character
from models.monster import Monster
from models.rolls import attack_roll, roll_d20, roll_saving_throw
from models.spells import Spell, SpellAction

SCORES = {"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10}


def make_hero(name="Hero"):
    return Character(
        name, 1, "Wizard", "Human", SCORES, hp=20, ac=10, proficiency_bonus=2
    )


def effect(**metadata):
    return Buff(name="Effect", source="Test", duration_rounds=10, metadata=metadata)


def test_straight_roll_uses_one_die():
    with patch("random.randint", side_effect=[7]):
        d20 = roll_d20()
    assert (d20.result, d20.rolls, d20.advantage, d20.disadvantage) == (
        7,
        [7],
        False,
        False,
    )


def test_advantage_keeps_higher_and_disadvantage_keeps_lower():
    with patch("random.randint", side_effect=[4, 17]):
        assert roll_d20(advantage=True).result == 17
    with patch("random.randint", side_effect=[4, 17]):
        assert roll_d20(disadvantage=True).result == 4


def test_advantage_and_disadvantage_cancel():
    with patch("random.randint", side_effect=[9]) as randint:
        d20 = roll_d20(advantage=True, disadvantage=True)
    assert d20.result == 9 and randint.call_count == 1
    assert not d20.advantage and not d20.disadvantage


def test_attack_roll_combines_attacker_and_target_effects():
    attacker, target = make_hero("Attacker"), make_hero("Target")
    attacker.buffs.add_buff(effect(advantage=["attack_rolls"]))
    with patch("random.randint", side_effect=[3, 15]):
        assert attack_roll(attacker, target).advantage
    # A second advantage source doesn't stack; disadvantage on the target cancels both
    target.buffs.add_buff(create_paralyzed_condition("Ghoul", "con", 10))
    target.buffs.add_buff(effect(disadvantage=["attacks_against"]))
    with patch("random.randint", side_effect=[3]) as randint:
        d20 = attack_roll(attacker, target)
    assert d20.result == 3 and randint.call_count == 1


def test_attack_action_accepts_explicit_advantage():
    hero, goblin = make_hero(), Monster("Goblin", "1/4", 7, 15, SCORES)
    sword = AttackAction(
        name="Sword",
        description="",
        weapon_name="Sword",
        damage_dice="1d8",
        damage_type="slashing",
        hit_bonus=4,
    )
    with patch("random.randint", side_effect=[2, 19, 5]):
        result = sword.execute(hero, goblin, advantage=True)
    assert result["advantage"] and result["attack_rolls"] == [2, 19] and result["hit"]


def test_haste_grants_advantage_on_dex_saves_only():
    hero = make_hero()
    hero.buffs.add_buff(create_haste_buff("Wizard"))
    with patch("random.randint", side_effect=[3, 18]):
        save = roll_saving_throw(hero, "dex", 15)
    assert save["advantage"] and save["save_roll"] == 18 and save["save_success"]
    with patch("random.randint", side_effect=[3]):
        save = roll_saving_throw(hero, "con", 15)
    assert not save["advantage"] and not save["save_success"]


def test_disadvantage_on_all_saves():
    hero = make_hero()
    hero.buffs.add_buff(effect(disadvantage=["saving_throws"]))
    for ability in ("str", "wis"):
        with patch("random.randint", side_effect=[18, 3]):
            save = roll_saving_throw(hero, ability, 10)
        assert save["disadvantage"] and save["save_roll"] == 3


def test_spell_attacks_and_saves_use_advantage_rules():
    caster, target = make_hero("Caster"), make_hero("Target")
    target.buffs.add_buff(create_paralyzed_condition("Ghoul", "con", 10))
    fire_bolt = Spell(
        name="Fire Bolt",
        level=0,
        school="Evocation",
        casting_time="1 action",
        range="120 feet",
        duration="Instantaneous",
        components={"verbal": True, "somatic": True, "material": False},
        damage_dice="1d10",
        damage_type="fire",
        is_attack_spell=True,
    )
    with patch("random.randint", side_effect=[2, 16, 6]):
        result = SpellAction(fire_bolt).execute(caster, target)
    assert result["advantage"] and result["attack_roll"] == 16

    sacred_flame = Spell(
        name="Sacred Flame",
        level=0,
        school="Evocation",
        casting_time="1 action",
        range="60 feet",
        duration="Instantaneous",
        components={"verbal": True, "somatic": True, "material": False},
        damage_dice="1d8",
        damage_type="radiant",
        save_type="dex",
    )
    with patch("random.randint", return_value=20):
        result = SpellAction(sacred_flame).execute(caster, target)
    assert result["auto_fail"] and not result["save_success"]


def test_natural_one_always_misses():
    from models.rolls import attack_hits

    assert not attack_hits(1, 30, 5)
    assert attack_hits(2, 5, 5) and not attack_hits(2, 4, 5)


def test_weapon_attack_natural_one_misses_even_with_huge_bonus():
    hero, goblin = make_hero(), Monster("Goblin", "1/4", 7, 1, SCORES)
    sword = AttackAction(
        name="Sword",
        description="",
        weapon_name="Sword",
        damage_dice="1d8",
        damage_type="slashing",
        hit_bonus=20,
    )
    with patch("random.randint", side_effect=[1]):
        result = sword.execute(hero, goblin)
    assert not result["hit"] and goblin.hp == 7
    # With advantage the other die counts; with disadvantage the 1 does
    with patch("random.randint", side_effect=[1, 10, 4]):
        assert sword.execute(hero, goblin, advantage=True)["hit"]
    with patch("random.randint", side_effect=[20, 1]):
        assert not sword.execute(hero, goblin, disadvantage=True)["hit"]


def test_spell_attack_natural_one_misses():
    caster, goblin = make_hero("Caster"), Monster("Goblin", "1/4", 7, 1, SCORES)
    fire_bolt = Spell(
        name="Fire Bolt",
        level=0,
        school="Evocation",
        casting_time="1 action",
        range="120 feet",
        duration="Instantaneous",
        components={"verbal": True, "somatic": True, "material": False},
        damage_dice="1d10",
        damage_type="fire",
        is_attack_spell=True,
    )
    with patch("random.randint", side_effect=[1]):
        result = SpellAction(fire_bolt).execute(caster, goblin)
    assert not result["hit"] and goblin.hp == 7
