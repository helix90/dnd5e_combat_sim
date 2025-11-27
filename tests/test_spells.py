"""
Unit tests for the spell system.

Tests the Spell class, SpellAction class, and spell casting mechanics.
"""

import pytest
import random
from unittest.mock import patch, MagicMock
from models.spells import Spell, SpellAction
from models.character import Character
from models.monster import Monster


class TestSpell:
    """Test the Spell class."""
    
    def test_spell_initialization(self):
        """Test spell initialization with all parameters."""
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex",
            description="A bright streak flashes from your pointing finger."
        )
        
        assert spell.name == "Fireball"
        assert spell.level == 3
        assert spell.school == "Evocation"
        assert spell.damage_dice == "8d6"
        assert spell.damage_type == "fire"
        assert spell.save_type == "dex"
        assert spell.is_attack_spell is False
        assert spell.healing is False
    
    def test_cantrip_initialization(self):
        """Test cantrip initialization."""
        spell = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d10",
            damage_type="fire",
            is_attack_spell=True
        )
        
        assert spell.level == 0
        assert spell.is_attack_spell is True
    
    def test_healing_spell_initialization(self):
        """Test healing spell initialization."""
        spell = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d8",
            healing=True
        )
        
        assert spell.healing is True
        assert spell.damage_type is None
    
    def test_spell_string_representation(self):
        """Test spell string representation."""
        spell = Spell(
            name="Magic Missile",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False}
        )
        
        assert str(spell) == "Magic Missile (Level 1, Evocation)"
        
        cantrip = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False}
        )
        
        assert str(cantrip) == "Fire Bolt (Cantrip, Evocation)"
    
    @patch('random.randint')
    def test_calculate_damage(self, mock_randint):
        """Test damage calculation."""
        mock_randint.return_value = 4  # Consistent roll for testing
        
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire"
        )
        
        # Test normal damage calculation
        damage = spell.calculate_damage()
        assert damage == 32  # 8 * 4 = 32
        mock_randint.assert_called_with(1, 6)
    
    @patch('random.randint')
    def test_cantrip_damage_scaling(self, mock_randint):
        """Test cantrip damage scaling with level."""
        mock_randint.return_value = 5  # Consistent roll for testing
        
        spell = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d10",
            damage_type="fire"
        )
        
        # Level 1-4: 1d10
        damage = spell.calculate_damage(1)
        assert damage == 5
        mock_randint.assert_called_with(1, 10)
        
        # Level 5-10: 2d10
        damage = spell.calculate_damage(5)
        assert damage == 10  # 2 * 5 = 10
        
        # Level 11-16: 3d10
        damage = spell.calculate_damage(11)
        assert damage == 15  # 3 * 5 = 15
        
        # Level 17+: 4d10
        damage = spell.calculate_damage(17)
        assert damage == 20  # 4 * 5 = 20
    
    def test_get_save_dc(self):
        """Test spell save DC calculation."""
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )
        
        # Mock character with spell_save_dc method
        mock_caster = MagicMock()
        mock_caster.spell_save_dc.return_value = 15
        
        save_dc = spell.get_save_dc(mock_caster)
        assert save_dc == 15
        
        # Test with save_dc_bonus
        spell.save_dc_bonus = 2
        save_dc = spell.get_save_dc(mock_caster)
        assert save_dc == 17
        
        # Test fallback when caster has no spell_save_dc method
        mock_caster_no_method = MagicMock()
        # Remove the spell_save_dc method to test fallback
        del mock_caster_no_method.spell_save_dc
        save_dc = spell.get_save_dc(mock_caster_no_method)
        assert save_dc == 10  # 8 + 2 (bonus)


class TestSpellAction:
    """Test the SpellAction class."""
    
    def test_spell_action_initialization(self):
        """Test SpellAction initialization."""
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )
        
        action = SpellAction(spell, spell_slot_level=3)
        
        assert action.spell == spell
        assert action.spell_slot_level == 3
        assert action.action_type == "spell"
        assert action.name == "Cast Fireball"
        assert action.description == spell.description
    
    def test_check_spell_slot_availability_cantrip(self):
        """Test spell slot availability for cantrips."""
        spell = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d10",
            damage_type="fire"
        )
        
        action = SpellAction(spell)
        
        # Cantrips should always be available
        mock_caster = MagicMock()
        assert action.check_spell_slot_availability(mock_caster) is True
        
        # Even if caster has no spell_slots attribute
        mock_caster_no_slots = MagicMock()
        del mock_caster_no_slots.spell_slots
        assert action.check_spell_slot_availability(mock_caster_no_slots) is True
    
    def test_check_spell_slot_availability_leveled_spell(self):
        """Test spell slot availability for leveled spells."""
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire"
        )
        
        action = SpellAction(spell, spell_slot_level=3)
        
        # Caster with available spell slot
        mock_caster = MagicMock()
        mock_caster.spell_slots_remaining = {3: 2}
        assert action.check_spell_slot_availability(mock_caster) is True
        
        # Caster with no spell slots
        mock_caster_no_slots = MagicMock()
        mock_caster_no_slots.spell_slots_remaining = {3: 0}
        assert action.check_spell_slot_availability(mock_caster_no_slots) is False
        
        # Caster with no spell_slots attribute
        mock_caster_no_attr = MagicMock()
        # Remove the spell_slots attribute to test fallback
        del mock_caster_no_attr.spell_slots
        assert action.check_spell_slot_availability(mock_caster_no_attr) is False

    def test_check_spell_slot_availability_with_string_keys(self):
        """Test spell slot availability with string keys (JSON compatibility regression test)."""
        # This tests the fix for the bug where JSON-loaded spell_slots have string keys
        # but spell levels are integers, causing lookups to fail
        spell = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d8",
            damage_type=None,
            healing=True
        )

        action = SpellAction(spell, spell_slot_level=1)

        # Caster with string keys (as loaded from JSON)
        mock_caster_string_keys = MagicMock()
        mock_caster_string_keys.spell_slots_remaining = {'1': 3, '2': 2}
        assert action.check_spell_slot_availability(mock_caster_string_keys) is True

        # Caster with integer keys (programmatically created)
        mock_caster_int_keys = MagicMock()
        mock_caster_int_keys.spell_slots_remaining = {1: 3, 2: 2}
        assert action.check_spell_slot_availability(mock_caster_int_keys) is True

        # Caster with no level 1 slots (string key)
        mock_caster_no_l1 = MagicMock()
        mock_caster_no_l1.spell_slots_remaining = {'1': 0, '2': 2}
        assert action.check_spell_slot_availability(mock_caster_no_l1) is False

    def test_consume_spell_slot_with_string_keys(self):
        """Test spell slot consumption with string keys (JSON compatibility regression test)."""
        spell = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d8",
            damage_type=None,
            healing=True
        )

        action = SpellAction(spell, spell_slot_level=1)

        # Test with string keys
        mock_caster_string = MagicMock()
        mock_caster_string.spell_slots_remaining = {'1': 3, '2': 2}
        assert action.consume_spell_slot(mock_caster_string) is True
        assert mock_caster_string.spell_slots_remaining['1'] == 2

        # Test with integer keys
        mock_caster_int = MagicMock()
        mock_caster_int.spell_slots_remaining = {1: 3, 2: 2}
        assert action.consume_spell_slot(mock_caster_int) is True
        assert mock_caster_int.spell_slots_remaining[1] == 2

        # Test consuming when slots are zero
        mock_caster_zero = MagicMock()
        mock_caster_zero.spell_slots_remaining = {'1': 0, '2': 2}
        assert action.consume_spell_slot(mock_caster_zero) is False
        assert mock_caster_zero.spell_slots_remaining['1'] == 0  # Should not go negative

    def test_consume_spell_slot(self):
        """Test spell slot consumption."""
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire"
        )
        
        action = SpellAction(spell, spell_slot_level=3)
        
        # Cantrips don't consume slots
        cantrip = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d10",
            damage_type="fire"
        )
        
        cantrip_action = SpellAction(cantrip)
        mock_caster = MagicMock()
        assert cantrip_action.consume_spell_slot(mock_caster) is True
        
        # Leveled spells consume slots
        mock_caster = MagicMock()
        mock_caster.spell_slots_remaining = {3: 2}
        
        assert action.consume_spell_slot(mock_caster) is True
        assert mock_caster.spell_slots_remaining[3] == 1
        
        # Try to consume when no slots available
        assert action.consume_spell_slot(mock_caster) is True
        assert mock_caster.spell_slots_remaining[3] == 0
        
        # Should fail when no slots left
        assert action.consume_spell_slot(mock_caster) is False
    
    @patch('random.randint')
    def test_execute_spell_attack(self, mock_randint):
        """Test executing a spell that requires an attack roll."""
        mock_randint.side_effect = [15, 6]  # Attack roll 15, damage roll 6
        
        spell = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d10",
            damage_type="fire",
            is_attack_spell=True
        )
        
        action = SpellAction(spell)
        
        mock_caster = MagicMock()
        mock_caster.spell_attack_bonus.return_value = 5
        mock_caster.level = 1
        
        mock_target = MagicMock()
        mock_target.ac = 18
        mock_target.hp = 20
        
        result = action.execute(mock_caster, mock_target)
        
        assert result['success'] is True
        assert result['spell'] == "Fire Bolt"
        assert result['attack_roll'] == 15
        assert result['attack_bonus'] == 5
        assert result['total_attack'] == 20
        assert result['target_ac'] == 18
        assert result['hit'] is True
        assert result['damage'] == 6
        assert result['damage_type'] == "fire"
        assert mock_target.hp == 14  # 20 - 6
    
    @patch('random.randint')
    def test_execute_spell_save(self, mock_randint):
        """Test executing a spell that requires a saving throw."""
        mock_randint.side_effect = [12, 4, 4, 4, 4, 4, 4, 4, 4]  # Save roll 12, damage rolls (8d6)
        
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )
        
        action = SpellAction(spell, spell_slot_level=3)
        
        mock_caster = MagicMock()
        mock_caster.spell_save_dc.return_value = 15
        mock_caster.level = 5
        mock_caster.spell_slots_remaining = {3: 2}
        
        mock_target = MagicMock()
        mock_target.saving_throw_bonus.return_value = 2
        mock_target.hp = 30
        
        result = action.execute(mock_caster, mock_target)
        
        assert result['success'] is True
        assert result['spell'] == "Fireball"
        assert result['save_type'] == "dex"
        assert result['save_dc'] == 15
        assert result['save_roll'] == 12
        assert result['save_bonus'] == 2
        assert result['total_save'] == 14
        assert result['save_success'] is False  # 14 < 15
        assert result['damage'] == 32  # 8 * 4 = 32
        assert result['damage_type'] == "fire"
        assert mock_target.hp == -2  # 30 - 32 = -2
    
    @patch('random.randint')
    def test_execute_spell_save_success_half_damage(self, mock_randint):
        """Test executing a spell with half damage on successful save."""
        mock_randint.side_effect = [16, 4, 4, 4, 4, 4, 4, 4, 4]  # Save roll 16, damage rolls (8d6)
        
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )
        
        action = SpellAction(spell, spell_slot_level=3)
        
        mock_caster = MagicMock()
        mock_caster.spell_save_dc.return_value = 15
        mock_caster.level = 5
        mock_caster.spell_slots_remaining = {3: 2}
        
        mock_target = MagicMock()
        mock_target.saving_throw_bonus.return_value = 2
        mock_target.hp = 30
        
        result = action.execute(mock_caster, mock_target)
        
        assert result['save_success'] is True  # 18 >= 15
        assert result['damage'] == 16  # 32 // 2
        assert mock_target.hp == 14  # 30 - 16
    
    @patch('random.randint')
    def test_execute_healing_spell(self, mock_randint):
        """Test executing a healing spell."""
        mock_randint.return_value = 6  # Healing roll 6
        
        spell = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d8",
            healing=True
        )
        
        action = SpellAction(spell, spell_slot_level=1)
        
        mock_caster = MagicMock()
        mock_caster.level = 3
        mock_caster.spell_slots_remaining = {1: 2}
        
        mock_target = MagicMock()
        mock_target.hp = 5
        mock_target.max_hp = 20
        
        result = action.execute(mock_caster, mock_target)
        
        assert result['success'] is True
        assert result['healing'] == 6
        assert mock_target.hp == 11  # 5 + 6
    
    def test_execute_spell_no_slots_available(self):
        """Test executing a spell when no spell slots are available."""
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire"
        )
        
        action = SpellAction(spell, spell_slot_level=3)
        
        mock_caster = MagicMock()
        mock_caster.spell_slots_remaining = {3: 0}
        
        mock_target = MagicMock()
        
        result = action.execute(mock_caster, mock_target)
        
        assert result['success'] is False
        assert result['reason'] == 'No spell slot available'


class TestCharacterSpellCasting:
    """Test character spell casting capabilities."""
    
    def test_spellcasting_ability_determination(self):
        """Test spellcasting ability determination by class."""
        # Test Wizard (Intelligence)
        wizard = Character(
            name="Gandalf",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={"str": 10, "dex": 14, "con": 12, "int": 18, "wis": 12, "cha": 10},
            hp=30,
            ac=15,
            proficiency_bonus=3
        )
        assert wizard.spellcasting_ability() == "int"
        
        # Test Cleric (Wisdom)
        cleric = Character(
            name="Pelor",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={"str": 14, "dex": 10, "con": 12, "int": 10, "wis": 18, "cha": 12},
            hp=35,
            ac=16,
            proficiency_bonus=3
        )
        assert cleric.spellcasting_ability() == "wis"
        
        # Test Bard (Charisma)
        bard = Character(
            name="Lute",
            level=5,
            character_class="Bard",
            race="Human",
            ability_scores={"str": 10, "dex": 14, "con": 12, "int": 12, "wis": 10, "cha": 18},
            hp=30,
            ac=14,
            proficiency_bonus=3
        )
        assert bard.spellcasting_ability() == "cha"
    
    def test_spell_attack_bonus_calculation(self):
        """Test spell attack bonus calculation."""
        wizard = Character(
            name="Gandalf",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={"str": 10, "dex": 14, "con": 12, "int": 18, "wis": 12, "cha": 10},
            hp=30,
            ac=15,
            proficiency_bonus=3
        )
        
        # Int modifier: (18 - 10) // 2 = 4
        # Spell attack bonus: 4 + 3 = 7
        assert wizard.spell_attack_bonus() == 7
    
    def test_spell_save_dc_calculation(self):
        """Test spell save DC calculation."""
        wizard = Character(
            name="Gandalf",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={"str": 10, "dex": 14, "con": 12, "int": 18, "wis": 12, "cha": 10},
            hp=30,
            ac=15,
            proficiency_bonus=3
        )
        
        # Spell save DC: 8 + 3 + 4 = 15
        assert wizard.spell_save_dc() == 15
    
    def test_add_and_get_spell(self):
        """Test adding and retrieving spells."""
        character = Character(
            name="Gandalf",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={"str": 10, "dex": 14, "con": 12, "int": 18, "wis": 12, "cha": 10},
            hp=30,
            ac=15,
            proficiency_bonus=3
        )
        
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )
        
        character.add_spell(spell)
        
        assert "Fireball" in character.spell_list
        assert character.get_spell("Fireball") == spell
        assert character.get_spell("Unknown Spell") is None
    
    def test_can_cast_spell(self):
        """Test spell casting availability."""
        character = Character(
            name="Gandalf",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={"str": 10, "dex": 14, "con": 12, "int": 18, "wis": 12, "cha": 10},
            hp=30,
            ac=15,
            proficiency_bonus=3,
            spell_slots={1: 4, 2: 3, 3: 2}
        )
        
        # Add a cantrip
        cantrip = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d10",
            damage_type="fire",
            is_attack_spell=True
        )
        character.add_spell(cantrip)
        
        # Add a leveled spell
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )
        character.add_spell(spell)
        
        # Cantrips can always be cast
        assert character.can_cast_spell("Fire Bolt") is True
        
        # Leveled spells need spell slots
        assert character.can_cast_spell("Fireball") is True
        assert character.can_cast_spell("Fireball", spell_slot_level=3) is True
        assert character.can_cast_spell("Fireball", spell_slot_level=4) is False
        
        # Unknown spells can't be cast
        assert character.can_cast_spell("Unknown Spell") is False
    
    @patch('random.randint')
    def test_cast_spell(self, mock_randint):
        """Test casting a spell."""
        mock_randint.side_effect = [12, 4, 4, 4, 4, 4, 4, 4, 4]  # Save roll 12, damage rolls (8d6)
        
        character = Character(
            name="Gandalf",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={"str": 10, "dex": 14, "con": 12, "int": 18, "wis": 12, "cha": 10},
            hp=30,
            ac=15,
            proficiency_bonus=3,
            spell_slots={1: 4, 2: 3, 3: 2}
        )
        
        spell = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )
        character.add_spell(spell)
        
        target = Character(
            name="Goblin",
            level=1,
            character_class="Monster",
            race="Goblin",
            ability_scores={"str": 8, "dex": 14, "con": 10, "int": 8, "wis": 8, "cha": 8},
            hp=20,
            ac=12,
            proficiency_bonus=2
        )
        
        result = character.cast_spell("Fireball", target)
        
        assert result['success'] is True
        assert result['spell'] == "Fireball"
        assert result['spell_level'] == 3
        assert result['damage'] == 32  # 8 * 4 = 32
        assert result['damage_type'] == "fire"
        assert target.hp == -12  # 20 - 32 = -12
        
        # Check that spell slot was consumed
        assert character.spell_slots_remaining[3] == 1
    
    def test_get_available_spells(self):
        """Test getting available spells."""
        character = Character(
            name="Gandalf",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={"str": 10, "dex": 14, "con": 12, "int": 18, "wis": 12, "cha": 10},
            hp=30,
            ac=15,
            proficiency_bonus=3,
            spell_slots={1: 4, 2: 3, 3: 0}  # No level 3 slots
        )
        
        # Add spells
        cantrip = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d10",
            damage_type="fire",
            is_attack_spell=True
        )
        character.add_spell(cantrip)
        
        spell1 = Spell(
            name="Magic Missile",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": False},
            damage_dice="1d4+1",
            damage_type="force"
        )
        character.add_spell(spell1)
        
        spell3 = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={"verbal": True, "somatic": True, "material": True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )
        character.add_spell(spell3)
        
        available = character.get_available_spells()
        
        # Should include cantrip and level 1 spell, but not level 3 (no slots)
        assert "Fire Bolt" in available
        assert "Magic Missile" in available
        assert "Fireball" not in available 

def test_spell_from_api_success(monkeypatch):
    from models.spells import Spell
    from utils.api_client import APIClient
    class DummyAPIClient(APIClient):
        def __init__(self):
            pass
        def fetch_spell_data(self, name):
            return {
                'name': 'Fireball', 'level': 3, 'school': 'Evocation', 'casting_time': '1 action',
                'range': '150 feet', 'duration': 'Instantaneous', 'components': 'V,S,M',
                'damage_dice': '8d6', 'damage_type': 'fire', 'desc': 'A bright streak...',
                'attack_type': 'ranged', 'concentration': 'no'
            }
    spell = Spell.from_api('Fireball', api_client=DummyAPIClient())
    assert spell.name == 'Fireball'
    assert spell.level == 3
    assert spell.damage_dice == '8d6'
    assert spell.damage_type == 'fire'
    assert spell.is_attack_spell
    assert not spell.concentration

def test_spell_from_api_fallback(monkeypatch):
    from models.spells import Spell
    from utils.api_client import APIClient
    class DummyFallback:
        def __init__(self):
            self.called = False
        def get_local_data(self, data_type, name):
            if data_type == 'spells' and name.lower() == 'magic missile':
                self.called = True
                return {
                    'name': 'Magic Missile', 'level': 1, 'school': 'Evocation', 'casting_time': '1 action',
                    'range': '120 feet', 'duration': 'Instantaneous', 'components': 'V,S',
                    'damage_dice': '1d4+1', 'damage_type': 'force', 'desc': 'Three glowing darts...',
                    'attack_type': 'ranged', 'concentration': 'no'
                }
            return None
    class DummyAPIClient(APIClient):
        def __init__(self):
            self.fallback_handler = DummyFallback()
        def fetch_spell_data(self, name):
            # Simulate API failure, so fallback is used
            return self.fallback_handler.get_local_data('spells', name)
    dummy_api_client = DummyAPIClient()
    spell = Spell.from_api('Magic Missile', api_client=dummy_api_client)
    assert spell.name == 'Magic Missile'
    assert spell.level == 1
    assert spell.damage_type == 'force'
    assert dummy_api_client.fallback_handler.called, "Fallback handler was not called!"

def test_spell_from_api_not_found(monkeypatch):
    from models.spells import Spell
    from utils.api_client import APIClient
    from utils.exceptions import APIError
    class DummyFallback:
        def get_local_data(self, data_type, name):
            return None
    class DummyAPIClient(APIClient):
        def __init__(self):
            self.fallback_handler = DummyFallback()
        def fetch_spell_data(self, name):
            return None
    with pytest.raises(APIError):
        Spell.from_api('Nonexistent Spell', api_client=DummyAPIClient()) 