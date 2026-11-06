"""
Action system for D&D 5e Combat Simulator.

Defines the Action base class and AttackAction subclass for use by characters and monsters.
"""

from typing import Any, Dict, Optional, Sequence, Tuple
import random
import re

from models.arena import Area
from models.buffs import (
    BuffManager,
    create_infernal_wound,
    create_mummy_rot,
    create_paralyzed_condition,
    create_prone_condition,
    has_condition,
    has_flag,
    is_incapacitated,
    is_paralyzed,
    is_prone,
    melee_hits_crit,
)
from models.damage import apply_damage, damage_after_save, reduce_max_hp, regain_hp
from models.rolls import attack_hits, attack_roll, is_critical, roll_saving_throw

# The conditions an attack's on_hit can apply
ON_HIT_CONDITIONS = ("paralyzed", "prone", "infernal_wound", "mummy_rot", "hp_drain")


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
        save_type: Optional[
            str
        ] = None,  # 'str', 'dex', 'con', etc. for save-based attacks
        save_dc: Optional[int] = None,  # DC for the saving throw
        on_hit: Optional[
            Dict[str, Any]
        ] = None,  # Save-or-condition rider, e.g. ghoul paralysis
        reach: Optional[int] = None,  # Melee reach in feet
        range: Optional[
            Sequence[int]
        ] = None,  # (normal, long) range in feet for ranged/thrown attacks
        area: Optional[
            Dict[str, Any]
        ] = None,  # Area effect shape, e.g. {'shape': 'cone', 'size': 30}
        recharge: Optional[
            int
        ] = None,  # "Recharge 5-6" -> 5: usable again on a d6 roll of 5 or more
        magical: bool = False,  # Gets past resistance to nonmagical weapon damage (Ki-Empowered Strikes)
        extra_damage: Optional[
            Dict[str, Any]
        ] = None,  # Damage of another type on a hit, see roll_extra_damage
        target_condition: Optional[
            Sequence[str]
        ] = None,  # Only usable on a target in one of these conditions
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
        if recharge is not None and not (
            isinstance(recharge, int) and 2 <= recharge <= 6
        ):
            raise ValueError(f"Invalid recharge for {name}: {recharge!r}")
        self.recharge = recharge
        self.ready = True  # False after a recharge action is used, until it recharges
        self.magical = magical
        # e.g. {'dice': '2d6', 'type': 'poison'} (a green dragon's bite), optionally with
        # 'save_type' and 'save_dc' for half on a successful save (a wyvern's sting)
        self.extra_damage = extra_damage
        # e.g. ['incapacitated', 'restrained'] (a vampire spawn's bite; grappling isn't modelled)
        self.target_condition = list(target_condition) if target_condition else None
        self.range = self._validate_range(range)
        # Melee attacks reach 5 ft unless they say otherwise. A ranged-only attack has no reach;
        # a thrown weapon like a javelin has both. Area effects (breath weapons) have a shape instead.
        if (
            reach is None
            and weapon_type != "ranged"
            and self.range is None
            and not area_effect
        ):
            reach = 5
        if reach is not None and (
            not isinstance(reach, int) or isinstance(reach, bool) or reach < 5
        ):
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

    def usable_on(self, target: Any) -> bool:
        """True unless the attack needs its target in a condition (target_condition) it isn't in."""
        if not self.target_condition:
            return True
        return any(
            (
                is_incapacitated(target)
                if condition == "incapacitated"
                else has_condition(target, condition)
            )
            for condition in self.target_condition
        )

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
        if hasattr(attacker, "attack_bonus"):
            return attacker.attack_bonus(self.weapon_type)
        return 0

    @staticmethod
    def parse_dice(dice_str: str):
        """
        Parse a dice string like '2d6+3', '1d4-1', '1d8', etc.
        Returns (num, die, mod)
        """
        pattern = r"^(\d+)[dD](\d+)([+-]\d+)?$"
        match = re.match(pattern, dice_str.replace(" ", ""))
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
            brutal = getattr(attacker, "brutal_critical_dice", None)
            extra = brutal(self) if callable(brutal) else 0
            num += extra if isinstance(extra, int) else 0
        rolls = [random.randint(1, die) for _ in range(num)]
        # Only add ability modifier if dice_mod is zero (i.e., not already included in dice string)
        mod = 0
        # A save-based area effect (a breath weapon) is just its dice
        if (
            hasattr(attacker, "ability_modifier")
            and dice_mod == 0
            and not (self.area_effect and self.save_type)
        ):
            # Use weapon_type to determine which ability modifier to use
            if self.weapon_type == "ranged":
                mod = attacker.ability_modifier("dex")
            elif self.weapon_type == "finesse":
                # Finesse weapons use the higher of STR or DEX
                mod = max(
                    attacker.ability_modifier("str"), attacker.ability_modifier("dex")
                )
            else:  # melee
                mod = attacker.ability_modifier("str")
        bonus = (
            attacker.weapon_damage_bonus(self)
            if callable(getattr(attacker, "weapon_damage_bonus", None))
            else 0
        )
        total = sum(rolls) + mod + dice_mod + (bonus if isinstance(bonus, int) else 0)
        return max(0, total)

    def _is_auto_critical(self, target: Any, within_5ft: Optional[bool] = None) -> bool:
        """
        Hits against a paralyzed or unconscious creature from within 5 ft are critical hits. Without
        positions (within_5ft is None), melee attacks are assumed to be within 5 ft and ranged ones not.
        """
        if within_5ft is None:
            within_5ft = self.weapon_type != "ranged"
        return within_5ft and melee_hits_crit(target)

    def roll_extra_damage(self, target: Any, critical: bool = False) -> Dict[str, Any]:
        """
        The extra damage of another type a hit deals (extra_damage), applied to the target with
        that type: dice doubled on a critical hit, halved on a successful save if it has one.
        """
        extra = self.extra_damage or {}
        if not extra.get("dice"):
            return {}
        num, die, mod = self.parse_dice(extra["dice"])
        amount = (
            sum(random.randint(1, die) for _ in range(num * 2 if critical else num))
            + mod
        )
        result = {"extra_damage_type": extra.get("type")}
        if extra.get("save_type") and extra.get("save_dc"):
            save = roll_saving_throw(target, extra["save_type"], extra["save_dc"])
            result["extra_damage_save"] = save
            if save["save_success"]:
                amount //= 2
        result["extra_damage"] = apply_damage(target, max(0, amount), extra.get("type"))
        return result

    def _apply_on_hit_effect(
        self, attacker: Any, target: Any, damage: int = 0
    ) -> Dict[str, Any]:
        """
        Apply this attack's on-hit condition to a target that was hit, unless it saves:
        'paralyzed' (a ghoul's claws), 'prone' (a wolf's bite), 'infernal_wound' (a horned
        devil's tail; a further hit on a wounded target deepens the wound without a save),
        'mummy_rot' (a mummy's fist) or 'hp_drain' (see _drain).
        """
        effect = self.on_hit or {}
        condition = effect.get("condition")
        if condition not in ON_HIT_CONDITIONS or not isinstance(
            getattr(target, "buffs", None), BuffManager
        ):
            return {}
        if condition == "hp_drain":
            return self._drain(attacker, target, damage, effect)
        if not target.is_alive():
            return {}
        if condition in (getattr(target, "condition_immunities", None) or []):
            return {"effect_immune": True}
        immune_races = {r.lower() for r in effect.get("immune_races", [])}
        if str(getattr(target, "race", "")).lower() in immune_races:
            return {"effect_immune": True}
        immune_types = {t.lower() for t in effect.get("immune_types", [])}
        if str(getattr(target, "creature_type", "") or "").lower() in immune_types:
            return {"effect_immune": True}
        source = getattr(attacker, "name", "Unknown")
        if condition == "paralyzed" and is_paralyzed(target):
            return {}
        if condition == "prone" and is_prone(target):
            return {}
        if condition == "infernal_wound":
            wound = target.buffs.get_condition("infernal_wound")
            if wound is not None:
                wound.metadata["wound_dice"].append(effect.get("wound_dice", "3d6"))
                return {"condition_applied": "Infernal Wound", "wound_deepened": True}

        save = roll_saving_throw(
            target, effect.get("save_type", "con"), effect.get("save_dc", 10)
        )
        result = {"effect_save": save}
        if not save["save_success"]:
            if condition == "paralyzed":
                buff = create_paralyzed_condition(
                    source,
                    effect.get("save_type", "con"),
                    effect.get("save_dc", 10),
                    effect.get("duration_rounds", 10),
                )
            elif condition == "prone":
                buff = create_prone_condition(source)
            elif condition == "mummy_rot":
                if target.buffs.has_condition("mummy_rot"):
                    return result
                buff = create_mummy_rot(source)
            else:
                buff = create_infernal_wound(source, effect.get("wound_dice", "3d6"))
            target.buffs.add_buff(buff)
            result["condition_applied"] = buff.name
        return result

    @staticmethod
    def _drain(
        attacker: Any, target: Any, damage: int, effect: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Life Drain (wight, wraith): unless the target succeeds on its save, its hit point maximum
        drops by the damage it took, even if the hit dropped it. A vampire spawn's bite has no save
        and heals the spawn by the same amount (heals_attacker).
        """
        if damage <= 0:
            return {}
        result = {}
        if effect.get("save_dc"):
            save = roll_saving_throw(
                target, effect.get("save_type", "con"), effect["save_dc"]
            )
            result["effect_save"] = save
            if save["save_success"]:
                return result
        result["hp_drained"] = reduce_max_hp(target, damage)
        result["target_max_hp_after"] = target.max_hp
        if effect.get("heals_attacker") and getattr(attacker, "hp", 0) > 0:
            result["attacker_healed"] = regain_hp(attacker, damage, magical=False)
        return result

    def execute(
        self,
        attacker: Any,
        target: Any,
        advantage: bool = False,
        disadvantage: bool = False,
        within_5ft: Optional[bool] = None,
        ac_bonus: int = 0,
        save_bonuses: Optional[Dict[Any, int]] = None,
    ) -> dict:
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
            target_names = [getattr(t, "name", str(t)) for t in target]
        else:
            target_names = getattr(target, "name", str(target))

        # Base result structure
        result = {
            "action": self.name,
            "weapon": self.weapon_name,
            "damage_type": self.damage_type,
            "description": self.description,
            "target": target_names,
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
                    save = roll_saving_throw(
                        t,
                        self.save_type,
                        self.save_dc,
                        cover_bonus=save_bonuses.get(t, 0),
                    )
                    save_success = save["save_success"]

                    # Half on a successful save (breath weapons), or none with Evasion
                    damage = damage_after_save(
                        t, base_damage, self.save_type, save_success, True
                    )

                    # Apply damage
                    damage = apply_damage(t, damage, self.damage_type)
                    total_damage_dealt += damage

                    target_results.append(
                        {
                            "target": getattr(t, "name", str(t)),
                            **save,
                            "damage": damage,
                            "hp_after": getattr(t, "hp", 0),
                        }
                    )

                result.update(
                    {
                        "save_type": self.save_type,
                        "save_dc": self.save_dc,
                        "area_effect": True,
                        "target_results": target_results,
                        "total_damage": total_damage_dealt,
                    }
                )

            else:
                # Area effect attack roll action (less common)
                bonus = self.hit_bonus(attacker)

                # Add buff bonuses to attack rolls
                buff_bonus = 0
                if hasattr(attacker, "buffs"):
                    buff_bonus = attacker.buffs.calculate_total_bonus("attack_rolls")

                # Roll damage once for AoE actions (same damage for all targets that are hit)
                base_damage = self.damage_roll(attacker)

                for t in targets_list:
                    d20 = attack_roll(
                        attacker,
                        t,
                        advantage,
                        disadvantage,
                        self.weapon_type != "ranged",
                    )
                    total_attack = d20.result + bonus + buff_bonus
                    target_ac = getattr(t, "ac", 10)
                    hit = attack_hits(d20.result, total_attack, target_ac)
                    critical = hit and (
                        is_critical(d20.result, attacker) or self._is_auto_critical(t)
                    )
                    damage = (
                        (
                            self.damage_roll(attacker, critical=True)
                            if critical
                            else base_damage
                        )
                        if hit
                        else 0
                    )

                    # Apply damage
                    if hit:
                        damage = apply_damage(t, damage, self.damage_type, critical)
                        total_damage_dealt += damage

                    target_results.append(
                        {
                            "target": getattr(t, "name", str(t)),
                            "advantage": d20.advantage,
                            "disadvantage": d20.disadvantage,
                            "attack_rolls": d20.rolls,
                            "critical": critical,
                            "attack_roll": d20.result,
                            "total_attack": total_attack,
                            "target_ac": target_ac,
                            "hit": hit,
                            "damage": damage,
                            "hp_after": getattr(t, "hp", 0),
                        }
                    )

                result.update(
                    {
                        "hit_bonus": bonus,
                        "buff_bonus": buff_bonus,
                        "area_effect": True,
                        "target_results": target_results,
                        "total_damage": total_damage_dealt,
                    }
                )

        else:
            # Single target action (standard behavior)
            attack_target = targets_list[0]
            d20 = attack_roll(
                attacker,
                attack_target,
                advantage,
                disadvantage,
                within_5ft if within_5ft is not None else self.weapon_type != "ranged",
            )
            bonus = self.hit_bonus(attacker)

            # Add buff bonuses to attack rolls
            buff_bonus = 0
            if hasattr(attacker, "buffs"):
                buff_bonus = attacker.buffs.calculate_total_bonus("attack_rolls")

            total_attack = d20.result + bonus + buff_bonus
            target_ac = getattr(targets_list[0], "ac", 10) + ac_bonus
            hit = attack_hits(d20.result, total_attack, target_ac)
            critical = hit and (
                is_critical(d20.result, attacker)
                or self._is_auto_critical(attack_target, within_5ft)
            )
            damage = (
                (
                    self.damage_roll(attacker, critical=True)
                    if critical
                    else self.damage_roll(attacker)
                )
                if hit
                else 0
            )

            # Apply damage to target HP if hit and target has hp
            if hit:
                damage = apply_damage(
                    targets_list[0],
                    damage,
                    self.damage_type,
                    critical,
                    self.magical or has_flag(attacker, "magical_weapon"),
                )
                extra = (
                    self.roll_extra_damage(attack_target, critical)
                    if self.extra_damage
                    else {}
                )
                result.update(extra)
                damage += extra.get("extra_damage", 0)

            if hit and self.on_hit:
                result.update(
                    self._apply_on_hit_effect(attacker, attack_target, damage)
                )

            result.update(
                {
                    "attack_roll": d20.result,
                    "attack_rolls": d20.rolls,
                    "hit_bonus": bonus,
                    "buff_bonus": buff_bonus,
                    "total_attack": total_attack,
                    "target_ac": target_ac,
                    "hit": hit,
                    "advantage": d20.advantage,
                    "disadvantage": d20.disadvantage,
                    "critical": critical,
                    "damage": damage,
                }
            )

        return result
