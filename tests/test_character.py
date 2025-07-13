"""
Unit tests for the Character model.

This module contains comprehensive tests for the Character class,
including ability score calculations, modifiers, attack bonuses,
and edge cases.
"""

import pytest
from models.character import Character


class TestCharacter:
    """Test cases for the Character class."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.standard_ability_scores = {
            'str': 16, 'dex': 14, 'con': 12, 'int': 10, 'wis': 8, 'cha': 6
        }
        
        self.character = Character(
            name="Test Fighter",
            level=5,
            character_class="Fighter",
            race="Human",
            ability_scores=self.standard_ability_scores,
            hp=45,
            ac=16,
            proficiency_bonus=3
        )
    
    def test_character_initialization(self):
        """Test that a character is initialized correctly."""
        assert self.character.name == "Test Fighter"
        assert self.character.level == 5
        assert self.character.character_class == "Fighter"
        assert self.character.race == "Human"
        assert self.character.ability_scores == self.standard_ability_scores
        assert self.character.hp == 45
        assert self.character.ac == 16
        assert self.character.proficiency_bonus == 3
    
    def test_character_initialization_invalid_level(self):
        """Test that invalid levels raise ValueError."""
        with pytest.raises(ValueError, match="Level must be between 1 and 20"):
            Character(
                name="Invalid",
                level=0,
                character_class="Fighter",
                race="Human",
                ability_scores=self.standard_ability_scores,
                hp=10,
                ac=10,
                proficiency_bonus=2
            )
        
        with pytest.raises(ValueError, match="Level must be between 1 and 20"):
            Character(
                name="Invalid",
                level=21,
                character_class="Fighter",
                race="Human",
                ability_scores=self.standard_ability_scores,
                hp=10,
                ac=10,
                proficiency_bonus=2
            )
    
    def test_character_initialization_missing_abilities(self):
        """Test that missing ability scores raise ValueError."""
        incomplete_scores = {'str': 16, 'dex': 14, 'con': 12}
        
        with pytest.raises(ValueError, match="Ability scores must include"):
            Character(
                name="Invalid",
                level=1,
                character_class="Fighter",
                race="Human",
                ability_scores=incomplete_scores,
                hp=10,
                ac=10,
                proficiency_bonus=2
            )
    
    def test_character_initialization_invalid_ability_scores(self):
        """Test that invalid ability scores raise ValueError."""
        invalid_scores = {'str': 0, 'dex': 14, 'con': 12, 'int': 10, 'wis': 8, 'cha': 6}
        
        with pytest.raises(ValueError, match="Ability scores must be between 1 and 30"):
            Character(
                name="Invalid",
                level=1,
                character_class="Fighter",
                race="Human",
                ability_scores=invalid_scores,
                hp=10,
                ac=10,
                proficiency_bonus=2
            )
        
        invalid_scores = {'str': 16, 'dex': 14, 'con': 12, 'int': 10, 'wis': 8, 'cha': 31}
        
        with pytest.raises(ValueError, match="Ability scores must be between 1 and 30"):
            Character(
                name="Invalid",
                level=1,
                character_class="Fighter",
                race="Human",
                ability_scores=invalid_scores,
                hp=10,
                ac=10,
                proficiency_bonus=2
            )
    
    def test_ability_modifier_calculations(self):
        """Test ability modifier calculations for various scores."""
        # Test standard scores
        assert self.character.ability_modifier('str') == 3  # 16 -> +3
        assert self.character.ability_modifier('dex') == 2  # 14 -> +2
        assert self.character.ability_modifier('con') == 1  # 12 -> +1
        assert self.character.ability_modifier('int') == 0  # 10 -> +0
        assert self.character.ability_modifier('wis') == -1  # 8 -> -1
        assert self.character.ability_modifier('cha') == -2  # 6 -> -2
    
    def test_ability_modifier_edge_cases(self):
        """Test ability modifier calculations for edge cases."""
        # Create character with extreme ability scores
        extreme_scores = {
            'str': 1, 'dex': 3, 'con': 5, 'int': 7, 'wis': 9, 'cha': 11
        }
        extreme_character = Character(
            name="Extreme",
            level=1,
            character_class="Fighter",
            race="Human",
            ability_scores=extreme_scores,
            hp=10,
            ac=10,
            proficiency_bonus=2
        )
        
        assert extreme_character.ability_modifier('str') == -5  # 1 -> -5
        assert extreme_character.ability_modifier('dex') == -4  # 3 -> -4
        assert extreme_character.ability_modifier('con') == -3  # 5 -> -3
        assert extreme_character.ability_modifier('int') == -2  # 7 -> -2
        assert extreme_character.ability_modifier('wis') == -1  # 9 -> -1
        assert extreme_character.ability_modifier('cha') == 0   # 11 -> +0
        
        # Test high scores
        high_scores = {
            'str': 20, 'dex': 22, 'con': 24, 'int': 26, 'wis': 28, 'cha': 30
        }
        high_character = Character(
            name="High Stats",
            level=1,
            character_class="Fighter",
            race="Human",
            ability_scores=high_scores,
            hp=10,
            ac=10,
            proficiency_bonus=2
        )
        
        assert high_character.ability_modifier('str') == 5   # 20 -> +5
        assert high_character.ability_modifier('dex') == 6   # 22 -> +6
        assert high_character.ability_modifier('con') == 7   # 24 -> +7
        assert high_character.ability_modifier('int') == 8   # 26 -> +8
        assert high_character.ability_modifier('wis') == 9   # 28 -> +9
        assert high_character.ability_modifier('cha') == 10  # 30 -> +10
    
    def test_ability_modifier_invalid_ability(self):
        """Test that invalid ability names raise ValueError."""
        with pytest.raises(ValueError, match="Invalid ability: invalid"):
            self.character.ability_modifier('invalid')
    
    def test_saving_throw_bonus_not_proficient(self):
        """Test saving throw bonus calculation when not proficient."""
        assert self.character.saving_throw_bonus('str', proficient=False) == 3
        assert self.character.saving_throw_bonus('dex', proficient=False) == 2
        assert self.character.saving_throw_bonus('con', proficient=False) == 1
        assert self.character.saving_throw_bonus('int', proficient=False) == 0
        assert self.character.saving_throw_bonus('wis', proficient=False) == -1
        assert self.character.saving_throw_bonus('cha', proficient=False) == -2
    
    def test_saving_throw_bonus_proficient(self):
        """Test saving throw bonus calculation when proficient."""
        assert self.character.saving_throw_bonus('str', proficient=True) == 6  # 3 + 3
        assert self.character.saving_throw_bonus('dex', proficient=True) == 5  # 2 + 3
        assert self.character.saving_throw_bonus('con', proficient=True) == 4  # 1 + 3
        assert self.character.saving_throw_bonus('int', proficient=True) == 3  # 0 + 3
        assert self.character.saving_throw_bonus('wis', proficient=True) == 2  # -1 + 3
        assert self.character.saving_throw_bonus('cha', proficient=True) == 1  # -2 + 3
    
    def test_attack_bonus_melee(self):
        """Test attack bonus calculation for melee weapons."""
        # Melee weapons use Strength modifier
        expected_bonus = self.character.ability_modifier('str') + self.character.proficiency_bonus
        assert self.character.attack_bonus("melee") == expected_bonus
        assert self.character.attack_bonus("melee") == 6  # 3 + 3
    
    def test_attack_bonus_ranged(self):
        """Test attack bonus calculation for ranged weapons."""
        # Ranged weapons use Dexterity modifier
        expected_bonus = self.character.ability_modifier('dex') + self.character.proficiency_bonus
        assert self.character.attack_bonus("ranged") == expected_bonus
        assert self.character.attack_bonus("ranged") == 5  # 2 + 3
    
    def test_attack_bonus_finesse(self):
        """Test attack bonus calculation for finesse weapons."""
        # Finesse weapons use the higher of Strength or Dexterity
        str_mod = self.character.ability_modifier('str')  # 3
        dex_mod = self.character.ability_modifier('dex')  # 2
        expected_bonus = max(str_mod, dex_mod) + self.character.proficiency_bonus
        assert self.character.attack_bonus("finesse") == expected_bonus
        assert self.character.attack_bonus("finesse") == 6  # max(3, 2) + 3
    
    def test_attack_bonus_finesse_dex_higher(self):
        """Test finesse attack bonus when Dexterity is higher."""
        # Create character with higher Dexterity than Strength
        dex_character = Character(
            name="Dex Fighter",
            level=5,
            character_class="Fighter",
            race="Elf",
            ability_scores={'str': 12, 'dex': 18, 'con': 14, 'int': 10, 'wis': 8, 'cha': 6},
            hp=45,
            ac=16,
            proficiency_bonus=3
        )
        
        str_mod = dex_character.ability_modifier('str')  # 1
        dex_mod = dex_character.ability_modifier('dex')  # 4
        expected_bonus = max(str_mod, dex_mod) + dex_character.proficiency_bonus
        assert dex_character.attack_bonus("finesse") == expected_bonus
        assert dex_character.attack_bonus("finesse") == 7  # max(1, 4) + 3
    
    def test_attack_bonus_default_weapon_type(self):
        """Test that attack_bonus defaults to melee weapon type."""
        expected_bonus = self.character.ability_modifier('str') + self.character.proficiency_bonus
        assert self.character.attack_bonus() == expected_bonus
        assert self.character.attack_bonus() == 6
    
    def test_string_representation(self):
        """Test string representation of character."""
        expected = "Test Fighter (Human Fighter 5)"
        assert str(self.character) == expected
    
    def test_repr_representation(self):
        """Test detailed string representation of character."""
        repr_str = repr(self.character)
        assert "Character(" in repr_str
        assert "name='Test Fighter'" in repr_str
        assert "level=5" in repr_str
        assert "character_class='Fighter'" in repr_str
        assert "race='Human'" in repr_str
        assert "ability_scores=" in repr_str
        assert "hp=45" in repr_str
        assert "ac=16" in repr_str
        assert "proficiency_bonus=3" in repr_str
    
    def test_ability_scores_immutability(self):
        """Test that ability scores are copied to prevent external modification."""
        original_scores = self.standard_ability_scores.copy()
        self.character.ability_scores['str'] = 20
        
        # The original dictionary should not be modified
        assert self.standard_ability_scores == original_scores
        # The character's ability scores should be modified
        assert self.character.ability_scores['str'] == 20 