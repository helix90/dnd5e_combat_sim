"""
Monster model for D&D 5e Combat Simulator.

This module contains the Monster class which represents a monster or NPC
in the D&D 5e system with all relevant attributes and methods for combat.
"""

from typing import Dict, List, Optional
from models.actions import AttackAction
from models.buffs import BuffManager
from utils.api_client import APIClient
from utils.exceptions import APIError


class Monster:
    """
    A D&D 5e monster with combat-relevant attributes and methods.
    
    Attributes:
        name (str): The monster's name
        challenge_rating (str): The monster's challenge rating (e.g., '1/4', '1', '5')
        hp (int): Current and maximum hit points
        ac (int): Armor Class
        ability_scores (Dict[str, int]): Dictionary of ability scores
        damage_resistances (List[str]): List of damage types the monster resists
        actions (List[Action]): List of available actions
    """
    
    def __init__(
        self,
        name: str,
        challenge_rating: str,
        hp: int,
        ac: int,
        ability_scores: Dict[str, int],
        damage_resistances: Optional[List[str]] = None,
        damage_immunities: Optional[List[str]] = None,
        special_abilities: Optional[List[str]] = None,
        legendary_actions: Optional[List[str]] = None,
        multiattack: bool = False,
        actions: Optional[List] = None
    ) -> None:
        """
        Initialize a new Monster instance.
        Args:
            name: The monster's name
            challenge_rating: The monster's challenge rating
            hp: Hit points
            ac: Armor Class
            ability_scores: Dictionary with keys 'str', 'dex', 'con', 'int', 'wis', 'cha'
            damage_resistances: List of damage types the monster resists
            damage_immunities: List of damage types the monster is immune to
            special_abilities: List of special abilities
            legendary_actions: List of legendary actions
            multiattack: Whether the monster can multiattack
            actions: List of actions
        Raises:
            ValueError: If ability scores are invalid
        """
        required_abilities = {'str', 'dex', 'con', 'int', 'wis', 'cha'}
        if not all(ability in ability_scores for ability in required_abilities):
            raise ValueError(f"Ability scores must include: {required_abilities}")
        if any(score < 1 or score > 30 for score in ability_scores.values()):
            raise ValueError("Ability scores must be between 1 and 30")
        self.name = name
        self.challenge_rating = challenge_rating
        self.hp = hp
        self.max_hp = hp
        self.ac = ac
        self.ability_scores = ability_scores.copy()
        self.damage_resistances = damage_resistances or []
        self.damage_immunities = damage_immunities or []
        self.special_abilities = special_abilities or []
        self.legendary_actions = legendary_actions or []
        self.multiattack = multiattack
        self.buffs = BuffManager()
        # Add default actions if not provided
        if actions is not None:
            self.actions = actions
        else:
            self.actions = [
                AttackAction(
                    name="Claw Attack",
                    description="Swipe with sharp claws.",
                    weapon_name="Claw",
                    damage_dice="1d6",
                    damage_type="slashing"
                )
            ]
    
    def ability_modifier(self, ability: str) -> int:
        """
        Calculate the modifier for a given ability score.
        
        Args:
            ability: The ability name ('str', 'dex', 'con', 'int', 'wis', 'cha')
            
        Returns:
            The ability modifier (score - 10) // 2
            
        Raises:
            ValueError: If ability is not a valid ability name
        """
        if ability not in self.ability_scores:
            raise ValueError(f"Invalid ability: {ability}")
        
        score = self.ability_scores[ability]
        return (score - 10) // 2
    
    def attack_bonus(self, weapon_type: str = "melee") -> int:
        """
        Calculate the attack bonus for a weapon attack.
        
        Args:
            weapon_type: Type of weapon ('melee', 'ranged', 'finesse')
            
        Returns:
            The attack bonus (ability modifier + proficiency bonus based on CR)
        """
        # Calculate proficiency bonus based on challenge rating
        # This is a simplified version - in the full rules, CR determines proficiency
        cr_value = self._parse_challenge_rating()
        if cr_value <= 1/4:
            proficiency_bonus = 2
        elif cr_value <= 1:
            proficiency_bonus = 2
        elif cr_value <= 4:
            proficiency_bonus = 3
        elif cr_value <= 8:
            proficiency_bonus = 4
        elif cr_value <= 12:
            proficiency_bonus = 5
        elif cr_value <= 16:
            proficiency_bonus = 6
        else:
            proficiency_bonus = 7
        
        # For simplicity, assume melee weapons use Strength and ranged use Dexterity
        if weapon_type == "ranged":
            ability_mod = self.ability_modifier('dex')
        elif weapon_type == "finesse":
            # Finesse weapons can use either Str or Dex, use the higher one
            str_mod = self.ability_modifier('str')
            dex_mod = self.ability_modifier('dex')
            ability_mod = max(str_mod, dex_mod)
        else:  # melee
            ability_mod = self.ability_modifier('str')
        
        return ability_mod + proficiency_bonus
    
    def roll_initiative(self) -> int:
        """
        Roll initiative: 1d20 + dex modifier.
        """
        import random
        return random.randint(1, 20) + self.ability_modifier('dex')

    def is_alive(self) -> bool:
        """
        Returns True if hp > 0.
        """
        return self.hp > 0

    def is_unconscious(self) -> bool:
        """
        Returns True if hp <= 0 (not dead/death saves for now).
        """
        return self.hp <= 0
    
    def _parse_challenge_rating(self) -> float:
        """
        Parse the challenge rating string into a numeric value.
        
        Returns:
            The challenge rating as a float
            
        Raises:
            ValueError: If challenge rating format is invalid
        """
        cr = self.challenge_rating.lower()
        
        if cr == "0":
            return 0
        elif cr == "1/8":
            return 1/8
        elif cr == "1/4":
            return 1/4
        elif cr == "1/2":
            return 1/2
        else:
            try:
                return float(cr)
            except ValueError:
                raise ValueError(f"Invalid challenge rating format: {self.challenge_rating}")
    
    def is_resistant_to(self, damage_type: str) -> bool:
        """
        Check if the monster is resistant to a specific damage type.
        
        Args:
            damage_type: The damage type to check
            
        Returns:
            True if the monster is resistant to the damage type, False otherwise
        """
        return damage_type.lower() in [d.lower() for d in self.damage_resistances]
    
    def __str__(self) -> str:
        """Return a string representation of the monster."""
        return f"{self.name} (CR {self.challenge_rating})"
    
    def __repr__(self) -> str:
        """Return a detailed string representation of the monster."""
        return (f"Monster(name='{self.name}', challenge_rating='{self.challenge_rating}', "
                f"hp={self.hp}, ac={self.ac}, ability_scores={self.ability_scores}, "
                f"damage_resistances={self.damage_resistances}, "
                f"damage_immunities={self.damage_immunities}, "
                f"special_abilities={self.special_abilities}, "
                f"legendary_actions={self.legendary_actions}, "
                f"multiattack={self.multiattack})") 

    @classmethod
    def from_api(cls, name, api_client=None):
        api = api_client or APIClient()
        api_data = api.fetch_monster_data(name)
        if not api_data:
            raise APIError(f"Monster '{name}' not found in API or local data.")
        # Validate and map API fields to Monster fields
        kwargs = {
            'name': api_data.get('name', name),
            'challenge_rating': api_data.get('challenge_rating', '1'),
            'hp': api_data.get('hit_points', 1),
            'ac': api_data.get('armor_class', 10),
            'ability_scores': {
                'str': api_data.get('strength', 10),
                'dex': api_data.get('dexterity', 10),
                'con': api_data.get('constitution', 10),
                'int': api_data.get('intelligence', 10),
                'wis': api_data.get('wisdom', 10),
                'cha': api_data.get('charisma', 10),
            },
            'damage_resistances': api_data.get('damage_resistances', []),
            'damage_immunities': api_data.get('damage_immunities', []),
            'special_abilities': api_data.get('special_abilities', []),
            'legendary_actions': api_data.get('legendary_actions', []),
            'multiattack': 'multiattack' in (api_data.get('actions', [{}])[0].get('name', '').lower()),
            'actions': None  # Could be mapped in detail if needed
        }
        return cls(**kwargs) 