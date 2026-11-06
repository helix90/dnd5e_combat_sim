"""
Monster model for D&D 5e Combat Simulator.

This module contains the Monster class which represents a monster or NPC
in the D&D 5e system with all relevant attributes and methods for combat.
"""

import math
from typing import Any, Dict, List, Optional
from models.actions import AttackAction
from models.arena import normalize_speed, size_in_squares
from models.buffs import BuffManager


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
        actions: Optional[List] = None,
        regeneration: Optional[Dict[str, Any]] = None,
        damage_vulnerabilities: Optional[List[str]] = None,
        size: str = "medium",
        speed: Optional[Dict[str, Any]] = None,
        creature_type: Optional[str] = None,
        saving_throws: Optional[Dict[str, int]] = None,
        condition_immunities: Optional[List[str]] = None,
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
            regeneration: Optional regeneration rules, e.g. for a troll
                {'hp': 10, 'suppressed_by': ['acid', 'fire'], 'revives_at_zero': True}
            damage_vulnerabilities: Damage types that deal double damage to the monster
            size: Creature size ('tiny' to 'gargantuan'), which sets the squares it takes up
            speed: Speeds in feet by movement mode, e.g. {'walk': 40, 'fly': 80}
            creature_type: e.g. 'undead', 'fiend' (Turn Undead, Divine Smite)
            saving_throws: Total bonuses for the saves the monster is proficient in, e.g.
                {'dex': 6, 'wis': 3}; other saves use the ability modifier
            condition_immunities: Conditions that can't affect it, e.g. ['charmed', 'poisoned']
        Raises:
            ValueError: If ability scores, size or speed are invalid
        """
        required_abilities = {"str", "dex", "con", "int", "wis", "cha"}
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
        self.damage_vulnerabilities = damage_vulnerabilities or []
        self.special_abilities = special_abilities or []
        self.legendary_actions = legendary_actions or []
        self.multiattack = multiattack
        self.regeneration = regeneration
        size_in_squares(size)
        self.size = size.lower()
        self.speed = normalize_speed(speed)
        self.creature_type = (creature_type or "").lower() or None
        self.saving_throws = dict(saving_throws or {})
        self.condition_immunities = [str(c).lower() for c in condition_immunities or []]
        # Results of abilities triggered outside the monster's own turn (e.g. Undead Fortitude),
        # waiting for the combat log
        self.pending_log_entries: List[Dict[str, Any]] = []
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
                    damage_type="slashing",
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

    def saving_throw_bonus(self, ability: str) -> int:
        """The monster's bonus to a saving throw: its listed bonus if proficient, else the ability modifier."""
        if ability in self.saving_throws:
            return self.saving_throws[ability]
        return self.ability_modifier(ability)

    def attack_bonus(self, weapon_type: str = "melee") -> int:
        """
        Calculate the attack bonus for a weapon attack.

        Args:
            weapon_type: Type of weapon ('melee' or 'thrown' use STR, 'ranged' DEX, 'finesse' the higher)

        Returns:
            The attack bonus (ability modifier + proficiency bonus based on CR)
        """
        # Proficiency bonus by challenge rating (SRD): +2 at CR 0-4, +3 at 5-8, ... +9 at 29-30
        cr_value = self._parse_challenge_rating()
        proficiency_bonus = 2 + max(0, (math.ceil(cr_value) - 1) // 4)

        # For simplicity, assume melee weapons use Strength and ranged use Dexterity
        if weapon_type == "ranged":
            ability_mod = self.ability_modifier("dex")
        elif weapon_type == "finesse":
            # Finesse weapons can use either Str or Dex, use the higher one
            str_mod = self.ability_modifier("str")
            dex_mod = self.ability_modifier("dex")
            ability_mod = max(str_mod, dex_mod)
        else:  # melee and thrown weapons
            ability_mod = self.ability_modifier("str")

        return ability_mod + proficiency_bonus

    def roll_initiative(self) -> int:
        """
        Roll initiative: 1d20 + dex modifier.
        """
        import random

        return random.randint(1, 20) + self.ability_modifier("dex")

    @property
    def hp(self) -> int:
        """Current hit points; never below 0 (5e: excess damage doesn't reduce HP further)."""
        return self._hp

    @hp.setter
    def hp(self, value: int) -> None:
        # Floor at 0 so healing a downed creature starts from 0, as in 5e
        self._hp = max(0, value)

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
            return 1 / 8
        elif cr == "1/4":
            return 1 / 4
        elif cr == "1/2":
            return 1 / 2
        else:
            try:
                return float(cr)
            except ValueError:
                raise ValueError(
                    f"Invalid challenge rating format: {self.challenge_rating}"
                )

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
        return (
            f"Monster(name='{self.name}', challenge_rating='{self.challenge_rating}', "
            f"hp={self.hp}, ac={self.ac}, ability_scores={self.ability_scores}, "
            f"damage_resistances={self.damage_resistances}, "
            f"damage_immunities={self.damage_immunities}, "
            f"special_abilities={self.special_abilities}, "
            f"legendary_actions={self.legendary_actions}, "
            f"multiattack={self.multiattack})"
        )
