"""
Action system for D&D 5e Combat Simulator.

Defines the Action base class and AttackAction subclass for use by characters and monsters.
"""

from typing import Any, Optional, TYPE_CHECKING
import random
import re

if TYPE_CHECKING:
    from models.character import Character
    from models.monster import Monster

class Action:
    """
    Base class for all combat actions (attack, spell, dodge, etc.).
    """
    def __init__(self, action_type: str, name: str, description: str) -> None:
        self.action_type = action_type  # e.g., 'attack', 'spell', 'dodge'
        self.name = name
        self.description = description

    def execute(self, attacker: Any, target: Any) -> dict:
        """
        Execute the action. To be implemented by subclasses.
        Args:
            attacker: The acting character or monster
            target: The target character or monster
        Returns:
            dict: Result of the action
        """
        raise NotImplementedError("execute() must be implemented by subclasses.")

class AttackAction(Action):
    """
    Represents a weapon or natural attack action.
    """
    def __init__(
        self,
        name: str,
        description: str,
        weapon_name: str,
        damage_dice: str,  # e.g., '1d8', '2d6'
        damage_type: str,
        hit_bonus: Optional[int] = None,
        weapon_type: str = "melee",  # 'melee', 'ranged', or 'finesse'
        area_effect: bool = False,  # True if this action affects multiple targets
        save_type: Optional[str] = None,  # 'str', 'dex', 'con', etc. for save-based attacks
        save_dc: Optional[int] = None  # DC for the saving throw
    ) -> None:
        super().__init__(action_type="attack", name=name, description=description)
        self.weapon_name = weapon_name
        self.damage_dice = damage_dice
        self.damage_type = damage_type
        self._hit_bonus = hit_bonus  # If None, calculate from attacker
        self.weapon_type = weapon_type  # Track weapon type for attack bonus calculation
        self.area_effect = area_effect
        self.save_type = save_type
        self.save_dc = save_dc

    def hit_bonus(self, attacker: Any) -> int:
        """
        Calculate the hit bonus for this attack.
        Args:
            attacker: The acting character or monster
        Returns:
            int: The attack bonus
        """
        if self._hit_bonus is not None:
            return self._hit_bonus
        # Pass weapon type to attacker's attack_bonus() method
        if hasattr(attacker, 'attack_bonus'):
            return attacker.attack_bonus(self.weapon_type)
        return 0

    @staticmethod
    def parse_dice(dice_str: str):
        """
        Parse a dice string like '2d6+3', '1d4-1', '1d8', etc.
        Returns (num, die, mod)
        """
        pattern = r'^(\d+)[dD](\d+)([+-]\d+)?$'
        match = re.match(pattern, dice_str.replace(' ', ''))
        if not match:
            raise ValueError(f"Invalid dice string: {dice_str}")
        num = int(match.group(1))
        die = int(match.group(2))
        mod = int(match.group(3)) if match.group(3) else 0
        return num, die, mod

    def damage_roll(self, attacker: Any) -> int:
        """
        Roll the weapon's damage dice and add attacker's relevant modifier if not already included in the dice string.
        Args:
            attacker: The acting character or monster
        Returns:
            int: Total damage
        """
        num, die, dice_mod = self.parse_dice(self.damage_dice)
        rolls = [random.randint(1, die) for _ in range(num)]
        # Only add ability modifier if dice_mod is zero (i.e., not already included in dice string)
        mod = 0
        if hasattr(attacker, 'ability_modifier') and dice_mod == 0:
            # Use weapon_type to determine which ability modifier to use
            if self.weapon_type == 'ranged':
                mod = attacker.ability_modifier('dex')
            elif self.weapon_type == 'finesse':
                # Finesse weapons use the higher of STR or DEX
                mod = max(attacker.ability_modifier('str'), attacker.ability_modifier('dex'))
            else:  # melee
                mod = attacker.ability_modifier('str')
        total = sum(rolls) + mod + dice_mod
        return max(0, total)

    def execute(self, attacker: Any, target: Any) -> dict:
        """
        Execute the attack: roll d20 + hit_bonus vs target AC, roll damage if hit.
        Args:
            attacker: The acting character or monster
            target: The target character or monster (or list of targets for area effects)
        Returns:
            dict: Result of the attack
        """
        # Convert single target to list for uniform handling
        targets_list = target if isinstance(target, list) else [target]

        # Get target name(s) for result
        if isinstance(target, list):
            target_names = [getattr(t, 'name', str(t)) for t in target]
        else:
            target_names = getattr(target, 'name', str(target))

        # Base result structure
        result = {
            'action': self.name,
            'weapon': self.weapon_name,
            'damage_type': self.damage_type,
            'description': self.description,
            'target': target_names
        }

        # Handle area effect actions
        if self.area_effect and len(targets_list) > 1:
            # Area effect action - apply to all targets
            target_results = []
            total_damage_dealt = 0

            # If this is a save-based action (like dragon breath)
            if self.save_type and self.save_dc:
                # Roll damage once for AoE actions (same base damage for all targets)
                base_damage = self.damage_roll(attacker)

                for t in targets_list:
                    save_roll = random.randint(1, 20)

                    # Calculate save bonus
                    if hasattr(t, 'saving_throw_bonus'):
                        save_bonus = t.saving_throw_bonus(self.save_type)
                    else:
                        save_bonus = 0

                    # Add buff bonuses to saving throws
                    buff_bonus = 0
                    if hasattr(t, 'buffs'):
                        buff_bonus = t.buffs.calculate_total_bonus('saving_throws')

                    total_save = save_roll + save_bonus + buff_bonus
                    save_success = total_save >= self.save_dc

                    # Apply damage (half on successful save for breath weapons)
                    damage = base_damage
                    if save_success:
                        damage = damage // 2

                    # Apply damage
                    if hasattr(t, 'hp'):
                        t.hp -= damage
                    total_damage_dealt += damage

                    target_results.append({
                        'target': getattr(t, 'name', str(t)),
                        'save_roll': save_roll,
                        'save_bonus': save_bonus,
                        'buff_bonus': buff_bonus,
                        'total_save': total_save,
                        'save_success': save_success,
                        'damage': damage,
                        'hp_after': getattr(t, 'hp', 0)
                    })

                result.update({
                    'save_type': self.save_type,
                    'save_dc': self.save_dc,
                    'area_effect': True,
                    'target_results': target_results,
                    'total_damage': total_damage_dealt
                })

            else:
                # Area effect attack roll action (less common)
                bonus = self.hit_bonus(attacker)

                # Add buff bonuses to attack rolls
                buff_bonus = 0
                if hasattr(attacker, 'buffs'):
                    buff_bonus = attacker.buffs.calculate_total_bonus('attack_rolls')

                # Roll damage once for AoE actions (same damage for all targets that are hit)
                base_damage = self.damage_roll(attacker)

                for t in targets_list:
                    attack_roll = random.randint(1, 20)
                    total_attack = attack_roll + bonus + buff_bonus
                    target_ac = getattr(t, 'ac', 10)
                    hit = total_attack >= target_ac
                    damage = base_damage if hit else 0

                    # Apply damage
                    if hit and hasattr(t, 'hp'):
                        t.hp -= damage
                        total_damage_dealt += damage

                    target_results.append({
                        'target': getattr(t, 'name', str(t)),
                        'attack_roll': attack_roll,
                        'total_attack': total_attack,
                        'target_ac': target_ac,
                        'hit': hit,
                        'damage': damage,
                        'hp_after': getattr(t, 'hp', 0)
                    })

                result.update({
                    'hit_bonus': bonus,
                    'buff_bonus': buff_bonus,
                    'area_effect': True,
                    'target_results': target_results,
                    'total_damage': total_damage_dealt
                })

        else:
            # Single target action (standard behavior)
            attack_roll = random.randint(1, 20)
            bonus = self.hit_bonus(attacker)

            # Add buff bonuses to attack rolls
            buff_bonus = 0
            if hasattr(attacker, 'buffs'):
                buff_bonus = attacker.buffs.calculate_total_bonus('attack_rolls')

            total_attack = attack_roll + bonus + buff_bonus
            target_ac = getattr(targets_list[0], 'ac', 10)
            hit = total_attack >= target_ac
            damage = self.damage_roll(attacker) if hit else 0

            # Apply damage to target HP if hit and target has hp
            if hit and hasattr(targets_list[0], 'hp'):
                targets_list[0].hp -= damage

            result.update({
                'attack_roll': attack_roll,
                'hit_bonus': bonus,
                'buff_bonus': buff_bonus,
                'total_attack': total_attack,
                'target_ac': target_ac,
                'hit': hit,
                'damage': damage
            })

        return result 