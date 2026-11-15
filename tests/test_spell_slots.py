"""Spell slots: a spell is cast with a slot of its level or higher, never lower, and every way
of spending one (spells, Divine Smite, Mage Armor before the fight) goes through spell_slots."""

import pytest

from models import class_features, spell_effects, spell_slots
from models.character import Character
from models.spell_manager import SpellManager
from models.spells import SpellAction

SPELLS = SpellManager()


def caster(slots, cls="Wizard", spells=(), dex=10, ac=10):
    character = Character(
        name="Caster",
        level=9,
        character_class=cls,
        race="Human",
        ability_scores={"str": 10, "dex": dex, "con": 10, "int": 16, "wis": 16, "cha": 16},
        hp=50,
        ac=ac,
        proficiency_bonus=4,
        spell_slots=slots,
    )
    for name in spells:
        character.add_spell(SPELLS.get_spell(name))
    return character


def test_json_slots_become_int_keys():
    assert caster({"1": "4", "3": 2}).spell_slots_remaining == {1: 4, 3: 2}


def test_a_lower_slot_cant_cast_a_higher_spell():
    wizard = caster({1: 4, 3: 0}, spells=["Fireball"])
    fireball = SpellAction(SPELLS.get_spell("Fireball"), spell_slot_level=1)
    assert not fireball.check_spell_slot_availability(wizard)
    assert not fireball.consume_spell_slot(wizard)
    assert not wizard.can_cast_spell("Fireball", spell_slot_level=1)
    assert wizard.spell_slots_remaining == {1: 4, 3: 0}
    result = fireball.execute(wizard, caster({}))
    assert result["success"] is False and result["reason"] == "No spell slot available"


def test_a_higher_slot_can_cast_a_lower_spell():
    wizard = caster({1: 0, 2: 1}, spells=["Magic Missile"])
    missile = SpellAction(SPELLS.get_spell("Magic Missile"), spell_slot_level=2)
    assert wizard.can_cast_spell("Magic Missile", spell_slot_level=2)
    assert wizard.can_cast_spell("Magic Missile")  # with the 2nd-level slot
    wizard.spell_list = ["Magic Missile"]
    assert wizard.get_available_spells() == ["Magic Missile"]
    assert missile.consume_spell_slot(wizard)
    assert wizard.spell_slots_remaining == {1: 0, 2: 0}
    assert not missile.consume_spell_slot(wizard)  # never below zero
    assert not wizard.can_cast_spell("Magic Missile")
    assert wizard.spell_slots_remaining[2] == 0


def test_cantrips_need_no_slot():
    assert spell_slots.can_spend(caster({}), 0) and spell_slots.spend(caster({}), 0)


@pytest.mark.parametrize("creature", [object(), type("NoDict", (), {"spell_slots_remaining": None})()])
def test_a_creature_without_slots_has_none(creature):
    assert spell_slots.remaining(creature) == {}
    assert spell_slots.lowest_slot(creature, 1) is None
    assert not spell_slots.spend(creature, 1)


def test_lowest_slot_skips_spent_and_lower_levels():
    wizard = caster({1: 0, 2: 3, 3: 1})
    assert spell_slots.lowest_slot(wizard, 1) == 2
    assert spell_slots.lowest_slot(wizard, 3) == 3
    assert spell_slots.lowest_slot(wizard, 4) is None


def test_divine_smite_spends_its_slot():
    paladin = caster({1: 0, 2: 2}, cls="Paladin")
    paladin.class_features = ["Divine Smite"]
    target = caster({})
    assert class_features.smite_slot(paladin) == 2
    attack = {"hit": True, "damage": 5}
    class_features.divine_smite(paladin, attack, target, 2)
    assert paladin.spell_slots_remaining == {1: 0, 2: 1}
    assert attack["divine_smite"]["slot_level"] == 2
    with pytest.raises(ValueError):
        class_features.divine_smite(paladin, attack, target, 1)


def test_mage_armor_before_the_fight_spends_a_first_level_slot():
    wizard = caster({1: 2}, spells=["Mage Armor"], dex=14)
    assert spell_effects.prepare(wizard) is not None
    assert wizard.spell_slots_remaining == {1: 1}

    spent = caster({1: 0, 2: 3}, spells=["Mage Armor"], dex=14)
    assert spell_effects.prepare(spent) is None
    assert spent.spell_slots_remaining == {1: 0, 2: 3}
