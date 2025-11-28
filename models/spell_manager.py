"""
Spell Manager for D&D 5e Combat Simulator.

Handles loading and managing spells from JSON data files.
"""

import json
import os
from typing import Dict, List, Optional
from models.spells import Spell
from utils.exceptions import APIError, ValidationError
from utils.logging import log_exception


class SpellManager:
    """
    Manages spell loading and provides utility methods for spell operations.
    """
    
    def __init__(self, spells_file: str = "data/spells.json"):
        """
        Initialize the SpellManager.
        
        Args:
            spells_file: Path to the spells JSON file
        """
        self.spells_file = spells_file
        self.spells: Dict[str, Spell] = {}
        self.spells_by_level: Dict[int, List[Spell]] = {}
        self.load_spells()
    
    def load_spells(self) -> None:
        """
        Load spells from the JSON file.
        """
        try:
            with open(self.spells_file, 'r') as f:
                data = json.load(f)
            
            # Load cantrips
            for spell_data in data.get('cantrips', []):
                spell = self._create_spell_from_data(spell_data)
                self.spells[spell.name] = spell
                if 0 not in self.spells_by_level:
                    self.spells_by_level[0] = []
                self.spells_by_level[0].append(spell)
            
            # Load leveled spells
            for level in range(1, 10):  # Levels 1-9
                level_key = f'level_{level}'
                if level_key in data:
                    for spell_data in data[level_key]:
                        spell = self._create_spell_from_data(spell_data)
                        self.spells[spell.name] = spell
                        if level not in self.spells_by_level:
                            self.spells_by_level[level] = []
                        self.spells_by_level[level].append(spell)
                        
        except FileNotFoundError as e:
            log_exception(e)
            raise APIError(f"Spells file not found: {self.spells_file}")
        except json.JSONDecodeError as e:
            log_exception(e)
            raise ValidationError(f"Invalid JSON in spells file: {e}")
        except Exception as e:
            log_exception(e)
            raise APIError(f"Error loading spells: {e}")
    
    def _create_spell_from_data(self, spell_data: Dict) -> Spell:
        """
        Create a Spell object from dictionary data.
        
        Args:
            spell_data: Dictionary containing spell data
            
        Returns:
            Spell: The created Spell object
        """
        return Spell(
            name=spell_data['name'],
            level=spell_data['level'],
            school=spell_data['school'],
            casting_time=spell_data['casting_time'],
            range=spell_data['range'],
            duration=spell_data['duration'],
            components=spell_data['components'],
            damage_dice=spell_data.get('damage_dice'),
            damage_type=spell_data.get('damage_type'),
            save_type=spell_data.get('save_type'),
            save_dc_bonus=spell_data.get('save_dc_bonus', 0),
            description=spell_data.get('description', ''),
            is_attack_spell=spell_data.get('is_attack_spell', False),
            healing=spell_data.get('healing', False),
            area_effect=spell_data.get('area_effect', False),
            concentration=spell_data.get('concentration', False),
            is_buff_spell=spell_data.get('is_buff_spell', False),
            buff_data=spell_data.get('buff_data'),
            max_targets=spell_data.get('max_targets', 1)
        )
    
    def get_spell(self, spell_name: str) -> Optional[Spell]:
        """
        Get a spell by name.
        
        Args:
            spell_name: The name of the spell
            
        Returns:
            Spell or None: The spell if found, None otherwise
        """
        return self.spells.get(spell_name)
    
    def get_spells_by_level(self, level: int) -> List[Spell]:
        """
        Get all spells of a specific level.
        
        Args:
            level: The spell level (0 for cantrips)
            
        Returns:
            List[Spell]: List of spells at that level
        """
        return self.spells_by_level.get(level, [])
    
    def get_spells_by_school(self, school: str) -> List[Spell]:
        """
        Get all spells of a specific school.
        
        Args:
            school: The spell school
            
        Returns:
            List[Spell]: List of spells of that school
        """
        return [spell for spell in self.spells.values() if spell.school.lower() == school.lower()]
    
    def get_combat_spells(self) -> List[Spell]:
        """
        Get all spells that are useful in combat.
        
        Returns:
            List[Spell]: List of combat spells
        """
        combat_spells = []
        for spell in self.spells.values():
            if (spell.damage_dice or spell.healing or 
                spell.name in ['Shield', 'Counterspell', 'Web']):
                combat_spells.append(spell)
        return combat_spells
    
    def get_healing_spells(self) -> List[Spell]:
        """
        Get all healing spells.
        
        Returns:
            List[Spell]: List of healing spells
        """
        return [spell for spell in self.spells.values() if spell.healing]
    
    def get_damage_spells(self) -> List[Spell]:
        """
        Get all damage-dealing spells.
        
        Returns:
            List[Spell]: List of damage spells
        """
        return [spell for spell in self.spells.values() if spell.damage_dice and not spell.healing]
    
    def add_spells_to_character(self, character, spell_names: List[str]) -> None:
        """
        Add spells to a character's spell list.
        
        Args:
            character: The character to add spells to
            spell_names: List of spell names to add
        """
        for spell_name in spell_names:
            spell = self.get_spell(spell_name)
            if spell:
                character.add_spell(spell)
    
    def get_all_spell_names(self) -> List[str]:
        """
        Get all spell names.
        
        Returns:
            List[str]: List of all spell names
        """
        return list(self.spells.keys())
    
    def __len__(self) -> int:
        """Return the number of spells loaded."""
        return len(self.spells)
    
    def __str__(self) -> str:
        """Return a string representation of the spell manager."""
        return f"SpellManager with {len(self.spells)} spells loaded" 