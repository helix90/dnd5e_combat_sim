"""
Action system for D&D 5e Combat Simulator.

Defines the Action base class and AttackAction subclass for use by characters and monsters.
"""

from typing import Any, Dict, Optional, Sequence, Tuple, TYPE_CHECKING
import random
import re

from models.arena import Area
from models.buffs import BuffManager, create_paralyzed_condition, has_flag, is_paralyzed, melee_hits_crit
from models.damage import apply_damage, damage_after_save
from models.rolls import attack_hits, attack_roll, is_critical, roll_saving_throw

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
        save_dc: Optional[int] = None,  # DC for the saving throw
        on_hit: Optional[Dict[str, Any]] = None,  # Save-or-condition rider, e.g. ghoul paralysis
        reach: Optional[int] = None,  # Melee reach in feet
        range: Optional[Sequence[int]] = None,  # (normal, long) range in feet for ranged/thrown attacks
        area: Optional[Dict[str, Any]] = None,  # Area effect shape, e.g. {'shape': 'cone', 'size': 30}
        recharge: Optional[int] = None,  # "Recharge 5-6" -> 5: usable again on a d6 roll of 5 or more
        magical: bool = False  # Gets past resistance to nonmagical weapon damage (Ki-Empowered Strikes)
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
        # e.g. {'condition': 'paralyzed', 'save_type': 'con', 'save_dc': 10,
        #       'duration_rounds': 10, 'immune_races': ['Elf']}
        self.on_hit = on_hit
        self.area = Area.from_dict(area)
        if recharge is not None and not (isinstance(recharge, int) and 2 <= recharge <= 6):
            raise ValueError(f"Invalid recharge for {name}: {recharge!r}")
        self.recharge = recharge
        self.ready = True  # False after a recharge action is used, until it recharges
        self.magical = magical
        self.range = self._validate_range(range)
        # Melee attacks reach 5 ft unless they say otherwise. A ranged-only attack has no reach;
        # a thrown weapon like a javelin has both. Area effects (breath weapons) have a shape instead.
        if reach is None and weapon_type != 'ranged' and self.range is None and not area_effect:
            reach = 5
        if reach is not None and (not isinstance(reach, int) or isinstance(reach, bool) or reach < 5):
            raise ValueError(f"Invalid reach for {name}: {reach!r}")
        self.reach = reach

    @staticmethod
    def _validate_range(value: Optional[Sequence[int]]) -> Optional[Tuple[int, int]]:
        """(normal, long) range in feet; attacks beyond normal range up to long range are at
        disadvantage."""
        if value is None:
            return None
        try:
            normal, long = (int(v) for v in value)
        except (TypeError, ValueError):
            raise ValueError(f"Range must be [normal, long] in feet, got {value!r}")
        if not 0 < normal <= long:
            raise ValueError(f"Range must satisfy 0 < normal <= long, got {value!r}")
        return normal, long

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

    def damage_roll(self, attacker: Any, critical: bool = False) -> int:
        """
        Roll the weapon's damage dice and add attacker's relevant modifier if not already included in the dice string.
        Args:
            attacker: The acting character or monster
            critical: Roll the damage dice twice (modifiers are added once)
        Returns:
            int: Total damage
        """
        num, die, dice_mod = self.parse_dice(self.damage_dice)
        if critical:
            num *= 2
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
        bonus = attacker.weapon_damage_bonus(self) if callable(getattr(attacker, 'weapon_damage_bonus', None)) else 0
        total = sum(rolls) + mod + dice_mod + (bonus if isinstance(bonus, int) else 0)
        return max(0, total)


    def _is_auto_critical(self, target: Any, within_5ft: Optional[bool] = None) -> bool:
        """
        Hits against a paralyzed or unconscious creature from within 5 ft are critical hits. Without
        positions (within_5ft is None), melee attacks are assumed to be within 5 ft and ranged ones not.
        """
        if within_5ft is None:
            within_5ft = self.weapon_type != 'ranged'
        return within_5ft and melee_hits_crit(target)

    def _apply_on_hit_effect(self, attacker: Any, target: Any) -> Dict[str, Any]:
        """Apply this attack's on-hit condition (currently paralysis) to a target that was hit."""
        effect = self.on_hit or {}
        if effect.get('condition') != 'paralyzed' or not isinstance(getattr(target, 'buffs', None), BuffManager):
            return {}
        if not target.is_alive() or is_paralyzed(target):
            return {}
        immune_races = {r.lower() for r in effect.get('immune_races', [])}
        if str(getattr(target, 'race', '')).lower() in immune_races:
            return {'effect_immune': True}

        save = roll_saving_throw(target, effect.get('save_type', 'con'), effect.get('save_dc', 10))
        result = {'effect_save': save}
        if not save['save_success']:
            target.buffs.add_buff(create_paralyzed_condition(
                getattr(attacker, 'name', 'Unknown'),
                effect.get('save_type', 'con'),
                effect.get('save_dc', 10),
                effect.get('duration_rounds', 10),
            ))
            result['condition_applied'] = 'Paralyzed'
        return result

    def execute(self, attacker: Any, target: Any, advantage: bool = False, disadvantage: bool = False,
                within_5ft: Optional[bool] = None, ac_bonus: int = 0,
                save_bonuses: Optional[Dict[Any, int]] = None) -> dict:
        """
        Execute the attack: roll d20 + hit_bonus vs target AC, roll damage if hit.
        Args:
            attacker: The acting character or monster
            target: The target character or monster (or list of targets for area effects)
            advantage: Extra situational advantage on the attack roll(s), on top of active effects
            disadvantage: Extra situational disadvantage on the attack roll(s)
            within_5ft: Whether the attacker is within 5 ft of a single target (on an arena);
                None to assume melee attacks are and ranged ones aren't
            ac_bonus: Added to a single target's AC (cover: +2 half, +5 three-quarters)
            save_bonuses: For an area effect, each target's cover bonus to its saving throw
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

        # Handle area effect actions (even one caught alone saves rather than being attacked)
        save_bonuses = save_bonuses or {}
        if self.area_effect:
            # Area effect action - apply to all targets
            target_results = []
            total_damage_dealt = 0

            # If this is a save-based action (like dragon breath)
            if self.save_type and self.save_dc:
                # Roll damage once for AoE actions (same base damage for all targets)
                base_damage = self.damage_roll(attacker)

                for t in targets_list:
                    save = roll_saving_throw(t, self.save_type, self.save_dc, cover_bonus=save_bonuses.get(t, 0))
                    save_success = save['save_success']

                    # Half on a successful save (breath weapons), or none with Evasion
                    damage = damage_after_save(t, base_damage, self.save_type, save_success, True)

                    # Apply damage
                    damage = apply_damage(t, damage, self.damage_type)
                    total_damage_dealt += damage

                    target_results.append({
                        'target': getattr(t, 'name', str(t)),
                        **save,
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
                    d20 = attack_roll(attacker, t, advantage, disadvantage)
                    total_attack = d20.result + bonus + buff_bonus
                    target_ac = getattr(t, 'ac', 10)
                    hit = attack_hits(d20.result, total_attack, target_ac)
                    critical = hit and (is_critical(d20.result, attacker) or self._is_auto_critical(t))
                    damage = (self.damage_roll(attacker, critical=True) if critical else base_damage) if hit else 0

                    # Apply damage
                    if hit:
                        damage = apply_damage(t, damage, self.damage_type, critical)
                        total_damage_dealt += damage

                    target_results.append({
                        'target': getattr(t, 'name', str(t)),
                        'advantage': d20.advantage,
                        'disadvantage': d20.disadvantage,
                        'attack_rolls': d20.rolls,
                        'critical': critical,
                        'attack_roll': d20.result,
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
            attack_target = targets_list[0]
            d20 = attack_roll(attacker, attack_target, advantage, disadvantage)
            bonus = self.hit_bonus(attacker)

            # Add buff bonuses to attack rolls
            buff_bonus = 0
            if hasattr(attacker, 'buffs'):
                buff_bonus = attacker.buffs.calculate_total_bonus('attack_rolls')

            total_attack = d20.result + bonus + buff_bonus
            target_ac = getattr(targets_list[0], 'ac', 10) + ac_bonus
            hit = attack_hits(d20.result, total_attack, target_ac)
            critical = hit and (is_critical(d20.result, attacker) or self._is_auto_critical(attack_target, within_5ft))
            damage = (self.damage_roll(attacker, critical=True) if critical else self.damage_roll(attacker)) if hit else 0

            # Apply damage to target HP if hit and target has hp
            if hit:
                damage = apply_damage(targets_list[0], damage, self.damage_type, critical,
                                      self.magical or has_flag(attacker, 'magical_weapon'))

            if hit and self.on_hit:
                result.update(self._apply_on_hit_effect(attacker, attack_target))

            result.update({
                'attack_roll': d20.result,
                'attack_rolls': d20.rolls,
                'hit_bonus': bonus,
                'buff_bonus': buff_bonus,
                'total_attack': total_attack,
                'target_ac': target_ac,
                'hit': hit,
                'advantage': d20.advantage,
                'disadvantage': d20.disadvantage,
                'critical': critical,
                'damage': damage
            })

        return result 