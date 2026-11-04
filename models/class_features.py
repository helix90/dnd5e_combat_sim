"""
Class features for D&D 5e Combat Simulator: what Rage, Divine Smite, Stunning Strike, Turn
Undead and the rest do, and how many uses a character has.

A character's features are strings in its data, e.g. 'Rage (3)', 'Ki (5 points)' or
'Lay on Hands (25)'. The number is the uses (or points) for the fight; without one it comes from
the character's level. Every fight starts rested, so each fight gets the full amount.

Combat decides when a feature is used (see Combat._take_turn and _weapon_attack); this module
holds the rules for what it does.
"""
import random
import re
from typing import Any, Dict, List, Optional

from models.buffs import (Buff, BuffManager, cannot_regain_hp, create_stunned_condition, create_turned_condition, is_stunned,
                          is_turned)
from models.damage import apply_damage, regain_hp
from models.rolls import roll_saving_throw
from models.spells import Spell, SpellAction
from models.weapons import MONK_WEAPONS, THROWN_WEAPONS, TWO_HANDED_WEAPONS

WEAPON_DAMAGE = ['bludgeoning', 'piercing', 'slashing']
SMITE_UNDEAD_TYPES = {'undead', 'fiend'}
TURN_UNDEAD_RANGE_FEET = 30


def features(creature: Any) -> List[str]:
    values = getattr(creature, 'class_features', None)
    return values if isinstance(values, list) else []


def feature(creature: Any, name: str) -> Optional[str]:
    """The creature's feature with this name, with or without a count: 'Rage' finds 'Rage (3)'."""
    return next((f for f in features(creature) if f == name or f.startswith(name + ' (')), None)


def has_feature(creature: Any, name: str) -> bool:
    return feature(creature, name) is not None


def _count(text: Optional[str]) -> Optional[int]:
    match = re.search(r'\((\d+)', text or '')
    return int(match.group(1)) if match else None


def _rages(level: int) -> int:
    return 2 if level < 3 else 3 if level < 6 else 4 if level < 12 else 5 if level < 17 else 6


def starting_resources(creature: Any) -> Dict[str, int]:
    """Uses (or points) of each limited feature the creature has, for one fight."""
    level = getattr(creature, 'level', 1)
    defaults = {
        'Rage': ('rage', _rages(level)),
        'Ki': ('ki', level),
        'Action Surge': ('action_surge', 2 if level >= 17 else 1),
        'Second Wind': ('second_wind', 1),
        'Lay on Hands': ('lay_on_hands', 5 * level),
        'Channel Divinity': ('channel_divinity', 0 if level < 2 else 1 if level < 6 else 2),
    }
    found = {}
    for name, (key, default) in defaults.items():
        if has_feature(creature, name):
            count = _count(feature(creature, name)) if name != 'Second Wind' else None
            found[key] = count if count is not None else default
    return found


def resource(creature: Any, name: str) -> int:
    values = getattr(creature, 'resources', None)
    return values.get(name, 0) if isinstance(values, dict) else 0


def spend(creature: Any, name: str, amount: int = 1) -> None:
    creature.resources[name] -= amount


# Passive features


def passive_buffs(creature: Any) -> List[Buff]:
    """Effects a character always has: Danger Sense (advantage on DEX saves)."""
    found = []
    if has_feature(creature, 'Danger Sense'):
        found.append(Buff('Danger Sense', getattr(creature, 'name', ''), metadata={'advantage': ['saving_throws:dex']}))
    return found


def critical_threshold(creature: Any) -> int:
    """A Champion fighter's Improved Critical: weapon attacks crit on 19-20 from 3rd level."""
    if feature(creature, 'Martial Archetype: Champion') and getattr(creature, 'level', 1) >= 3:
        return 19
    return 20


def attack_bonus_for(creature: Any, weapon_type: str) -> int:
    """Fighting Style: Archery gives +2 to attack rolls with ranged weapons."""
    return 2 if weapon_type == 'ranged' and has_feature(creature, 'Fighting Style: Archery') else 0


# Rage and Reckless Attack


def rage_damage(level: int) -> int:
    return 2 if level < 9 else 3 if level < 16 else 4


def is_raging(creature: Any) -> bool:
    buffs = getattr(creature, 'buffs', None)
    return isinstance(buffs, BuffManager) and buffs.has_buff('Rage')


def uses_strength(action: Any) -> bool:
    """A melee weapon attack using Strength (Rage damage, Reckless Attack, Divine Smite's 'melee')."""
    return getattr(action, 'reach', None) is not None and getattr(action, 'weapon_type', None) == 'melee'


def is_melee_weapon(action: Any) -> bool:
    return getattr(action, 'reach', None) is not None and getattr(action, 'action_type', None) == 'attack' \
        and not getattr(action, 'area_effect', False)


def is_melee_attack(action: Any, distance: Optional[int]) -> bool:
    """A melee weapon used in melee: a thrown javelin isn't (distance None means no arena)."""
    return is_melee_weapon(action) and (distance is None or distance <= action.reach)


def can_rage(creature: Any) -> bool:
    return resource(creature, 'rage') > 0 and not is_raging(creature)


def start_rage(creature: Any) -> Dict[str, Any]:
    """Rage for a minute: resistance to weapon damage and extra damage with Strength melee attacks."""
    spend(creature, 'rage')
    creature.buffs.add_buff(Buff('Rage', creature.name, duration_rounds=10,
                                 metadata={'resistances': WEAPON_DAMAGE}))
    return {'action': 'Rage', 'feature': 'Rage'}


def weapon_damage_bonus(creature: Any, action: Any) -> int:
    """
    Rage adds its bonus to the damage of melee weapon attacks made with Strength, and the Dueling
    fighting style +2 to attacks with a one-handed melee weapon. A weapon the character also throws
    (javelin, handaxe) doesn't get Dueling, since the attack can't tell a throw from a swing.
    """
    bonus = rage_damage(getattr(creature, 'level', 1)) if is_raging(creature) and uses_strength(action) else 0
    name = getattr(action, 'weapon_name', None) or getattr(action, 'name', '')
    if has_feature(creature, 'Fighting Style: Dueling') and is_melee_weapon(action) \
            and name not in TWO_HANDED_WEAPONS and name not in THROWN_WEAPONS:
        bonus += 2
    return bonus


def brutal_critical_dice(creature: Any, action: Any) -> int:
    """Brutal Critical (barbarian 9th level): extra weapon dice on a melee critical hit, 2 at 13th, 3 at 17th."""
    if not has_feature(creature, 'Brutal Critical') or not is_melee_weapon(action):
        return 0
    level = getattr(creature, 'level', 1)
    return 1 + (level >= 13) + (level >= 17)


def initiative_advantage(creature: Any) -> bool:
    """Feral Instinct (barbarian 7th level): advantage on initiative."""
    return has_feature(creature, 'Feral Instinct')


def reckless(creature: Any, action: Any, distance: Optional[int] = None) -> bool:
    """Reckless Attack (barbarian 2nd level): used whenever raging with a Strength melee attack."""
    return has_feature(creature, 'Reckless Attack') and is_raging(creature) and uses_strength(action) \
        and is_melee_attack(action, distance)


def be_reckless(creature: Any) -> None:
    """Attacks against the barbarian have advantage until its next turn (see Combat.next_turn)."""
    if not creature.buffs.has_buff('Reckless Attack'):
        creature.buffs.add_buff(Buff('Reckless Attack', creature.name,
                                     metadata={'advantage': ['attacks_against'], 'until_turn_start': True}))


# Second Wind and Action Surge


def wants_second_wind(creature: Any) -> bool:
    """Second Wind as a bonus action once the fighter is below half its hit points."""
    return (resource(creature, 'second_wind') > 0 and 0 < creature.hp < creature.max_hp / 2
            and not cannot_regain_hp(creature))


def second_wind(creature: Any) -> Dict[str, Any]:
    spend(creature, 'second_wind')
    healed = regain_hp(creature, random.randint(1, 10) + creature.level, magical=False)
    return {'action': 'Second Wind', 'feature': 'Second Wind', 'healing': healed}


# Divine Smite


def smite_dice(slot_level: int, target: Any) -> int:
    """2d8 for a 1st-level slot, +1d8 per level above (to 5d8), +1d8 against undead and fiends."""
    dice = min(5, 1 + slot_level)
    if getattr(target, 'creature_type', None) in SMITE_UNDEAD_TYPES:
        dice += 1
    return dice


def smite_slot(creature: Any) -> Optional[int]:
    """The lowest spell slot the paladin has left, or None."""
    if not has_feature(creature, 'Divine Smite'):
        return None
    slots = getattr(creature, 'spell_slots_remaining', None) or {}
    levels = sorted(int(level) for level, left in slots.items() if left > 0)
    return levels[0] if levels else None


def wants_smite(creature: Any, attack: Dict[str, Any], target: Any) -> Optional[int]:
    """
    The slot to smite with after a melee weapon hit, or None. The paladin smites on a critical
    hit (the dice double), against undead and fiends (the extra die), and when the smite's
    average damage would likely finish the target; otherwise it keeps its slots.
    """
    slot = smite_slot(creature)
    if slot is None or not attack.get('hit') or not target.is_alive():
        return None
    dice = smite_dice(slot, target)
    if attack.get('critical') or getattr(target, 'creature_type', None) in SMITE_UNDEAD_TYPES:
        return slot
    return slot if dice * 4.5 >= target.hp else None


def divine_smite(creature: Any, attack: Dict[str, Any], target: Any, slot: int) -> None:
    """Spend the slot and add the smite's radiant damage to the attack."""
    slots = creature.spell_slots_remaining
    key = slot if slot in slots else str(slot)
    slots[key] -= 1
    dice = smite_dice(slot, target) * (2 if attack.get('critical') else 1)
    dealt = apply_damage(target, sum(random.randint(1, 8) for _ in range(dice)), 'radiant',
                         attack.get('critical', False))
    attack['damage'] = attack.get('damage', 0) + dealt
    attack['divine_smite'] = {'slot_level': slot, 'damage': dealt}


# Monks: Martial Arts, Flurry of Blows, Stunning Strike


def martial_arts_strike(creature: Any) -> Optional[Any]:
    """The monk's unarmed strike for its Martial Arts bonus attack, or None if it isn't a monk."""
    if not has_feature(creature, 'Martial Arts'):
        return None
    return next((a for a in getattr(creature, 'actions', []) if getattr(a, 'name', '') == 'Unarmed Strike'), None)


def allows_martial_arts(action: Any) -> bool:
    """Martial Arts' bonus attack follows an Attack action with an unarmed strike or monk weapon."""
    return getattr(action, 'weapon_name', None) in MONK_WEAPONS and is_melee_weapon(action)


def ki_save_dc(creature: Any) -> int:
    return 8 + creature.proficiency_bonus + creature.ability_modifier('wis')


def wants_stunning_strike(creature: Any, attack: Dict[str, Any], target: Any, typical_hit: float) -> bool:
    """
    Stunning Strike (monk 5th level) after a melee weapon hit, for 1 ki: on a target that isn't
    already stunned and will survive another of the monk's hits, so the stun is worth something.
    """
    return (has_feature(creature, 'Stunning Strike') and resource(creature, 'ki') > 0 and attack.get('hit')
            and target.is_alive() and not is_stunned(target) and target.hp > typical_hit)


def stunning_strike(creature: Any, attack: Dict[str, Any], target: Any) -> None:
    spend(creature, 'ki')
    save = roll_saving_throw(target, 'con', ki_save_dc(creature))
    if not save['save_success']:
        target.buffs.add_buff(create_stunned_condition(creature.name))
    attack['stunning_strike'] = {'save': save, 'stunned': not save['save_success']}


def flurry_strikes(creature: Any) -> int:
    """Unarmed strikes for the bonus action: two (Flurry of Blows, 1 ki) if the monk has ki, else one."""
    return 2 if has_feature(creature, 'Ki') and resource(creature, 'ki') > 0 else 1


# Turn Undead


def destroy_undead_cr(creature: Any) -> Optional[float]:
    """The highest CR Destroy Undead destroys ('Destroy Undead (CR 1/2)'), or None."""
    text = feature(creature, 'Destroy Undead')
    if not text:
        return None
    match = re.search(r'CR\s*(\d+)(?:/(\d+))?', text)
    if not match:
        return None
    return int(match.group(1)) / int(match.group(2) or 1)


def can_turn_undead(creature: Any) -> bool:
    return resource(creature, 'channel_divinity') > 0 and getattr(creature, 'character_class', '') == 'Cleric'


def turnable(undead: List[Any]) -> List[Any]:
    """Undead that Turn Undead can still affect: alive and not already turned."""
    return [u for u in undead if getattr(u, 'creature_type', None) == 'undead' and u.is_alive() and not is_turned(u)]


def challenge_rating(creature: Any) -> float:
    parse = getattr(creature, '_parse_challenge_rating', None)
    return parse() if callable(parse) else 0.0


def turn_undead(cleric: Any, undead: List[Any]) -> Dict[str, Any]:
    """
    Each undead makes a WIS save against the cleric's spell DC. On a failure it is turned, or
    destroyed if its CR is at or below the cleric's Destroy Undead threshold.
    """
    spend(cleric, 'channel_divinity')
    destroy_cr = destroy_undead_cr(cleric)
    results = []
    dc = cleric.spell_save_dc()
    for creature in undead:
        save = roll_saving_throw(creature, 'wis', dc, magical=True)  # Channel Divinity is magical
        entry = {'target': creature.name, **save}
        if not save['save_success']:
            if destroy_cr is not None and challenge_rating(creature) <= destroy_cr:
                creature.hp = 0
                entry['destroyed'] = True
            else:
                creature.buffs.add_buff(create_turned_condition(cleric.name))
                entry['turned'] = True
        results.append(entry)
    turned = [r['target'] for r in results if r.get('turned')]
    destroyed = [r['target'] for r in results if r.get('destroyed')]
    return {
        'action': 'Turn Undead',
        'type': 'special',
        'feature': 'Channel Divinity',
        'target': [c.name for c in undead],
        'save_type': 'wis',
        'save_dc': dc,
        'target_results': results,
        'turned': turned,
        'destroyed': destroyed,
        'description': _turn_text(turned, destroyed, len(undead)),
    }


def _turn_text(turned: List[str], destroyed: List[str], count: int) -> str:
    parts = []
    if turned:
        parts.append('turns ' + ', '.join(turned))
    if destroyed:
        parts.append('destroys ' + ', '.join(destroyed))
    if not parts:
        return f"presents a holy symbol; all {count} undead resist" if count > 1 else \
            "presents a holy symbol; the undead resists"
    return 'presents a holy symbol and ' + ' and '.join(parts)


# Lay on Hands


class LayOnHandsAction(SpellAction):
    """
    A paladin's Lay on Hands: touch a creature to restore hit points from the pool. It moves and
    targets like a touch-range healing spell, but spends the pool instead of a spell slot.
    """

    def __init__(self) -> None:
        super().__init__(Spell('Lay on Hands', 0, '', '1 action', 'Touch', 'Instantaneous', {},
                               description='Restore hit points from a pool of healing power.', healing=True))
        self.name = 'Lay on Hands'

    def execute(self, caster: Any, target: Any, **_: Any) -> Dict[str, Any]:
        """Heal what the target is missing, as far as the pool allows."""
        healed = 0 if cannot_regain_hp(target) else min(resource(caster, 'lay_on_hands'), target.max_hp - target.hp)
        if healed > 0:
            spend(caster, 'lay_on_hands', healed)
            regain_hp(target, healed)
        return {'action': 'Lay on Hands', 'type': 'spell', 'feature': 'Lay on Hands', 'target': target.name,
                'healing': healed, 'target_hp_after': target.hp}


def feature_notes(result: Dict[str, Any]) -> List[str]:
    """Class features an action result used, its own and its attacks', for the log."""
    notes = list(result.get('features') or [])
    for attack in result.get('attacks') or result.get('individual_attacks') or []:
        if isinstance(attack, dict):
            notes += [n for n in attack.get('features') or [] if n not in notes]
    return notes
