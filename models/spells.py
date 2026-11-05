"""
Spell system for D&D 5e Combat Simulator.

Defines the Spell class and SpellAction subclass for spell casting in combat.
"""

from typing import Dict, List, Optional, Any, TYPE_CHECKING
import copy
import random
import re

from models import concentration, spell_effects
from models.actions import Action
from models.arena import Area
from models.buffs import cannot_regain_hp
from models.damage import apply_damage, damage_after_save, regain_hp
from models.rolls import attack_hits, attack_roll as roll_attack, is_critical, roll_saving_throw

if TYPE_CHECKING:
    from models.character import Character
    from models.monster import Monster


# Save spells that still deal half damage on a successful save; the rest deal none
HALF_ON_SAVE_SPELLS = {'Fireball', 'Lightning Bolt', 'Moonbeam', 'Call Lightning', 'Burning Hands', 'Ice Storm',
                       'Blight', 'Cone of Cold', 'Flame Strike'}

FEET_PER_MILE = 5280
TOUCH_RANGE_FEET = 5
ROUNDS_PER_MINUTE = 10


def parse_duration_rounds(text: Optional[str]) -> int:
    """
    Rounds a spell lasts from its duration text: "1 minute" -> 10, "Up to 10 minutes" -> 100,
    "1 hour" -> 600. Anything else ("Instantaneous", "Until dispelled") gives -1, for the rest of
    the fight.
    """
    match = re.search(r'(\d+)\s*(round|minute|hour)', (text or '').lower())
    if not match:
        return -1
    amount = int(match.group(1))
    return amount * {'round': 1, 'minute': ROUNDS_PER_MINUTE, 'hour': 60 * ROUNDS_PER_MINUTE}[match.group(2)]


def parse_range_feet(text: Optional[str]) -> Optional[int]:
    """
    A spell's range in feet from its text: "120 feet" -> 120, "Touch" -> 5, "Self" or
    "Self (15-foot cone)" -> 0, "1 mile" -> 5280. Ranges that aren't a distance ("Sight",
    "Unlimited", "Special") give None.
    """
    value = (text or '').strip().lower()
    if value.startswith('self'):
        return 0
    if value == 'touch':
        return TOUCH_RANGE_FEET
    match = re.fullmatch(r'(\d+)\s*(feet|foot|ft\.?|miles?)', value)
    if not match:
        return None
    amount = int(match.group(1))
    return amount * FEET_PER_MILE if match.group(2).startswith('mile') else amount


def roll_dice(dice: Optional[str], critical: bool = False) -> int:
    """Roll plain dice like '2d6' (twice as many on a critical hit); 0 for None."""
    if not dice:
        return 0
    num, die = (int(x) for x in dice.lower().split('d'))
    return sum(random.randint(1, die) for _ in range(num * (2 if critical else 1)))


def average_dice(dice: Optional[str]) -> float:
    if not dice:
        return 0.0
    num, die = (int(x) for x in dice.lower().split('d'))
    return num * (die + 1) / 2



def heal(target: Any, amount: int) -> int:
    """
    Heal a target with a spell and return the healing to report: the amount rolled, or 0 if the
    target can't regain hit points (mummy rot).
    """
    if cannot_regain_hp(target):
        return 0
    regain_hp(target, amount)
    return amount

class Spell:
    """
    Represents a D&D 5e spell with all its properties and effects.
    """
    def __init__(
        self,
        name: str,
        level: int,  # 0 for cantrips
        school: str,
        casting_time: str,
        range: str,
        duration: str,
        components: Dict[str, bool],  # {'verbal': True, 'somatic': False, 'material': False}
        damage_dice: Optional[str] = None,  # e.g., '1d10', '8d6'
        damage_type: Optional[str] = None,
        save_type: Optional[str] = None,  # 'str', 'dex', 'con', 'int', 'wis', 'cha'
        save_dc_bonus: int = 0,
        description: str = "",
        is_attack_spell: bool = False,  # True if spell requires attack roll
        healing: bool = False,  # True if spell heals instead of damages
        area_effect: bool = False,  # True if spell affects multiple targets
        concentration: bool = False,  # True if spell requires concentration
        is_buff_spell: bool = False,  # True if spell applies buffs
        buff_data: Optional[Dict[str, Any]] = None,  # Buff configuration data
        max_targets: int = 1,  # Maximum number of targets (e.g., 3 for Bless)
        area: Optional[Dict[str, Any]] = None,  # Shape on an arena, e.g. {'shape': 'sphere', 'size': 20}
        projectiles: int = 1,  # Darts, rays or beams, each rolled on its own (3 for Magic Missile)
        projectiles_per_slot: int = 0,  # More of them for each slot level above the spell's level
        cantrip_projectiles: bool = False,  # A cantrip that gains beams with level, not dice (Eldritch Blast)
        effect: Optional[str] = None,  # What it does besides damage and healing, see models/spell_effects.py
        combat: bool = True,  # False for spells with no use in a fight (Prestidigitation, Revivify)
        hit_point_dice: Optional[str] = None,  # Sleep's pool of hit points
        on_failed_save: Optional[Dict[str, Any]] = None,  # A buff the target gets if it fails its save (Vicious Mockery)
        higher_level_dice: Optional[str] = None,  # Added for each slot level above the spell's level ('1d6' for Fireball)
        higher_level_step: int = 1,  # Slot levels per higher_level_dice (2 for Spiritual Weapon)
        extra_damage: Optional[Dict[str, Any]] = None,  # A second part of another type, e.g. {'dice': '4d6', 'type': 'cold'}
        no_effect_on: Optional[List[str]] = None  # Creature types the spell does nothing to (Blight: undead, constructs)
    ) -> None:
        self.name = name
        self.level = level
        self.school = school
        self.casting_time = casting_time
        self.range = range
        self.duration = duration
        self.components = components
        self.damage_dice = damage_dice
        self.damage_type = damage_type
        self.save_type = save_type
        self.save_dc_bonus = save_dc_bonus
        self.description = description
        self.is_attack_spell = is_attack_spell
        self.healing = healing
        self.area_effect = area_effect
        self.concentration = concentration
        self.is_buff_spell = is_buff_spell
        self.buff_data = buff_data or {}
        self.max_targets = max_targets
        self.range_feet = parse_range_feet(range)  # None if the range isn't a distance
        self.area = Area.from_dict(area)
        self.projectiles = projectiles
        self.projectiles_per_slot = projectiles_per_slot
        self.cantrip_projectiles = cantrip_projectiles
        self.effect = effect
        self.combat = combat
        self.hit_point_dice = hit_point_dice
        self.on_failed_save = on_failed_save
        self.higher_level_dice = higher_level_dice
        self.higher_level_step = max(1, higher_level_step)
        self.extra_damage = extra_damage
        self.no_effect_on = [t.lower() for t in no_effect_on or []]

    def upcast_dice(self, slot_level: Optional[int]) -> Optional[str]:
        """The dice a higher slot adds: Fireball in a 5th-level slot adds '2d6'."""
        if not self.higher_level_dice or not slot_level or self.level == 0:
            return None
        steps = (slot_level - self.level) // self.higher_level_step
        if steps <= 0:
            return None
        num, die = self.higher_level_dice.lower().split('d')
        return f"{int(num) * steps}d{die}"

    def affects(self, creature: Any) -> bool:
        """False for a creature type the spell has no effect on (Blight on undead and constructs)."""
        return str(getattr(creature, 'creature_type', '') or '').lower() not in self.no_effect_on

    @property
    def bonus_action(self) -> bool:
        """Cast as a bonus action (Hunter's Mark, Spiritual Weapon)."""
        return 'bonus' in (self.casting_time or '').lower()

    @property
    def duration_rounds(self) -> int:
        return parse_duration_rounds(self.duration)

    def calculate_damage(self, caster_level: int = 1, critical: bool = False, slot_level: Optional[int] = None) -> int:
        """
        Calculate spell damage (or healing), including scaling for cantrips and higher slots.
        
        Args:
            caster_level: The level of the spellcaster
            critical: Roll the damage dice twice (a spell attack's critical hit)
            slot_level: The slot it's cast with: a higher one adds higher_level_dice

        Returns:
            int: Total damage
        """
        if not self.damage_dice:
            return 0
            
        # For cantrips, damage scales with level (Eldritch Blast gains beams instead)
        if self.level == 0 and not self.cantrip_projectiles:
            dice = self.damage_dice
            if caster_level >= 17:
                dice = dice.replace('1d', '4d')  # 4x damage at level 17+
            elif caster_level >= 11:
                dice = dice.replace('1d', '3d')  # 3x damage at level 11+
            elif caster_level >= 5:
                dice = dice.replace('1d', '2d')  # 2x damage at level 5+
        else:
            dice = self.damage_dice

        # Parse dice notation with optional modifier (e.g., "1d4+1", "2d6", "8d6-2")
        dice_str = dice.lower()
        modifier = 0

        # Extract modifier if present
        if '+' in dice_str:
            dice_part, mod_part = dice_str.split('+')
            modifier = int(mod_part)
            dice_str = dice_part
        elif '-' in dice_str and not dice_str.startswith('-'):
            dice_part, mod_part = dice_str.rsplit('-', 1)
            modifier = -int(mod_part)
            dice_str = dice_part

        if 'd' not in dice_str:  # a fixed amount (Heal's 70)
            return int(dice_str) + modifier
        num, die = dice_str.split('d')
        num = int(num) * (2 if critical else 1)
        die = int(die)
        rolls = [random.randint(1, die) for _ in range(num)]
        return sum(rolls) + modifier + roll_dice(self.upcast_dice(slot_level), critical)

    def projectile_count(self, caster_level: int = 1, slot_level: Optional[int] = None) -> int:
        """
        How many darts, rays or beams the spell makes: Magic Missile has 3 plus one per slot level
        above 1st, Scorching Ray 3 plus one per level above 2nd, and Eldritch Blast one beam, two
        at level 5, three at 11 and four at 17.
        """
        count = self.projectiles
        if self.level == 0 and self.cantrip_projectiles:
            count += sum(caster_level >= level for level in (5, 11, 17))
        elif slot_level and slot_level > self.level:
            count += self.projectiles_per_slot * (slot_level - self.level)
        return count

    def average_damage(self, caster_level: int = 1, slot_level: Optional[int] = None) -> float:
        """Average damage of the whole spell if everything hits, for every projectile together."""
        if not self.damage_dice:
            return 0.0
        dice = self.damage_dice.lower().replace(' ', '')
        match = re.fullmatch(r'(\d+)d(\d+)([+-]\d+)?', dice)
        if not match:
            return 0.0
        num, die, modifier = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
        if self.level == 0 and not self.cantrip_projectiles:
            num *= 1 + sum(caster_level >= level for level in (5, 11, 17))
        each = num * (die + 1) / 2 + modifier + average_dice(self.upcast_dice(slot_level))
        return each * self.projectile_count(caster_level, slot_level) + average_dice((self.extra_damage or {}).get('dice'))

    def get_save_dc(self, caster: Any) -> int:
        """
        Calculate the spell save DC for this spell.
        
        Args:
            caster: The spellcaster (Character or Monster)
            
        Returns:
            int: The spell save DC
        """
        if hasattr(caster, 'spell_save_dc'):
            return caster.spell_save_dc() + self.save_dc_bonus
        return 8 + self.save_dc_bonus  # Default fallback

    def __str__(self) -> str:
        """Return a string representation of the spell."""
        level_str = f"Level {self.level}" if self.level > 0 else "Cantrip"
        return f"{self.name} ({level_str}, {self.school})"

    def __repr__(self) -> str:
        """Return a detailed string representation of the spell."""
        return f"Spell(name='{self.name}', level={self.level}, school='{self.school}')"


class SpellAction(Action):
    """
    Represents a spell casting action in combat.
    """
    def __init__(
        self,
        spell: Spell,
        spell_slot_level: Optional[int] = None,
        target_count: int = 1,
        free: bool = False
    ) -> None:
        """
        Initialize a spell action.
        
        Args:
            spell: The Spell object to cast
            spell_slot_level: The level of spell slot to use (None for cantrips)
            target_count: Number of targets for area spells
            free: Keep using a spell that's already going instead of casting it: no slot, and
                concentration carries on (Call Lightning's later bolts, moving Moonbeam or
                Hunter's Mark)
        """
        super().__init__(action_type="spell", name=f"Cast {spell.name}", description=spell.description)
        self.spell = spell
        self.spell_slot_level = spell_slot_level
        self.target_count = target_count
        self.free = free

    def check_spell_slot_availability(self, caster: Any) -> bool:
        """
        Check if the caster has the required spell slot available.
        """
        # Cantrips don't use spell slots
        if self.spell.level == 0:
            return True
        required_level = self.spell_slot_level or self.spell.level
        # Prefer spell_slots_remaining, fallback to spell_slots
        slots = None
        if hasattr(caster, 'spell_slots_remaining'):
            slots = getattr(caster, 'spell_slots_remaining')
        elif hasattr(caster, 'spell_slots'):
            slots = getattr(caster, 'spell_slots')
        if slots is not None:
            # Try both int and str keys for compatibility with JSON data
            value = slots.get(required_level, 0) or slots.get(str(required_level), 0)
            # If value is a MagicMock, treat as 0
            try:
                from unittest.mock import MagicMock
                if isinstance(value, MagicMock):
                    value = 0
            except ImportError:
                pass
            return value > 0
        return False

    def consume_spell_slot(self, caster: Any) -> bool:
        """
        Consume a spell slot from the caster.
        """
        if self.spell.level == 0:
            return True
        required_level = self.spell_slot_level or self.spell.level
        slots = None
        if hasattr(caster, 'spell_slots_remaining'):
            slots = getattr(caster, 'spell_slots_remaining')
        elif hasattr(caster, 'spell_slots'):
            slots = getattr(caster, 'spell_slots')
        if slots is not None:
            # Try both int and str keys for compatibility with JSON data
            key_to_use = required_level if required_level in slots else str(required_level)
            value = slots.get(key_to_use, 0)
            try:
                from unittest.mock import MagicMock
                if isinstance(value, MagicMock):
                    value = 0
            except ImportError:
                pass
            if value > 0:
                slots[key_to_use] = value - 1
                return True
        return False

    def _touch(self) -> bool:
        """A touch or self-range spell attack is made from within 5 ft (a prone target gives
        advantage); others are assumed to be made from farther away unless an arena says otherwise."""
        range_feet = getattr(self.spell, 'range_feet', None)
        return range_feet is not None and range_feet <= 5 or str(getattr(self.spell, 'range', '')).lower() in ('touch', 'self')

    def roll_damage(self, caster: Any, critical: bool = False) -> int:
        """
        The spell's damage (or healing) dice, with a higher slot's extra dice. A wizard with
        Empowered Evocation adds INT to the damage of an evocation spell.
        """
        amount = self.spell.calculate_damage(getattr(caster, 'level', 1), critical, self.spell_slot_level)
        if not self.spell.healing and self.spell.school == 'Evocation' and 'Empowered Evocation' in (
                getattr(caster, 'class_features', None) or []) and hasattr(caster, 'ability_modifier'):
            amount += max(0, caster.ability_modifier('int'))
        return amount

    def _apply_damage(self, target: Any, amount: int, extra: int = 0, save_success: Optional[bool] = None,
                      critical: bool = False) -> int:
        """
        Damage to one target: nothing to a creature type the spell doesn't affect, halved (or
        none) on a successful save, and a second part of another type (Flame Strike's radiant)
        against the target's own resistances.
        """
        if not self.spell.affects(target):
            return 0
        parts = [(amount, self.spell.damage_type)]
        if self.spell.extra_damage:
            parts.append((extra, self.spell.extra_damage.get('type')))
        total = 0
        for value, kind in parts:
            if save_success is not None:
                value = damage_after_save(target, value, self.spell.save_type, save_success,
                                          self.spell.name in HALF_ON_SAVE_SPELLS)
            total += apply_damage(target, value, kind, critical)
        return total

    def roll_extra_damage(self, critical: bool = False) -> int:
        return roll_dice((self.spell.extra_damage or {}).get('dice'), critical)

    def _get_healing_amount(self, caster: Any) -> int:
        """
        Calculate healing, including spellcasting ability modifier if required.
        """
        healing = self.roll_damage(caster)
        # Add spellcasting ability modifier if the spell description mentions it
        if self.spell.healing and self.spell.description and "spellcasting ability modifier" in self.spell.description:
            if hasattr(caster, 'spellcasting_ability') and hasattr(caster, 'ability_modifier'):
                ability = caster.spellcasting_ability()
                healing += caster.ability_modifier(ability)
        return healing

    def _execute_projectiles(self, caster: Any, count: int, candidates: List[Any],
                             advantage: bool) -> Dict[str, Any]:
        """
        Magic Missile's darts, Scorching Ray's rays and Eldritch Blast's beams: each one rolls its
        own damage (and its own attack, for rays and beams) and can go to a different creature.
        Like a player, the caster splits them before rolling anything (the darts strike at once):
        the chosen target gets enough to drop it on average, then the next candidate, and any left
        over go back to the chosen target.
        """
        attack_bonus = caster.spell_attack_bonus() if hasattr(caster, 'spell_attack_bonus') else 0
        buff_bonus = caster.buffs.calculate_total_bonus('attack_rolls') if hasattr(caster, 'buffs') else 0
        each = self.spell.average_damage(getattr(caster, 'level', 1)) / self.spell.projectile_count(
            getattr(caster, 'level', 1))

        def expected(creature: Any, options: Dict[str, Any]) -> float:
            if not self.spell.is_attack_spell:
                return each
            needed = getattr(creature, 'ac', 10) + options.get('ac_bonus', 0) - attack_bonus - buff_bonus
            chance = min(0.95, max(0.05, (21 - needed) / 20))
            if options.get('disadvantage') and not advantage:
                chance *= chance
            return each * chance

        shots: List[Any] = []
        for i, (creature, options) in enumerate(candidates):
            left = count - len(shots)
            if left <= 0:
                break
            needed = -(-max(getattr(creature, 'hp', 0), 0) // max(expected(creature, options), 0.1))
            shots += [(creature, options)] * int(min(left, max(needed, 1 if i == 0 else 0)))
        shots += [candidates[0]] * (count - len(shots))

        attacks = []
        for creature, options in shots:
            entry: Dict[str, Any] = {'target': getattr(creature, 'name', str(creature))}
            hit, critical = True, False
            if self.spell.is_attack_spell:
                d20 = roll_attack(caster, creature, advantage, options.get('disadvantage', False),
                                  options.get('within_5ft', self._touch()))
                total_attack = d20.result + attack_bonus + buff_bonus
                target_ac = getattr(creature, 'ac', 10) + options.get('ac_bonus', 0)
                hit = attack_hits(d20.result, total_attack, target_ac)
                critical = hit and is_critical(d20.result, caster)
                entry.update({'attack_roll': d20.result, 'attack_rolls': d20.rolls, 'advantage': d20.advantage,
                              'disadvantage': d20.disadvantage, 'total_attack': total_attack,
                              'target_ac': target_ac, 'critical': critical})
            damage = 0
            if hit:
                damage = apply_damage(creature, self.spell.calculate_damage(getattr(caster, 'level', 1), critical,
                                                                            self.spell_slot_level),
                                      self.spell.damage_type, critical)
            entry.update({'hit': hit, 'damage': damage, 'damage_type': self.spell.damage_type,
                          'hp_after': creature.hp})
            attacks.append(entry)

        names = list(dict.fromkeys(a['target'] for a in attacks))
        result: Dict[str, Any] = {
            'target': names[0] if len(names) == 1 else ', '.join(names),
            'damage': sum(a['damage'] for a in attacks),
            'damage_type': self.spell.damage_type,
            'attacks': attacks,
            'projectiles': count,
            'hits': sum(a['hit'] for a in attacks),
        }
        if self.spell.is_attack_spell:
            result.update({'attack_bonus': attack_bonus, 'buff_bonus': buff_bonus,
                           'hit': any(a['hit'] for a in attacks)})
        if len(names) == 1:
            result['target_hp_after'] = attacks[-1]['hp_after']
        return result

    def execute(self, caster: Any, target: Any, advantage: bool = False, disadvantage: bool = False,
                ac_bonus: int = 0, save_bonus: int = 0,
                save_bonuses: Optional[Dict[Any, int]] = None,
                other_targets: Optional[List[Any]] = None, within_5ft: Optional[bool] = None) -> Dict[str, Any]:
        """
        Execute the spell: handle attack rolls, saving throws, and damage/healing.

        Args:
            caster: The spellcaster (Character or Monster)
            target: The target (Character, Monster, or list of targets for multi-target spells)
            advantage: Extra situational advantage on spell attack rolls, on top of active effects
            disadvantage: Extra situational disadvantage on spell attack rolls
            ac_bonus: Added to a single target's AC against a spell attack (cover)
            save_bonus: Added to a single target's saving throw (cover, for DEX saves)
            save_bonuses: For an area effect, each target's cover bonus to its saving throw
            other_targets: For a spell with several darts, rays or beams, (creature, options) pairs
                of other enemies they can go to, best first, with each one's 'ac_bonus' and
                'disadvantage' (see _execute_projectiles)

        Returns:
            dict: Result of the spell cast
        """
        # Convert single target to list for uniform handling
        targets_list = target if isinstance(target, list) else [target]
        # Check and consume spell slot
        if self.free:
            pass
        elif not self.check_spell_slot_availability(caster):
            return {
                'action': self.name,
                'success': False,
                'reason': 'No spell slot available',
                'description': self.description,
                'target': getattr(target, 'name', str(target))
            }
        
        if not self.free and not self.consume_spell_slot(caster):
            return {
                'action': self.name,
                'success': False,
                'reason': 'Failed to consume spell slot',
                'description': self.description,
                'target': getattr(target, 'name', str(target))
            }

        # Get target name(s) for result
        if isinstance(target, list):
            target_names = [getattr(t, 'name', str(t)) for t in target]
        else:
            target_names = getattr(target, 'name', str(target))

        result = {
            'action': self.name,
            'caster': getattr(caster, 'name', str(caster)),
            'spell': self.spell.name,
            'spell_level': self.spell.level,
            'success': True,
            'description': self.description,
            'target': target_names,
            'type': 'spell'  # Explicit type for easier identification
        }

        # A new concentration spell ends the one the caster was concentrating on
        holding = self.spell.concentration and not self.free
        if holding:
            ended = concentration.end(caster)
            if ended:
                result['concentration_ended'] = ended

        handler = spell_effects.HANDLERS.get(self.spell.effect)
        if handler is not None:
            fields, affected = handler(self, caster, targets_list, save_bonuses or {})
            result.update(fields)
        else:
            self._resolve(caster, target, targets_list, result, advantage, disadvantage, ac_bonus, save_bonus,
                          save_bonuses, other_targets, within_5ft)
            affected = targets_list if self.spell.is_buff_spell else []
            if self.spell.on_failed_save and result.get('save_success') is False:
                spell_effects.debuff(caster, targets_list[0], self.spell.on_failed_save)
            if self.spell.effect == 'call_lightning' and not self.free:
                spell_effects.call_lightning_storm(caster, self)
                affected = [caster]
        if holding and affected:
            concentration.start(caster, self.spell.name, affected, self.spell.duration_rounds,
                                self.spell_slot_level)
        return result

    def _resolve(self, caster: Any, target: Any, targets_list: List[Any], result: Dict[str, Any],
                 advantage: bool, disadvantage: bool, ac_bonus: int, save_bonus: int,
                 save_bonuses: Optional[Dict[Any, int]], other_targets: Optional[List[Any]],
                 within_5ft: Optional[bool] = None) -> Dict[str, Any]:
        """Attack rolls, saving throws, damage, healing and Bless-style buffs, filling in result."""
        # Handle buff spells
        if self.spell.is_buff_spell:
            from models.buffs import Buff

            # Apply buff to all targets
            buffs_applied = []
            for t in targets_list:
                # Create a separate buff instance for each target
                buff = Buff(
                    name=self.spell.buff_data.get('name', self.spell.name),
                    source=getattr(caster, 'name', str(caster)),
                    duration_rounds=self.spell.buff_data.get('duration_rounds', -1),
                    bonus_dice=self.spell.buff_data.get('bonus_dice'),
                    bonus_static=self.spell.buff_data.get('bonus_static', 0),
                    affects=self.spell.buff_data.get('affects', []),
                    concentration=self.spell.buff_data.get('concentration', self.spell.concentration),
                    metadata=copy.deepcopy(self.spell.buff_data.get('metadata', {}))
                )

                # Apply buff to this target
                if hasattr(t, 'buffs'):
                    t.buffs.add_buff(buff)
                    buffs_applied.append(getattr(t, 'name', str(t)))

            result.update({
                'buff_applied': len(buffs_applied) > 0,
                'buff_name': self.spell.buff_data.get('name', self.spell.name),
                'buff_duration': self.spell.buff_data.get('duration_rounds', -1),
                'targets_buffed': buffs_applied,
                'num_targets': len(buffs_applied)
            })

            if len(buffs_applied) == 0:
                result.update({
                    'reason': 'No targets could receive buffs'
                })

            return result

        projectiles = self.spell.projectile_count(getattr(caster, 'level', 1), self.spell_slot_level)
        if projectiles > 1 and not self.spell.area_effect and not self.spell.healing and not self.spell.save_type:
            first = (targets_list[0], {'ac_bonus': ac_bonus, 'disadvantage': disadvantage,
                                       'within_5ft': self._touch() if within_5ft is None else within_5ft})
            result.update(self._execute_projectiles(caster, projectiles, [first] + list(other_targets or []),
                                                    advantage))
            return result

        # Handle spell attack rolls
        if self.spell.is_attack_spell:
            # Check if this is an area effect spell
            if self.spell.area_effect and len(targets_list) > 1:
                # Area effect attack spell - make separate attack rolls for each target
                target_results = []
                total_damage_dealt = 0

                # Calculate attack bonus once (same for all targets)
                if hasattr(caster, 'spell_attack_bonus'):
                    attack_bonus = caster.spell_attack_bonus()
                else:
                    attack_bonus = 0

                # Add buff bonuses to spell attack rolls
                buff_bonus = 0
                if hasattr(caster, 'buffs'):
                    buff_bonus = caster.buffs.calculate_total_bonus('attack_rolls')

                # Roll damage once for AoE spells (same damage for all targets that are hit)
                base_damage = self.roll_damage(caster)
                base_healing = self._get_healing_amount(caster) if self.spell.healing else 0

                for t in targets_list:
                    attack_roll = roll_attack(caster, t, advantage, disadvantage, self._touch()).result
                    total_attack = attack_roll + attack_bonus + buff_bonus
                    target_ac = getattr(t, 'ac', 10)
                    hit = attack_hits(attack_roll, total_attack, target_ac)

                    if hit:
                        if self.spell.healing:
                            target_results.append({
                                'target': getattr(t, 'name', str(t)),
                                'attack_roll': attack_roll,
                                'total_attack': total_attack,
                                'target_ac': target_ac,
                                'hit': True,
                                'healing': heal(t, base_healing),
                                'hp_after': t.hp
                            })
                        else:
                            dealt = apply_damage(t, base_damage, self.spell.damage_type)
                            total_damage_dealt += dealt
                            target_results.append({
                                'target': getattr(t, 'name', str(t)),
                                'attack_roll': attack_roll,
                                'total_attack': total_attack,
                                'target_ac': target_ac,
                                'hit': True,
                                'damage': dealt,
                                'hp_after': t.hp
                            })
                    else:
                        target_results.append({
                            'target': getattr(t, 'name', str(t)),
                            'attack_roll': attack_roll,
                            'total_attack': total_attack,
                            'target_ac': target_ac,
                            'hit': False,
                            'damage': 0
                        })

                result.update({
                    'attack_bonus': attack_bonus,
                    'buff_bonus': buff_bonus,
                    'area_effect': True,
                    'target_results': target_results,
                    'total_damage': total_damage_dealt,
                    'damage_type': self.spell.damage_type
                })

            else:
                # Single target attack spell
                d20 = roll_attack(caster, targets_list[0], advantage, disadvantage,
                                  self._touch() if within_5ft is None else within_5ft)
                attack_roll = d20.result
                if hasattr(caster, 'spell_attack_bonus'):
                    attack_bonus = caster.spell_attack_bonus()
                else:
                    attack_bonus = 0

                # Add buff bonuses to spell attack rolls
                buff_bonus = 0
                if hasattr(caster, 'buffs'):
                    buff_bonus = caster.buffs.calculate_total_bonus('attack_rolls')

                total_attack = attack_roll + attack_bonus + buff_bonus
                target_ac = getattr(targets_list[0], 'ac', 10) + ac_bonus
                hit = attack_hits(attack_roll, total_attack, target_ac)
                critical = hit and not self.spell.healing and is_critical(attack_roll, caster)

                result.update({
                    'attack_roll': attack_roll,
                    'attack_rolls': d20.rolls,
                    'advantage': d20.advantage,
                    'disadvantage': d20.disadvantage,
                    'attack_bonus': attack_bonus,
                    'buff_bonus': buff_bonus,
                    'total_attack': total_attack,
                    'target_ac': target_ac,
                    'hit': hit,
                    'critical': critical
                })

                if hit:
                    if self.spell.healing:
                        healing = self._get_healing_amount(caster)
                        healing = heal(targets_list[0], healing)
                        result.update({
                            'healing': healing,
                            'target_hp_after': targets_list[0].hp
                        })
                    else:
                        damage = self._apply_damage(targets_list[0], self.roll_damage(caster, critical),
                                                    self.roll_extra_damage(critical), critical=critical)
                        result.update({
                            'damage': damage,
                            'damage_type': self.spell.damage_type,
                            'target_hp_after': targets_list[0].hp
                        })
                else:
                    result.update({
                        'damage': 0,
                        'healing': 0
                    })

        # Handle saving throw spells
        elif self.spell.save_type:
            save_dc = self.spell.get_save_dc(caster)

            # Check if this is an area effect spell
            if self.spell.area_effect and (len(targets_list) > 1 or save_bonuses is not None):
                # Area effect spell - apply to all targets
                target_results = []
                total_damage_dealt = 0

                # Roll damage once for AoE spells (same base damage for all targets)
                base_damage = self.roll_damage(caster)
                extra_damage = self.roll_extra_damage()

                for t in targets_list:
                    save = roll_saving_throw(t, self.spell.save_type, save_dc,
                                             cover_bonus=(save_bonuses or {}).get(t, 0), magical=True)
                    save_success = save['save_success']
                    damage = self._apply_damage(t, base_damage, extra_damage, save_success)
                    total_damage_dealt += damage

                    target_results.append({
                        'target': getattr(t, 'name', str(t)),
                        **save,
                        'damage': damage,
                        'hp_after': t.hp
                    })

                result.update({
                    'save_type': self.spell.save_type,
                    'save_dc': save_dc,
                    'area_effect': True,
                    'target_results': target_results,
                    'total_damage': total_damage_dealt,
                    'damage_type': self.spell.damage_type
                })

            else:
                # Single target saving throw spell
                save = roll_saving_throw(targets_list[0], self.spell.save_type, save_dc, cover_bonus=save_bonus,
                                         magical=True)
                save_success = save['save_success']

                result.update({
                    'save_type': self.spell.save_type,
                    'save_dc': save_dc,
                    **save,
                })

                # Apply effects based on save result
                if self.spell.healing:
                    healing = self._get_healing_amount(caster)
                    healing = heal(targets_list[0], healing)
                    result.update({
                        'healing': healing,
                        'target_hp_after': targets_list[0].hp
                    })
                else:
                    damage = self._apply_damage(targets_list[0], self.roll_damage(caster), self.roll_extra_damage(),
                                                save_success)
                    if not self.spell.affects(targets_list[0]):
                        result['no_effect'] = True
                    result.update({
                        'damage': damage,
                        'damage_type': self.spell.damage_type,
                        'target_hp_after': targets_list[0].hp
                    })

        # Handle spells with no attack or save (like Magic Missile)
        else:
            # An area effect spell, or healing for several creatures (Mass Cure Wounds)
            if (self.spell.area_effect or self.spell.healing) and len(targets_list) > 1:
                # Area effect spell - apply to all targets
                target_results = []
                total_damage_dealt = 0

                for t in targets_list:
                    if self.spell.healing:
                        healing = self._get_healing_amount(caster)
                        healing = heal(t, healing)
                        target_results.append({
                            'target': getattr(t, 'name', str(t)),
                            'healing': healing,
                            'hp_after': t.hp
                        })
                    else:
                        damage = self.roll_damage(caster)
                        damage = apply_damage(t, damage, self.spell.damage_type)
                        total_damage_dealt += damage
                        target_results.append({
                            'target': getattr(t, 'name', str(t)),
                            'damage': damage,
                            'hp_after': t.hp
                        })

                if self.spell.healing:
                    result.update({
                        'area_effect': True,
                        'target_results': target_results
                    })
                else:
                    result.update({
                        'area_effect': True,
                        'target_results': target_results,
                        'total_damage': total_damage_dealt,
                        'damage_type': self.spell.damage_type
                    })
            else:
                # Single target spell
                if self.spell.healing:
                    healing = self._get_healing_amount(caster)
                    healing = heal(targets_list[0], healing)
                    result.update({
                        'healing': healing,
                        'target_hp_after': targets_list[0].hp
                    })
                else:
                    damage = self.roll_damage(caster)
                    damage = apply_damage(targets_list[0], damage, self.spell.damage_type)
                    result.update({
                        'damage': damage,
                        'damage_type': self.spell.damage_type,
                        'target_hp_after': targets_list[0].hp
                    })

        return result 