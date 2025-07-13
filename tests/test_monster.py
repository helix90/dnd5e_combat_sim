"""
Unit tests for the Monster model.

This module contains comprehensive tests for the Monster class,
including ability score calculations, modifiers, attack bonuses,
challenge rating parsing, and edge cases.
"""

import pytest
from models.monster import Monster


class TestMonster:
    """Test cases for the Monster class."""
    
    def setup_method(self):
        """Set up test fixtures before each test method."""
        self.standard_ability_scores = {
            'str': 18, 'dex': 14, 'con': 16, 'int': 8, 'wis': 12, 'cha': 6
        }
        
        self.monster = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=7,
            ac=15,
            ability_scores=self.standard_ability_scores,
            damage_resistances=["fire", "cold"]
        )
    
    def test_monster_initialization(self):
        """Test that a monster is initialized correctly."""
        assert self.monster.name == "Goblin"
        assert self.monster.challenge_rating == "1/4"
        assert self.monster.hp == 7
        assert self.monster.ac == 15
        assert self.monster.ability_scores == self.standard_ability_scores
        assert self.monster.damage_resistances == ["fire", "cold"]
    
    def test_monster_initialization_no_resistances(self):
        """Test that a monster can be initialized without damage resistances."""
        monster = Monster(
            name="Simple Monster",
            challenge_rating="1",
            hp=10,
            ac=12,
            ability_scores=self.standard_ability_scores
        )
        
        assert monster.damage_resistances == []
    
    def test_monster_initialization_missing_abilities(self):
        """Test that missing ability scores raise ValueError."""
        incomplete_scores = {'str': 18, 'dex': 14, 'con': 16}
        
        with pytest.raises(ValueError, match="Ability scores must include"):
            Monster(
                name="Invalid",
                challenge_rating="1",
                hp=10,
                ac=12,
                ability_scores=incomplete_scores
            )
    
    def test_monster_initialization_invalid_ability_scores(self):
        """Test that invalid ability scores raise ValueError."""
        invalid_scores = {'str': 0, 'dex': 14, 'con': 16, 'int': 8, 'wis': 12, 'cha': 6}
        
        with pytest.raises(ValueError, match="Ability scores must be between 1 and 30"):
            Monster(
                name="Invalid",
                challenge_rating="1",
                hp=10,
                ac=12,
                ability_scores=invalid_scores
            )
        
        invalid_scores = {'str': 18, 'dex': 14, 'con': 16, 'int': 8, 'wis': 12, 'cha': 31}
        
        with pytest.raises(ValueError, match="Ability scores must be between 1 and 30"):
            Monster(
                name="Invalid",
                challenge_rating="1",
                hp=10,
                ac=12,
                ability_scores=invalid_scores
            )
    
    def test_ability_modifier_calculations(self):
        """Test ability modifier calculations for various scores."""
        # Test standard scores
        assert self.monster.ability_modifier('str') == 4  # 18 -> +4
        assert self.monster.ability_modifier('dex') == 2  # 14 -> +2
        assert self.monster.ability_modifier('con') == 3  # 16 -> +3
        assert self.monster.ability_modifier('int') == -1  # 8 -> -1
        assert self.monster.ability_modifier('wis') == 1  # 12 -> +1
        assert self.monster.ability_modifier('cha') == -2  # 6 -> -2
    
    def test_ability_modifier_edge_cases(self):
        """Test ability modifier calculations for edge cases."""
        # Create monster with extreme ability scores
        extreme_scores = {
            'str': 1, 'dex': 3, 'con': 5, 'int': 7, 'wis': 9, 'cha': 11
        }
        extreme_monster = Monster(
            name="Extreme Monster",
            challenge_rating="1",
            hp=10,
            ac=10,
            ability_scores=extreme_scores
        )
        
        assert extreme_monster.ability_modifier('str') == -5  # 1 -> -5
        assert extreme_monster.ability_modifier('dex') == -4  # 3 -> -4
        assert extreme_monster.ability_modifier('con') == -3  # 5 -> -3
        assert extreme_monster.ability_modifier('int') == -2  # 7 -> -2
        assert extreme_monster.ability_modifier('wis') == -1  # 9 -> -1
        assert extreme_monster.ability_modifier('cha') == 0   # 11 -> +0
        
        # Test high scores
        high_scores = {
            'str': 20, 'dex': 22, 'con': 24, 'int': 26, 'wis': 28, 'cha': 30
        }
        high_monster = Monster(
            name="High Stats Monster",
            challenge_rating="20",
            hp=100,
            ac=20,
            ability_scores=high_scores
        )
        
        assert high_monster.ability_modifier('str') == 5   # 20 -> +5
        assert high_monster.ability_modifier('dex') == 6   # 22 -> +6
        assert high_monster.ability_modifier('con') == 7   # 24 -> +7
        assert high_monster.ability_modifier('int') == 8   # 26 -> +8
        assert high_monster.ability_modifier('wis') == 9   # 28 -> +9
        assert high_monster.ability_modifier('cha') == 10  # 30 -> +10
    
    def test_ability_modifier_invalid_ability(self):
        """Test that invalid ability names raise ValueError."""
        with pytest.raises(ValueError, match="Invalid ability: invalid"):
            self.monster.ability_modifier('invalid')
    
    def test_attack_bonus_melee(self):
        """Test attack bonus calculation for melee weapons."""
        # Melee weapons use Strength modifier + proficiency bonus based on CR
        str_mod = self.monster.ability_modifier('str')  # 4
        # CR 1/4 gives proficiency bonus of 2
        expected_bonus = str_mod + 2
        assert self.monster.attack_bonus("melee") == expected_bonus
        assert self.monster.attack_bonus("melee") == 6  # 4 + 2
    
    def test_attack_bonus_ranged(self):
        """Test attack bonus calculation for ranged weapons."""
        # Ranged weapons use Dexterity modifier + proficiency bonus based on CR
        dex_mod = self.monster.ability_modifier('dex')  # 2
        # CR 1/4 gives proficiency bonus of 2
        expected_bonus = dex_mod + 2
        assert self.monster.attack_bonus("ranged") == expected_bonus
        assert self.monster.attack_bonus("ranged") == 4  # 2 + 2
    
    def test_attack_bonus_finesse(self):
        """Test attack bonus calculation for finesse weapons."""
        # Finesse weapons use the higher of Strength or Dexterity
        str_mod = self.monster.ability_modifier('str')  # 4
        dex_mod = self.monster.ability_modifier('dex')  # 2
        # CR 1/4 gives proficiency bonus of 2
        expected_bonus = max(str_mod, dex_mod) + 2
        assert self.monster.attack_bonus("finesse") == expected_bonus
        assert self.monster.attack_bonus("finesse") == 6  # max(4, 2) + 2
    
    def test_attack_bonus_finesse_dex_higher(self):
        """Test finesse attack bonus when Dexterity is higher."""
        # Create monster with higher Dexterity than Strength
        dex_monster = Monster(
            name="Dex Monster",
            challenge_rating="1",
            hp=20,
            ac=15,
            ability_scores={'str': 12, 'dex': 18, 'con': 14, 'int': 8, 'wis': 10, 'cha': 6}
        )
        
        str_mod = dex_monster.ability_modifier('str')  # 1
        dex_mod = dex_monster.ability_modifier('dex')  # 4
        # CR 1 gives proficiency bonus of 2
        expected_bonus = max(str_mod, dex_mod) + 2
        assert dex_monster.attack_bonus("finesse") == expected_bonus
        assert dex_monster.attack_bonus("finesse") == 6  # max(1, 4) + 2
    
    def test_attack_bonus_default_weapon_type(self):
        """Test that attack_bonus defaults to melee weapon type."""
        str_mod = self.monster.ability_modifier('str')  # 4
        # CR 1/4 gives proficiency bonus of 2
        expected_bonus = str_mod + 2
        assert self.monster.attack_bonus() == expected_bonus
        assert self.monster.attack_bonus() == 6
    
    def test_attack_bonus_different_challenge_ratings(self):
        """Test attack bonus calculation for different challenge ratings."""
        # Test CR 1/8 (proficiency bonus 2)
        cr_1_8_monster = Monster(
            name="CR 1/8 Monster",
            challenge_rating="1/8",
            hp=5,
            ac=12,
            ability_scores=self.standard_ability_scores
        )
        str_mod = cr_1_8_monster.ability_modifier('str')  # 4
        assert cr_1_8_monster.attack_bonus("melee") == 6  # 4 + 2
        
        # Test CR 1 (proficiency bonus 2)
        cr_1_monster = Monster(
            name="CR 1 Monster",
            challenge_rating="1",
            hp=20,
            ac=15,
            ability_scores=self.standard_ability_scores
        )
        str_mod = cr_1_monster.ability_modifier('str')  # 4
        assert cr_1_monster.attack_bonus("melee") == 6  # 4 + 2
        
        # Test CR 5 (proficiency bonus 4)
        cr_5_monster = Monster(
            name="CR 5 Monster",
            challenge_rating="5",
            hp=50,
            ac=17,
            ability_scores=self.standard_ability_scores
        )
        str_mod = cr_5_monster.ability_modifier('str')  # 4
        assert cr_5_monster.attack_bonus("melee") == 8  # 4 + 4
        
        # Test CR 10 (proficiency bonus 5)
        cr_10_monster = Monster(
            name="CR 10 Monster",
            challenge_rating="10",
            hp=100,
            ac=19,
            ability_scores=self.standard_ability_scores
        )
        str_mod = cr_10_monster.ability_modifier('str')  # 4
        assert cr_10_monster.attack_bonus("melee") == 9  # 4 + 5
        
        # Test CR 20 (proficiency bonus 7)
        cr_20_monster = Monster(
            name="CR 20 Monster",
            challenge_rating="20",
            hp=200,
            ac=22,
            ability_scores=self.standard_ability_scores
        )
        str_mod = cr_20_monster.ability_modifier('str')  # 4
        assert cr_20_monster.attack_bonus("melee") == 11  # 4 + 7
    
    def test_parse_challenge_rating(self):
        """Test challenge rating parsing for various formats."""
        # Test fractional CRs
        assert self.monster._parse_challenge_rating() == 0.25  # "1/4"
        
        cr_1_8_monster = Monster(
            name="CR 1/8",
            challenge_rating="1/8",
            hp=5,
            ac=12,
            ability_scores=self.standard_ability_scores
        )
        assert cr_1_8_monster._parse_challenge_rating() == 0.125  # "1/8"
        
        cr_1_2_monster = Monster(
            name="CR 1/2",
            challenge_rating="1/2",
            hp=10,
            ac=13,
            ability_scores=self.standard_ability_scores
        )
        assert cr_1_2_monster._parse_challenge_rating() == 0.5  # "1/2"
        
        # Test integer CRs
        cr_1_monster = Monster(
            name="CR 1",
            challenge_rating="1",
            hp=20,
            ac=15,
            ability_scores=self.standard_ability_scores
        )
        assert cr_1_monster._parse_challenge_rating() == 1.0  # "1"
        
        cr_5_monster = Monster(
            name="CR 5",
            challenge_rating="5",
            hp=50,
            ac=17,
            ability_scores=self.standard_ability_scores
        )
        assert cr_5_monster._parse_challenge_rating() == 5.0  # "5"
        
        # Test CR 0
        cr_0_monster = Monster(
            name="CR 0",
            challenge_rating="0",
            hp=1,
            ac=10,
            ability_scores=self.standard_ability_scores
        )
        assert cr_0_monster._parse_challenge_rating() == 0.0  # "0"
    
    def test_parse_challenge_rating_invalid(self):
        """Test that invalid challenge rating formats raise ValueError."""
        # Create a monster with invalid CR and test the parsing
        invalid_monster = Monster(
            name="Invalid CR",
            challenge_rating="invalid",
            hp=10,
            ac=12,
            ability_scores=self.standard_ability_scores
        )
        
        with pytest.raises(ValueError, match="Invalid challenge rating format: invalid"):
            invalid_monster._parse_challenge_rating()
    
    def test_is_resistant_to(self):
        """Test damage resistance checking."""
        # Test case-sensitive resistance checking
        assert self.monster.is_resistant_to("fire") == True
        assert self.monster.is_resistant_to("cold") == True
        assert self.monster.is_resistant_to("lightning") == False
        assert self.monster.is_resistant_to("poison") == False
        
        # Test case-insensitive resistance checking
        assert self.monster.is_resistant_to("FIRE") == True
        assert self.monster.is_resistant_to("Cold") == True
        assert self.monster.is_resistant_to("Fire") == True
    
    def test_is_resistant_to_no_resistances(self):
        """Test damage resistance checking for monster with no resistances."""
        no_resist_monster = Monster(
            name="No Resistances",
            challenge_rating="1",
            hp=20,
            ac=15,
            ability_scores=self.standard_ability_scores
        )
        
        assert no_resist_monster.is_resistant_to("fire") == False
        assert no_resist_monster.is_resistant_to("cold") == False
        assert no_resist_monster.is_resistant_to("lightning") == False
    
    def test_string_representation(self):
        """Test string representation of monster."""
        expected = "Goblin (CR 1/4)"
        assert str(self.monster) == expected
    
    def test_repr_representation(self):
        """Test detailed string representation of monster."""
        repr_str = repr(self.monster)
        assert "Monster(" in repr_str
        assert "name='Goblin'" in repr_str
        assert "challenge_rating='1/4'" in repr_str
        assert "hp=7" in repr_str
        assert "ac=15" in repr_str
        assert "ability_scores=" in repr_str
        assert "damage_resistances=" in repr_str
    
    def test_ability_scores_immutability(self):
        """Test that ability scores are copied to prevent external modification."""
        original_scores = self.standard_ability_scores.copy()
        self.monster.ability_scores['str'] = 20
        
        # The original dictionary should not be modified
        assert self.standard_ability_scores == original_scores
        # The monster's ability scores should be modified
        assert self.monster.ability_scores['str'] == 20 

def test_monster_from_api_success(monkeypatch):
    from models.monster import Monster
    from utils.api_client import APIClient
    class DummyAPIClient(APIClient):
        def __init__(self):
            pass
        def fetch_monster_data(self, name):
            return {
                'name': 'Goblin', 'challenge_rating': '1/4', 'hit_points': 7, 'armor_class': 15,
                'strength': 8, 'dexterity': 14, 'constitution': 10, 'intelligence': 10, 'wisdom': 8, 'charisma': 8,
                'damage_resistances': [], 'damage_immunities': [], 'special_abilities': [], 'legendary_actions': [],
                'actions': [{'name': 'Scimitar'}]
            }
    monster = Monster.from_api('Goblin', api_client=DummyAPIClient())
    assert monster.name == 'Goblin'
    assert monster.challenge_rating == '1/4'
    assert monster.hp == 7
    assert monster.ac == 15
    assert monster.ability_scores['dex'] == 14

def test_monster_from_api_fallback(monkeypatch):
    from models.monster import Monster
    from utils.api_client import APIClient
    class DummyFallback:
        def __init__(self):
            self.called = False
        def get_local_data(self, data_type, name):
            if data_type == 'monsters' and name.lower() == 'ogre':
                self.called = True
                return {
                    'name': 'Ogre', 'challenge_rating': '2', 'hit_points': 59, 'armor_class': 11,
                    'strength': 19, 'dexterity': 8, 'constitution': 16, 'intelligence': 5, 'wisdom': 7, 'charisma': 7,
                    'damage_resistances': [], 'damage_immunities': [], 'special_abilities': [], 'legendary_actions': [],
                    'actions': [{'name': 'Smash'}]  # Provide at least one action to avoid IndexError
                }
            return None
    class DummyAPIClient(APIClient):
        def __init__(self):
            self.fallback_handler = DummyFallback()
        def fetch_monster_data(self, name):
            # Simulate API failure, so fallback is used
            return self.fallback_handler.get_local_data('monsters', name)
    dummy_api_client = DummyAPIClient()
    monster = Monster.from_api('Ogre', api_client=dummy_api_client)
    assert monster.name == 'Ogre'
    assert monster.hp == 59
    assert monster.ability_scores['str'] == 19
    assert dummy_api_client.fallback_handler.called, "Fallback handler was not called!"

def test_monster_from_api_not_found(monkeypatch):
    from models.monster import Monster
    from utils.api_client import APIClient
    from utils.exceptions import APIError
    class DummyFallback:
        def get_local_data(self, data_type, name):
            return None
    class DummyAPIClient(APIClient):
        def __init__(self):
            self.fallback_handler = DummyFallback()
        def fetch_monster_data(self, name):
            return None
    with pytest.raises(APIError):
        Monster.from_api('Nonexistent Monster', api_client=DummyAPIClient()) 