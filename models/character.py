"""
Character model for D&D 5e Combat Simulator.

This module contains the Character class which represents a player character
in the D&D 5e system with all relevant attributes and methods for combat.
"""

from typing import Dict, List, Optional, Any
from models.actions import AttackAction
from models.spells import Spell, SpellAction
from models.buffs import BuffManager


class Character:
    """
    A D&D 5e player character with combat-relevant attributes and methods.
    
    Attributes:
        name (str): The character's name
        level (int): The character's level (1-20)
        character_class (str): The character's class (e.g., 'Fighter', 'Wizard')
        race (str): The character's race (e.g., 'Human', 'Elf')
        ability_scores (Dict[str, int]): Dictionary of ability scores
        hp (int): Current and maximum hit points
        ac (int): Armor Class
        proficiency_bonus (int): Proficiency bonus based on level
        actions (List[Action]): List of available actions
        equipment (List[str]): List of equipment, weapons, armor, items
        spell_slots (Dict[int, int]): Spell slots by level (e.g., {1: 2, 2: 0})
        class_features (List[str]): List of class features (e.g., 'Action Surge')
        spell_list (List[str]): List of known/prepared spells
        saving_throw_proficiencies (List[str]): List of proficient saving throws
    """
    
    def __init__(
        self,
        name: str,
        level: int,
        character_class: str,
        race: str,
        ability_scores: Dict[str, int],
        hp: int,
        ac: int,
        proficiency_bonus: int,
        actions: Optional[List[Any]] = None,
        equipment: Optional[List[str]] = None,
        spell_slots: Optional[Dict[int, int]] = None,
        class_features: Optional[List[str]] = None,
        spell_list: Optional[List[str]] = None,
        saving_throw_proficiencies: Optional[List[str]] = None,
        features: Optional[List[str]] = None,
        items: Optional[List[str]] = None,
        spells: Optional[Dict[str, Any]] = None,
        reactions: Optional[List[Any]] = None,
        bonus_actions: Optional[List[Any]] = None,
        initiative_bonus: int = 0,
        notes: str = ""
    ) -> None:
        """
        Initialize a new Character instance.
        
        Args:
            name: The character's name
            level: The character's level (1-20)
            character_class: The character's class
            race: The character's race
            ability_scores: Dictionary with keys 'str', 'dex', 'con', 'int', 'wis', 'cha'
            hp: Hit points
            ac: Armor Class
            proficiency_bonus: Proficiency bonus
            
        Raises:
            ValueError: If level is not between 1 and 20, or if ability scores are invalid
        """
        if not 1 <= level <= 20:
            raise ValueError("Level must be between 1 and 20")
        
        required_abilities = {'str', 'dex', 'con', 'int', 'wis', 'cha'}
        if not all(ability in ability_scores for ability in required_abilities):
            raise ValueError(f"Ability scores must include: {required_abilities}")
        
        if any(score < 1 or score > 30 for score in ability_scores.values()):
            raise ValueError("Ability scores must be between 1 and 30")
        
        self.name = name
        self.level = level
        self.character_class = character_class
        self.race = race
        self.ability_scores = ability_scores.copy()
        self.hp = hp
        self.max_hp = hp
        self.ac = ac
        self.proficiency_bonus = proficiency_bonus
        self.equipment = equipment or []
        self.spell_slots = spell_slots or {}
        self.class_features = class_features or []
        self.spell_list = spell_list or []
        self.saving_throw_proficiencies = saving_throw_proficiencies or []
        self.spells = {}  # Dictionary to store Spell objects by name
        self.spell_slots_remaining = spell_slots.copy() if spell_slots else {}
        self.features = features or []
        self.items = items or []
        self.reactions = reactions or []
        self.bonus_actions = bonus_actions or []
        self.initiative_bonus = initiative_bonus
        self.notes = notes
        self.buffs = BuffManager()

        # Add default actions if not provided
        if actions is not None:
            self.actions = actions
        else:
            self.actions = [
                AttackAction(
                    name="Sword Attack",
                    description="Slash with a sword.",
                    weapon_name="Longsword",
                    damage_dice="1d8",
                    damage_type="slashing"
                ),
                AttackAction(
                    name="Dagger Attack",
                    description="Stab with a dagger.",
                    weapon_name="Dagger",
                    damage_dice="1d4",
                    damage_type="piercing"
                ),
                AttackAction(
                    name="Bow Attack",
                    description="Shoot with a shortbow.",
                    weapon_name="Shortbow",
                    damage_dice="1d6",
                    damage_type="piercing"
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
    
    def saving_throw_bonus(self, ability: str, proficient: bool = False) -> int:
        """
        Calculate the saving throw bonus for a given ability.
        
        Args:
            ability: The ability name ('str', 'dex', 'con', 'int', 'wis', 'cha')
            proficient: Whether the character is proficient in this saving throw
            
        Returns:
            The saving throw bonus (ability modifier + proficiency bonus if proficient)
        """
        modifier = self.ability_modifier(ability)
        if proficient:
            return modifier + self.proficiency_bonus
        return modifier
    
    def attack_bonus(self, weapon_type: str = "melee") -> int:
        """
        Calculate the attack bonus for a weapon attack.
        
        Args:
            weapon_type: Type of weapon ('melee', 'ranged', 'finesse')
            
        Returns:
            The attack bonus (ability modifier + proficiency bonus)
        """
        # For simplicity, assume melee weapons use Strength and ranged use Dexterity
        # In a full implementation, this would be more complex based on weapon properties
        if weapon_type == "ranged":
            ability_mod = self.ability_modifier('dex')
        elif weapon_type == "finesse":
            # Finesse weapons can use either Str or Dex, use the higher one
            str_mod = self.ability_modifier('str')
            dex_mod = self.ability_modifier('dex')
            ability_mod = max(str_mod, dex_mod)
        else:  # melee
            ability_mod = self.ability_modifier('str')
        
        return ability_mod + self.proficiency_bonus
    
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
    
    def spellcasting_ability(self) -> str:
        """
        Determine the spellcasting ability based on character class.
        
        Returns:
            str: The primary spellcasting ability ('int', 'wis', or 'cha')
        """
        if self.character_class in ['Wizard', 'Artificer']:
            return 'int'
        elif self.character_class in ['Cleric', 'Druid', 'Ranger']:
            return 'wis'
        elif self.character_class in ['Bard', 'Paladin', 'Sorcerer', 'Warlock']:
            return 'cha'
        else:
            return 'int'  # Default fallback
    
    def spell_attack_bonus(self) -> int:
        """
        Calculate the spell attack bonus.
        
        Returns:
            int: The spell attack bonus (spellcasting ability modifier + proficiency bonus)
        """
        ability_mod = self.ability_modifier(self.spellcasting_ability())
        return ability_mod + self.proficiency_bonus
    
    def spell_save_dc(self) -> int:
        """
        Calculate the spell save DC.
        
        Returns:
            int: The spell save DC (8 + proficiency bonus + spellcasting ability modifier)
        """
        ability_mod = self.ability_modifier(self.spellcasting_ability())
        return 8 + self.proficiency_bonus + ability_mod
    
    def add_spell(self, spell: Spell) -> None:
        """
        Add a spell to the character's spell list.
        
        Args:
            spell: The Spell object to add
        """
        self.spells[spell.name] = spell
        if spell.name not in self.spell_list:
            self.spell_list.append(spell.name)
    
    def get_spell(self, spell_name: str) -> Optional[Spell]:
        """
        Get a spell by name.
        
        Args:
            spell_name: The name of the spell
            
        Returns:
            Spell or None: The spell if found, None otherwise
        """
        return self.spells.get(spell_name)
    
    def can_cast_spell(self, spell_name: str, spell_slot_level: Optional[int] = None) -> bool:
        """
        Check if the character can cast a spell.
        
        Args:
            spell_name: The name of the spell
            spell_slot_level: The level of spell slot to use (None for cantrips)
            
        Returns:
            bool: True if the spell can be cast
        """
        spell = self.get_spell(spell_name)
        if not spell:
            return False
        
        # Cantrips don't use spell slots
        if spell.level == 0:
            return True
        
        # Check if we have the required spell slot
        required_level = spell_slot_level or spell.level
        return self.spell_slots_remaining.get(required_level, 0) > 0
    
    def cast_spell(self, spell_name: str, target: Any, spell_slot_level: Optional[int] = None) -> Dict[str, Any]:
        """
        Cast a spell at a target.
        
        Args:
            spell_name: The name of the spell to cast
            target: The target of the spell
            spell_slot_level: The level of spell slot to use (None for cantrips)
            
        Returns:
            dict: Result of the spell cast
        """
        spell = self.get_spell(spell_name)
        if not spell:
            return {
                'success': False,
                'reason': f'Spell {spell_name} not known'
            }
        
        spell_action = SpellAction(spell, spell_slot_level)
        return spell_action.execute(self, target)
    
    def get_available_spells(self) -> List[str]:
        """
        Get a list of spells the character can currently cast.
        
        Returns:
            List[str]: List of spell names that can be cast
        """
        available = []
        for spell_name in self.spell_list:
            if self.can_cast_spell(spell_name):
                available.append(spell_name)
        return available
    
    def __str__(self) -> str:
        """Return a string representation of the character."""
        return f"{self.name} ({self.race} {self.character_class} {self.level})"
    
    def __repr__(self) -> str:
        """Return a detailed string representation of the character."""
        return (f"Character(name='{self.name}', level={self.level}, "
                f"character_class='{self.character_class}', race='{self.race}', "
                f"ability_scores={self.ability_scores}, hp={self.hp}, "
                f"ac={self.ac}, proficiency_bonus={self.proficiency_bonus})") 