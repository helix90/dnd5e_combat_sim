"""
Test spell slot consumption to ensure characters can't cast more spells than they have slots for.
"""
import pytest
from unittest.mock import MagicMock
from models.character import Character, normalize_spell_slots
from models.character_builder import build_party
from models.spell_manager import SpellManager
from models.spells import Spell, SpellAction
from utils.party_loader import PartyLoader


class TestSpellSlotConsumption:
    """Test that spell slots are properly consumed and enforced."""

    def test_spell_slots_consumed_correctly(self):
        """Test that casting a spell consumes a spell slot."""
        # Create a character with 2 first-level slots
        char = Character(
            name="Test Cleric",
            level=1,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 16, 'cha': 10},
            hp=10,
            ac=15,
            proficiency_bonus=2,
            spell_slots={'1': 2, '2': 0}
        )

        # Create a 1st level spell
        spell = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d8",
            healing=True
        )
        char.add_spell(spell)

        # Create spell action
        spell_action = SpellAction(spell, spell_slot_level=1)

        # Verify we have 2 slots
        assert char.spell_slots_remaining[1] == 2

        # Cast first spell
        target = MagicMock()
        target.name = "Ally"
        target.hp = 5
        target.max_hp = 20

        result1 = spell_action.execute(char, target)
        assert result1['success'] == True
        assert char.spell_slots_remaining[1] == 1  # Should have 1 slot left

        # Reset target HP for second cast
        target.hp = 5

        # Cast second spell
        result2 = spell_action.execute(char, target)
        assert result2['success'] == True
        assert char.spell_slots_remaining[1] == 0  # Should have 0 slots left

    def test_cannot_cast_without_spell_slots(self):
        """Test that characters cannot cast spells when they have no slots left."""
        # Create a character with 1 first-level slot
        char = Character(
            name="Test Cleric",
            level=1,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 16, 'cha': 10},
            hp=10,
            ac=15,
            proficiency_bonus=2,
            spell_slots={'1': 1}
        )

        # Create a 1st level spell
        spell = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d8",
            healing=True
        )
        char.add_spell(spell)

        # Create spell action
        spell_action = SpellAction(spell, spell_slot_level=1)

        target = MagicMock()
        target.name = "Ally"
        target.hp = 5
        target.max_hp = 20

        # Cast first spell - should succeed
        result1 = spell_action.execute(char, target)
        assert result1['success'] == True
        assert char.spell_slots_remaining[1] == 0

        # Reset target
        target.hp = 5

        # Try to cast second spell - should FAIL due to no slots
        result2 = spell_action.execute(char, target)
        assert result2['success'] == False
        assert result2['reason'] == 'No spell slot available'
        assert char.spell_slots_remaining[1] == 0  # Should still be 0

    def test_cantrips_dont_consume_slots(self):
        """Test that cantrips (level 0 spells) don't consume spell slots."""
        # Create a character
        char = Character(
            name="Test Wizard",
            level=1,
            character_class="Wizard",
            race="Human",
            ability_scores={'str': 10, 'dex': 10, 'con': 10, 'int': 16, 'wis': 10, 'cha': 10},
            hp=8,
            ac=12,
            proficiency_bonus=2,
            spell_slots={'1': 2}
        )

        # Create a cantrip (level 0)
        cantrip = Spell(
            name="Fire Bolt",
            level=0,  # Cantrip
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d10",
            damage_type="fire",
            is_attack_spell=True
        )
        char.add_spell(cantrip)

        # Create spell action
        spell_action = SpellAction(cantrip, spell_slot_level=None)

        target = MagicMock()
        target.name = "Enemy"
        target.hp = 20
        target.ac = 10

        # Cast cantrip multiple times
        for i in range(5):
            result = spell_action.execute(char, target)
            assert result['success'] == True
            # Spell slots should NOT be consumed
            assert char.spell_slots_remaining[1] == 2

    def test_spell_slot_string_keys_compatibility(self):
        """Test that spell slots work with both string and integer keys (JSON compatibility)."""
        # Create character with STRING keys (as loaded from JSON)
        char = Character(
            name="Test Cleric",
            level=3,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 16, 'cha': 10},
            hp=15,
            ac=15,
            proficiency_bonus=2,
            spell_slots={'1': '3', '2': '2'}  # STRING VALUES from JSON
        )

        assert char.spell_slots_remaining == {1: 3, 2: 2}

        spell = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d8",
            healing=True
        )
        char.add_spell(spell)

        spell_action = SpellAction(spell, spell_slot_level=1)

        target = MagicMock()
        target.name = "Ally"
        target.hp = 5
        target.max_hp = 20

        # Should be able to cast spell
        result = spell_action.execute(char, target)
        assert result['success'] == True

        assert char.spell_slots_remaining[1] == 2  # Started with 3, used 1

    def test_multiple_spell_levels(self):
        """Test that different spell levels consume their respective slots."""
        # Create character with multiple spell slot levels
        char = Character(
            name="Test Cleric",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 16, 'cha': 10},
            hp=30,
            ac=15,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3, '3': 2}
        )

        # Create spells of different levels
        cure_wounds = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d8",
            healing=True
        )

        lesser_restoration = Spell(
            name="Lesser Restoration",
            level=2,
            school="Abjuration",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            healing=True
        )

        char.add_spell(cure_wounds)
        char.add_spell(lesser_restoration)

        target = MagicMock()
        target.name = "Ally"
        target.hp = 10
        target.max_hp = 50

        # Cast 1st level spell
        spell_action_1 = SpellAction(cure_wounds, spell_slot_level=1)
        result1 = spell_action_1.execute(char, target)
        assert result1['success'] == True
        assert char.spell_slots_remaining[1] == 3  # 4 -> 3
        assert char.spell_slots_remaining[2] == 3  # Unchanged

        # Reset target
        target.hp = 10

        # Cast 2nd level spell
        spell_action_2 = SpellAction(lesser_restoration, spell_slot_level=2)
        result2 = spell_action_2.execute(char, target)
        assert result2['success'] == True
        assert char.spell_slots_remaining[1] == 3  # Unchanged
        assert char.spell_slots_remaining[2] == 2  # 3 -> 2

    def test_upcasting_consumes_higher_slot(self):
        """Test that upcasting a spell consumes the higher level slot."""
        # Create character
        char = Character(
            name="Test Cleric",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 16, 'cha': 10},
            hp=30,
            ac=15,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3, '3': 2}
        )

        # Create 1st level spell
        cure_wounds = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d8",
            healing=True
        )
        char.add_spell(cure_wounds)

        # Cast using a 2nd level slot (upcasting)
        spell_action = SpellAction(cure_wounds, spell_slot_level=2)

        target = MagicMock()
        target.name = "Ally"
        target.hp = 10
        target.max_hp = 50

        result = spell_action.execute(char, target)
        assert result['success'] == True
        assert char.spell_slots_remaining[1] == 4  # 1st level slots unchanged
        assert char.spell_slots_remaining[2] == 2  # 2nd level slot consumed (3 -> 2)


def test_spell_slots_from_json_use_int_keys_and_counts():
    assert normalize_spell_slots({'1': '4', '2': 3}) == {1: 4, 2: 3}
    assert normalize_spell_slots(None) == {}
    with pytest.raises(ValueError):
        normalize_spell_slots({'first': 2})


def test_party_casters_can_cast_leveled_spells():
    """Characters built from characters.json (string slot keys) can cast spells they have slots for."""
    party = build_party(PartyLoader.get_party_with_level(1, 5)['characters'], SpellManager())
    calyra = next(c for c in party if c.name == 'Calyra')
    assert calyra.spell_slots == calyra.spell_slots_remaining == {1: 4, 2: 3, 3: 2}
    assert calyra.spell_slots is not calyra.spell_slots_remaining
    assert calyra.can_cast_spell('Fireball')
    assert {'Magic Missile', 'Scorching Ray', 'Fireball'} <= set(calyra.get_available_spells())

    calyra.spell_slots_remaining[3] = 0
    assert not calyra.can_cast_spell('Fireball')
    assert calyra.can_cast_spell('Fireball', spell_slot_level=3) is False
    assert calyra.spell_slots[3] == 2  # the maximum is untouched
