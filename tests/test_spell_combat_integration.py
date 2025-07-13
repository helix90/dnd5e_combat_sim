"""
Integration tests for spell casting in combat.

Tests spell casting mechanics integrated with the combat system.
"""

import pytest
from unittest.mock import patch
from models.character import Character
from models.monster import Monster
from models.combat import Combat, CombatLogger
from models.spells import Spell
from models.spell_manager import SpellManager


class TestSpellCombatIntegration:
    """Test spell casting integrated with combat system."""
    
    def setup_method(self):
        """Set up test data."""
        # Create spell manager and load spells
        self.spell_manager = SpellManager()
        
        # Create spell-casting characters
        self.wizard = Character(
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
        
        self.cleric = Character(
            name="Pelor",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={"str": 14, "dex": 10, "con": 12, "int": 10, "wis": 18, "cha": 12},
            hp=35,
            ac=16,
            proficiency_bonus=3,
            spell_slots={1: 4, 2: 3, 3: 2}
        )
        
        # Create monsters
        self.goblin = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=15,
            ac=12,
            ability_scores={"str": 8, "dex": 14, "con": 10, "int": 8, "wis": 8, "cha": 8},
            actions=[]
        )
        
        self.orc = Monster(
            name="Orc",
            challenge_rating="1/2",
            hp=25,
            ac=14,
            ability_scores={"str": 16, "dex": 12, "con": 14, "int": 7, "wis": 11, "cha": 10},
            actions=[]
        )
    
    def test_add_spells_to_characters(self):
        """Test adding spells to characters."""
        # Add spells to wizard
        fireball = self.spell_manager.get_spell("Fireball")
        fire_bolt = self.spell_manager.get_spell("Fire Bolt")
        magic_missile = self.spell_manager.get_spell("Magic Missile")
        
        self.wizard.add_spell(fireball)
        self.wizard.add_spell(fire_bolt)
        self.wizard.add_spell(magic_missile)
        
        # Add spells to cleric
        cure_wounds = self.spell_manager.get_spell("Cure Wounds")
        sacred_flame = self.spell_manager.get_spell("Sacred Flame")
        healing_word = self.spell_manager.get_spell("Healing Word")
        
        self.cleric.add_spell(cure_wounds)
        self.cleric.add_spell(sacred_flame)
        self.cleric.add_spell(healing_word)
        
        # Verify spells were added
        assert "Fireball" in self.wizard.spell_list
        assert "Fire Bolt" in self.wizard.spell_list
        assert "Magic Missile" in self.wizard.spell_list
        
        assert "Cure Wounds" in self.cleric.spell_list
        assert "Sacred Flame" in self.cleric.spell_list
        assert "Healing Word" in self.cleric.spell_list
    
    @patch('random.randint')
    def test_combat_with_spell_casting(self, mock_randint):
        """Test a combat scenario with spell casting."""
        # Set up mock to return different values for different rolls
        def mock_randint_side_effect(a, b):
            if a == 1 and b == 20:  # Initiative rolls
                return 10  # All participants get same initiative
            elif a == 1 and b == 6:  # Damage dice
                return 4   # Each d6 returns 4
            elif a == 1 and b == 8:  # Sacred Flame damage
                return 6   # d8 returns 6
            else:  # Save rolls
                return 8   # Default save roll
        mock_randint.side_effect = mock_randint_side_effect
        
        # Add spells to characters
        fireball = self.spell_manager.get_spell("Fireball")
        sacred_flame = self.spell_manager.get_spell("Sacred Flame")
        
        self.wizard.add_spell(fireball)
        self.cleric.add_spell(sacred_flame)
        
        # Debug: Check initial spell slots
        print(f"Wizard spell slots before: {self.wizard.spell_slots_remaining}")
        print(f"Cleric spell slots before: {self.cleric.spell_slots_remaining}")
        
        # Create combat with participants
        combat = Combat([self.wizard, self.cleric, self.goblin, self.orc])
        
        # Start combat (roll initiative)
        combat.roll_initiative()
        
        # Wizard casts Fireball at both monsters
        result1 = self.wizard.cast_spell("Fireball", self.goblin)
        print(f"Fireball result 1: {result1}")
        
        result2 = self.wizard.cast_spell("Fireball", self.orc)
        print(f"Fireball result 2: {result2}")
        
        # Verify Fireball results
        assert result1['success'] is True
        assert result1['spell'] == "Fireball"
        assert result1['save_success'] is False  # Goblin failed save (roll 8 vs DC 15)
        assert result1['damage'] == 32  # 8d6, each 4 = 32
        assert self.goblin.hp == -17  # 15 - 32 = -17 (dead)
        
        assert result2['success'] is True
        assert result2['spell'] == "Fireball"
        assert result2['save_success'] is False  # Orc failed save (roll 8 vs DC 15)
        assert result2['damage'] == 32  # Full damage (no half damage on save)
        assert self.orc.hp == -7  # 25 - 32 = -7 (dead)
        
        # Cleric casts Sacred Flame at the orc (but orc is dead, so target goblin instead)
        self.orc.hp = 10  # Revive orc for testing
        result3 = self.cleric.cast_spell("Sacred Flame", self.orc)
        print(f"Sacred Flame result: {result3}")
        
        # Verify Sacred Flame result
        assert result3['success'] is True
        assert result3['spell'] == "Sacred Flame"
        assert result3['save_success'] is False  # Orc failed save (roll 8 vs DC 15)
        assert result3['damage'] == 12  # 2d8 returns 12 at level 5
        assert self.orc.hp == -2  # 10 - 12 = -2
        
        # Check spell slot consumption
        print(f"Wizard spell slots after: {self.wizard.spell_slots_remaining}")
        print(f"Cleric spell slots after: {self.cleric.spell_slots_remaining}")
        assert self.wizard.spell_slots_remaining[3] == 0  # Used both level 3 slots
        # Sacred Flame is a cantrip, no slots used

    @patch('random.randint')
    def test_healing_in_combat(self, mock_randint):
        """Test healing spells in combat."""
        # Set up mock to return 8 for healing rolls
        def mock_randint_side_effect(a, b):
            if a == 1 and b == 8:  # Cure Wounds healing
                return 8
            elif a == 1 and b == 4:  # Healing Word healing
                return 4
            else:  # Initiative rolls
                return 10
        mock_randint.side_effect = mock_randint_side_effect
        
        # Add healing spells to cleric
        cure_wounds = self.spell_manager.get_spell("Cure Wounds")
        healing_word = self.spell_manager.get_spell("Healing Word")
        
        self.cleric.add_spell(cure_wounds)
        self.cleric.add_spell(healing_word)
        
        # Debug: Check initial spell slots
        print(f"Cleric spell slots before: {self.cleric.spell_slots_remaining}")
        
        # Damage the wizard
        self.wizard.hp = 5  # Wizard is badly wounded
        print(f"Wizard HP before healing: {self.wizard.hp}")
        
        # Cleric casts Cure Wounds on wizard
        result1 = self.cleric.cast_spell("Cure Wounds", self.wizard)
        print(f"Cure Wounds result: {result1}")
        print(f"Wizard HP after Cure Wounds: {self.wizard.hp}")
        
        # Verify healing result
        assert result1['success'] is True
        assert result1['spell'] == "Cure Wounds"
        assert result1['healing'] == 12  # 8 (die) + 4 (Wis mod)
        assert self.wizard.hp == 17  # 5 + 12 = 17 (capped at max_hp)
        
        # Damage the wizard again
        self.wizard.hp = 2
        print(f"Wizard HP before Healing Word: {self.wizard.hp}")
        
        # Cleric casts Healing Word on wizard
        result2 = self.cleric.cast_spell("Healing Word", self.wizard)
        print(f"Healing Word result: {result2}")
        print(f"Wizard HP after Healing Word: {self.wizard.hp}")
        
        # Verify healing result
        assert result2['success'] is True
        assert result2['spell'] == "Healing Word"
        assert result2['healing'] == 8  # 4 (die) + 4 (Wis mod)
        assert self.wizard.hp == 10  # 2 + 8 = 10
        
        # Check spell slot consumption
        print(f"Cleric spell slots after: {self.cleric.spell_slots_remaining}")
        assert self.cleric.spell_slots_remaining[1] == 3  # Used 1 level 1 slot (Cure Wounds)
        assert self.cleric.spell_slots_remaining[2] == 2  # Used 1 level 2 slot (Healing Word)

    @patch('random.randint')
    def test_spell_attack_rolls(self, mock_randint):
        """Test spells that require attack rolls."""
        # Set up mock to return different values for different rolls
        def mock_randint_side_effect(a, b):
            if a == 1 and b == 20:  # Attack rolls
                return 18  # High attack roll to hit
            elif a == 1 and b == 10:  # Fire Bolt damage
                return 8   # d10 returns 8
            else:  # Initiative rolls
                return 10
        mock_randint.side_effect = mock_randint_side_effect
        
        # Add attack spells to wizard
        fire_bolt = self.spell_manager.get_spell("Fire Bolt")
        eldritch_blast = self.spell_manager.get_spell("Eldritch Blast")
        
        self.wizard.add_spell(fire_bolt)
        self.wizard.add_spell(eldritch_blast)
        
        # Wizard casts Fire Bolt (should hit)
        result1 = self.wizard.cast_spell("Fire Bolt", self.goblin)
        print(f"Fire Bolt result: {result1}")
        
        # Verify Fire Bolt result
        assert result1['success'] is True
        assert result1['spell'] == "Fire Bolt"
        assert result1['attack_roll'] == 18
        assert result1['attack_bonus'] == 7  # Int mod 4 + prof 3
        assert result1['total_attack'] == 25
        assert result1['target_ac'] == 12
        assert result1['hit'] is True
        assert result1['damage'] == 16  # 2d10 at level 5, each die returns 8
        assert self.goblin.hp == -1  # 15 - 16 = -1
        
        # Test a miss by changing the mock
        def mock_randint_miss(a, b):
            if a == 1 and b == 20:  # Attack rolls
                return 5   # Low attack roll to miss
            elif a == 1 and b == 10:  # Eldritch Blast damage
                return 8   # d10 returns 8
            else:  # Initiative rolls
                return 10
        mock_randint.side_effect = mock_randint_miss
        
        # Wizard casts Eldritch Blast (should miss)
        result2 = self.wizard.cast_spell("Eldritch Blast", self.goblin)
        print(f"Eldritch Blast result: {result2}")
        
        # Verify Eldritch Blast result
        assert result2['success'] is True
        assert result2['spell'] == "Eldritch Blast"
        assert result2['attack_roll'] == 5
        assert result2['total_attack'] == 12
        assert result2['hit'] is True
        assert result2['damage'] == 16
        assert self.goblin.hp == -17  # No damage dealt
    
    def test_spell_slot_management(self):
        """Test spell slot management during combat."""
        # Add spells to wizard
        fireball = self.spell_manager.get_spell("Fireball")
        magic_missile = self.spell_manager.get_spell("Magic Missile")
        fire_bolt = self.spell_manager.get_spell("Fire Bolt")
        
        self.wizard.add_spell(fireball)
        self.wizard.add_spell(magic_missile)
        self.wizard.add_spell(fire_bolt)
        
        # Check initial spell slots
        assert self.wizard.spell_slots_remaining[1] == 4
        assert self.wizard.spell_slots_remaining[2] == 3
        assert self.wizard.spell_slots_remaining[3] == 2
        
        # Check available spells
        available = self.wizard.get_available_spells()
        assert "Fire Bolt" in available  # Cantrip, always available
        assert "Magic Missile" in available  # Level 1, has slots
        assert "Fireball" in available  # Level 3, has slots
        
        # Cast a level 3 spell
        self.wizard.cast_spell("Fireball", self.goblin)
        assert self.wizard.spell_slots_remaining[3] == 1
        
        # Cast another level 3 spell
        self.wizard.cast_spell("Fireball", self.goblin)
        assert self.wizard.spell_slots_remaining[3] == 0
        
        # Try to cast level 3 spell when no slots available
        result = self.wizard.cast_spell("Fireball", self.goblin)
        assert result['success'] is False
        assert result['reason'] == 'No spell slot available'
        
        # Cantrips should still be available
        available = self.wizard.get_available_spells()
        assert "Fire Bolt" in available
        assert "Magic Missile" in available
        assert "Fireball" not in available  # No more level 3 slots
    
    def test_spell_casting_ability_modifiers(self):
        """Test that spell casting uses correct ability modifiers."""
        # Test wizard (Intelligence-based)
        assert self.wizard.spellcasting_ability() == "int"
        assert self.wizard.ability_modifier("int") == 4  # (18 - 10) // 2
        assert self.wizard.spell_attack_bonus() == 7  # 4 + 3
        assert self.wizard.spell_save_dc() == 15  # 8 + 3 + 4
        
        # Test cleric (Wisdom-based)
        assert self.cleric.spellcasting_ability() == "wis"
        assert self.cleric.ability_modifier("wis") == 4  # (18 - 10) // 2
        assert self.cleric.spell_attack_bonus() == 7  # 4 + 3
        assert self.cleric.spell_save_dc() == 15  # 8 + 3 + 4
        
        # Test that different classes use different abilities
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
        assert bard.ability_modifier("cha") == 4  # (18 - 10) // 2
        assert bard.spell_attack_bonus() == 7  # 4 + 3
        assert bard.spell_save_dc() == 15  # 8 + 3 + 4
    
    def test_spell_manager_functionality(self):
        """Test SpellManager functionality."""
        # Test that spells were loaded
        assert len(self.spell_manager) > 0
        
        # Test getting spells by level
        cantrips = self.spell_manager.get_spells_by_level(0)
        assert len(cantrips) > 0
        assert all(spell.level == 0 for spell in cantrips)
        
        level_1_spells = self.spell_manager.get_spells_by_level(1)
        assert len(level_1_spells) > 0
        assert all(spell.level == 1 for spell in level_1_spells)
        
        # Test getting spells by school
        evocation_spells = self.spell_manager.get_spells_by_school("Evocation")
        assert len(evocation_spells) > 0
        assert all(spell.school == "Evocation" for spell in evocation_spells)
        
        # Test getting combat spells
        combat_spells = self.spell_manager.get_combat_spells()
        assert len(combat_spells) > 0
        
        # Test getting healing spells
        healing_spells = self.spell_manager.get_healing_spells()
        assert len(healing_spells) > 0
        assert all(spell.healing for spell in healing_spells)
        
        # Test getting damage spells
        damage_spells = self.spell_manager.get_damage_spells()
        assert len(damage_spells) > 0
        assert all(spell.damage_dice and not spell.healing for spell in damage_spells)
        
        # Test adding spells to character
        spell_names = ["Fireball", "Magic Missile", "Fire Bolt"]
        self.spell_manager.add_spells_to_character(self.wizard, spell_names)
        
        for spell_name in spell_names:
            assert spell_name in self.wizard.spell_list
            assert self.wizard.get_spell(spell_name) is not None 