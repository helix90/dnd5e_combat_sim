"""
What spells do besides plain damage and healing: Sleep, Entangle and Web, Hypnotic Pattern,
Moonbeam, Call Lightning, Hunter's Mark, Spiritual Weapon, Mage Armor, Mirror Image and spells
that grant a buff (Shield of Faith, Divine Favor, Magic Weapon, Protection from Evil and Good).

A spell's "effect" field in data/spells.json names its handler here. SpellAction.execute spends
the slot, ends the caster's old concentration and calls the handler, which returns the result
fields and the creatures that hold an effect tied to the caster's concentration (see
models/concentration.py). Combat calls the rest at the right moments: Moonbeam at the start of
the creature's turn, the weapon riders on a hit, Mirror Image when the caster is attacked.
"""
import copy
import random
from typing import Any, Callable, Dict, List, Optional, Tuple

from models import concentration
from models.buffs import (Buff, BuffManager, create_hypnotized_condition, create_paralyzed_condition,
                          create_restrained_condition, create_unconscious_condition, has_flag)
from models.damage import apply_damage, damage_after_save
from models.rolls import attack_hits, attack_roll, is_critical, roll_d20, roll_saving_throw

# Sleep doesn't affect undead
SLEEP_IMMUNE_TYPES = {'undead'}
# Mirror Image: the d20 an attack against the caster needs to hit a duplicate instead, by duplicates left
MIRROR_IMAGE_TARGET = {3: 6, 2: 8, 1: 11}
SPIRITUAL_WEAPON_DICE = '1d8'

Handler = Callable[[Any, Any, List[Any], Dict[Any, int]], Tuple[Dict[str, Any], List[Any]]]


def _name(creature: Any) -> str:
    return getattr(creature, 'name', str(creature))


def _names(creatures: List[Any]) -> str:
    return ', '.join(_name(c) for c in creatures)


def _roll(dice: str, critical: bool = False) -> int:
    num, die = (int(x) for x in dice.lower().split('d'))
    return sum(random.randint(1, die) for _ in range(num * (2 if critical else 1)))


def _has_buffs(creature: Any) -> bool:
    return isinstance(getattr(creature, 'buffs', None), BuffManager)


def immune_to(creature: Any, condition: str) -> bool:
    return condition in [str(c).lower() for c in getattr(creature, 'condition_immunities', None) or []]


def _spell_modifier(caster: Any) -> int:
    if hasattr(caster, 'spellcasting_ability') and hasattr(caster, 'ability_modifier'):
        return caster.ability_modifier(caster.spellcasting_ability())
    return 0


def _duration(action: Any) -> int:
    return action.spell.duration_rounds


def _dice(action: Any) -> str:
    """The spell's dice with what its slot adds: Moonbeam in a 4th-level slot is '2d10' + '2d10'."""
    extra = action.spell.upcast_dice(action.spell_slot_level)
    if not extra:
        return action.spell.damage_dice
    (n1, d1), (n2, d2) = (x.lower().split('d') for x in (action.spell.damage_dice, extra))
    return f"{int(n1) + int(n2)}d{d1}" if d1 == d2 else action.spell.damage_dice


def held_slot(caster: Any, spell_name: str) -> Optional[int]:
    """The slot a lasting spell the caster keeps going was cast with (Call Lightning's later bolts)."""
    buffs = getattr(caster, 'buffs', None)
    if not isinstance(buffs, BuffManager):
        return None
    return next((b.metadata.get('slot_level') for b in buffs.active_buffs
                 if b.metadata.get('storm') == spell_name or b.metadata.get('concentrating_on') == spell_name), None)


# Buff spells


def _buff(action: Any, caster: Any, targets: List[Any], _bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """A buff from the spell's buff_data on each target (Shield of Faith, Mirror Image...)."""
    data = action.spell.buff_data
    name = data.get('name', action.spell.name)
    buffed = []
    for target in targets:
        if not _has_buffs(target):
            continue
        target.buffs.remove_buff(name)
        target.buffs.add_buff(Buff(
            name=name, source=_name(caster),
            duration_rounds=data.get('duration_rounds', _duration(action)),
            bonus_dice=data.get('bonus_dice'), bonus_static=data.get('bonus_static', 0),
            affects=list(data.get('affects', [])), concentration=action.spell.concentration,
            metadata=copy.deepcopy(data.get('metadata', {}))))
        buffed.append(target)
    text = f"{_names(buffed)} {'gains' if len(buffed) == 1 else 'gain'} {name}" if buffed else 'no effect'
    return {'buff_applied': bool(buffed), 'buff_name': name, 'targets_buffed': [_name(t) for t in buffed],
            'effect_text': text}, buffed


def _mage_armor(action: Any, caster: Any, targets: List[Any], _bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """Mage Armor: base AC 13 + DEX (see Character.ac)."""
    return _armor(caster, targets[0]), []


def _armor(caster: Any, target: Any) -> Dict[str, Any]:
    base = 13 + (target.ability_modifier('dex') if hasattr(target, 'ability_modifier') else 0)
    target.buffs.remove_buff('Mage Armor')
    target.buffs.add_buff(Buff(name='Mage Armor', source=_name(caster), metadata={'base_ac': base}))
    return {'buff_applied': True, 'buff_name': 'Mage Armor', 'effect_text': f"AC {target.ac}"}


# Conditions


def _sleep(action: Any, caster: Any, targets: List[Any], _bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """
    Sleep: roll the hit point pool (5d8, 2d8 more per slot level above 1st). Creatures in the area
    fall asleep in order of current hit points, lowest first, while the pool covers them. Undead,
    creatures immune to being charmed and those already asleep are skipped.
    """
    spell = action.spell
    extra = max(0, (action.spell_slot_level or spell.level) - spell.level)
    pool = rolled = _roll(spell.hit_point_dice or '5d8') + (_roll(f'{2 * extra}d8') if extra else 0)
    eligible = sorted((t for t in targets if t.is_alive() and _has_buffs(t)
                       and getattr(t, 'creature_type', None) not in SLEEP_IMMUNE_TYPES
                       and not immune_to(t, 'charmed') and not t.buffs.has_condition('unconscious')),
                      key=lambda t: t.hp)
    slept = []
    for target in eligible:
        if target.hp > pool:
            break
        pool -= target.hp
        target.buffs.add_buff(create_unconscious_condition(_name(caster), _duration(action)))
        slept.append(target)
    text = (f"{_names(slept)} {'falls' if len(slept) == 1 else 'fall'} asleep" if slept else 'no one falls asleep')
    return {'hit_point_pool': rolled, 'conditions_applied': [_name(t) for t in slept], 'effect_text': text}, []


def _saving_condition(action: Any, caster: Any, targets: List[Any], bonuses: Dict[Any, int],
                      immunity: str, make: Callable[[], Buff], verb: str) -> Tuple[Dict[str, Any], List[Any]]:
    """Every target saves or gets the condition, which lasts while the caster concentrates."""
    spell = action.spell
    dc = spell.get_save_dc(caster)
    results, affected = [], []
    for target in targets:
        if not target.is_alive() or not _has_buffs(target):
            continue
        if immune_to(target, immunity):
            results.append({'target': _name(target), 'immune': True})
            continue
        save = roll_saving_throw(target, spell.save_type, dc, cover_bonus=bonuses.get(target, 0), magical=True)
        if not save['save_success']:
            target.buffs.add_buff(make())
            affected.append(target)
        results.append({'target': _name(target), **save})
    text = f"{_names(affected)} {verb}" if affected else 'everyone resists'
    return {'save_type': spell.save_type, 'save_dc': dc, 'target_results': results,
            'conditions_applied': [_name(t) for t in affected], 'effect_text': text}, affected


def _restrain(action: Any, caster: Any, targets: List[Any], bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """Entangle (STR save) and Web (DEX save): restrained while the caster concentrates."""
    dc = action.spell.get_save_dc(caster)
    return _saving_condition(action, caster, targets, bonuses, 'restrained',
                             lambda: create_restrained_condition(_name(caster), action.spell.name, dc, _duration(action)),
                             'restrained')


def _hypnotic_pattern(action: Any, caster: Any, targets: List[Any], bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """Hypnotic Pattern (WIS save): charmed and incapacitated until damaged, while the caster concentrates."""
    return _saving_condition(action, caster, targets, bonuses, 'charmed',
                             lambda: create_hypnotized_condition(_name(caster), _duration(action)),
                             'hypnotized')


def _hold(action: Any, caster: Any, targets: List[Any], bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """
    Hold Monster (WIS save): paralyzed while the caster concentrates, repeating the save at the end
    of each of its turns. No effect on undead.
    """
    dc = action.spell.get_save_dc(caster)
    target = targets[0]
    if not action.spell.affects(target):
        return {'save_type': action.spell.save_type, 'save_dc': dc, 'no_effect': True,
                'target_results': [{'target': _name(target), 'immune': True}],
                'conditions_applied': [], 'effect_text': f"no effect on {_name(target)}"}, []

    def paralyze() -> Buff:
        buff = create_paralyzed_condition(_name(caster), action.spell.save_type, dc, _duration(action))
        buff.concentration = True
        buff.metadata['magical'] = True  # the repeat saves are against a spell too
        return buff
    return _saving_condition(action, caster, [target], bonuses, 'paralyzed', paralyze, 'paralyzed')


def try_escape(creature: Any) -> Dict[str, Any]:
    """A restrained creature uses its action on a STR check against the spell's DC to get free."""
    condition = creature.buffs.get_condition('restrained')
    dc = condition.metadata['escape_dc']
    total = roll_d20().result + (creature.ability_modifier('str') if hasattr(creature, 'ability_modifier') else 0)
    freed = total >= dc
    if freed:
        creature.buffs.active_buffs = [b for b in creature.buffs.active_buffs if b is not condition]
    return {'action': 'Escape', 'type': 'condition', 'condition': 'restrained', 'condition_ended': freed,
            'description': (f"breaks free of the {condition.metadata['spell']} (STR {total} vs DC {dc})" if freed else
                            f"strains against the {condition.metadata['spell']} (STR {total} vs DC {dc}) and stays restrained")}


# Moonbeam


def _moonbeam(action: Any, caster: Any, targets: List[Any], _bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """
    Moonbeam shines on one creature and follows it; the creature saves at the start of each of its
    turns (see moonbeam_turn_start). Moving it to another creature (free=True on the action) costs
    the caster's action but no slot.
    """
    target = targets[0]
    name = _name(caster)
    for creature in concentration.held_by(caster):
        if _has_buffs(creature):
            creature.buffs.active_buffs = [b for b in creature.buffs.active_buffs
                                           if not (b.name == 'Moonbeam' and b.source == name)]
    target.buffs.add_buff(Buff(name='Moonbeam', source=name, duration_rounds=_duration(action), concentration=True,
                               metadata={'moonbeam': {'dice': _dice(action), 'save_dc': action.spell.get_save_dc(caster),
                                                      'damage_type': action.spell.damage_type}}))
    if action.free:
        concentration.add_creature(caster, target)
    verb = 'moves the beam onto' if action.free else 'a beam of moonlight shines on'
    return {'effect_text': f"{verb} {_name(target)}"}, [target]


def moonbeam_turn_start(creature: Any) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    A creature starting its turn in a Moonbeam makes a CON save: 2d10 radiant, half on a success.
    Returns (caster's name, log entry), or None if it isn't in one.
    """
    if not _has_buffs(creature):
        return None
    beam = next((b for b in creature.buffs.active_buffs if 'moonbeam' in b.metadata), None)
    if beam is None or not creature.is_alive():
        return None
    data = beam.metadata['moonbeam']
    save = roll_saving_throw(creature, 'con', data['save_dc'], magical=True)
    damage = damage_after_save(creature, _roll(data['dice']), 'con', save['save_success'], True)
    damage = apply_damage(creature, damage, data['damage_type'], magical=True)
    return beam.source, {'action': 'Cast Moonbeam', 'spell': 'Moonbeam', 'type': 'spell', 'target': _name(creature),
                         'damage': damage, 'damage_type': data['damage_type'], 'target_hp_after': creature.hp,
                         'save_type': 'con', 'save_dc': data['save_dc'], **save}


# Hunter's Mark and other riders on weapon hits


def _hunters_mark(action: Any, caster: Any, targets: List[Any], _bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """Hunter's Mark on one creature; moving it to another when that one drops is free (free=True)."""
    target = targets[0]
    target.buffs.add_buff(Buff(name="Hunter's Mark", source=_name(caster), duration_rounds=_duration(action),
                               concentration=True, metadata={'hunters_mark': True}))
    if action.free:
        concentration.add_creature(caster, target)
    return {'effect_text': f"{'moves the mark to' if action.free else 'marks'} {_name(target)}"}, [target]


def marked_by(caster: Any, enemies: List[Any]) -> Optional[Any]:
    """The living creature the caster's Hunter's Mark is on, if any."""
    name = _name(caster)
    return next((e for e in enemies if e.is_alive() and _has_buffs(e) and any(
        b.metadata.get('hunters_mark') and b.source == name for b in e.buffs.active_buffs)), None)


def weapon_riders(attacker: Any, attack: Dict[str, Any], target: Any) -> List[str]:
    """
    Extra damage on a weapon hit from the attacker's spells: Hunter's Mark (1d6 against its
    mark) and Divine Favor (1d4 radiant). Dice double on a critical hit. Returns notes for the log.
    """
    if not attack.get('hit') or not _has_buffs(attacker):
        return []
    critical = attack.get('critical', False)
    notes = []
    if marked_by(attacker, [target]) is target:
        extra = apply_damage(target, _roll('1d6', critical), attack.get('damage_type'), critical)
        attack['damage'] = attack.get('damage', 0) + extra
        notes.append(f"Hunter's Mark: +{extra}")
    for buff in attacker.buffs.active_buffs:
        dice = buff.metadata.get('weapon_damage_dice')
        if dice:
            kind = buff.metadata.get('weapon_damage_type') or attack.get('damage_type')
            extra = apply_damage(target, _roll(dice, critical), kind, critical, magical=True)
            attack['damage'] = attack.get('damage', 0) + extra
            notes.append(f"{buff.name}: +{extra} {kind}")
    return notes


# Spiritual Weapon


def _spiritual_weapon(action: Any, caster: Any, targets: List[Any], _bonuses: Dict[Any, int]) -> Tuple[Dict[str, Any], List[Any]]:
    """Spiritual Weapon appears for 1 minute and attacks at once (see spiritual_weapon_attack)."""
    caster.buffs.remove_buff('Spiritual Weapon')
    caster.buffs.add_buff(Buff(name='Spiritual Weapon', source=_name(caster), duration_rounds=_duration(action),
                               metadata={'spiritual_weapon': True,
                                         'spiritual_weapon_dice': _dice(action) if action.spell.damage_dice
                                         else SPIRITUAL_WEAPON_DICE}))
    return spiritual_weapon_attack(caster, targets[0]), []


def has_spiritual_weapon(caster: Any) -> bool:
    return has_flag(caster, 'spiritual_weapon')


def spiritual_weapon_attack(caster: Any, target: Any, advantage: bool = False, disadvantage: bool = False) -> Dict[str, Any]:
    """The weapon's melee spell attack: 1d8 (1d8 more per two slot levels above 2nd) + the caster's spellcasting modifier force damage."""
    weapon = next((b for b in caster.buffs.active_buffs if b.metadata.get('spiritual_weapon')), None) \
        if _has_buffs(caster) else None
    dice = (weapon.metadata.get('spiritual_weapon_dice') if weapon else None) or SPIRITUAL_WEAPON_DICE
    bonus = caster.spell_attack_bonus() if hasattr(caster, 'spell_attack_bonus') else 0
    d20 = attack_roll(caster, target, advantage, disadvantage, True)  # the weapon attacks from beside it
    total = d20.result + bonus
    hit = attack_hits(d20.result, total, getattr(target, 'ac', 10))
    critical = hit and is_critical(d20.result, caster)
    damage = apply_damage(target, _roll(dice, critical) + _spell_modifier(caster), 'force',
                          critical, magical=True) if hit else 0
    return {'target': _name(target), 'attack_roll': d20.result, 'attack_rolls': d20.rolls, 'total_attack': total,
            'target_ac': getattr(target, 'ac', 10), 'advantage': d20.advantage, 'disadvantage': d20.disadvantage,
            'hit': hit, 'critical': critical, 'damage': damage, 'damage_type': 'force', 'target_hp_after': target.hp}


# Mirror Image


class _Duplicate:
    """An illusory duplicate taking an attack meant for the caster: AC 10 + DEX, destroyed by a hit."""

    def __init__(self, caster: Any) -> None:
        self.name = f"{_name(caster)}'s duplicate"
        self.ac = 10 + (caster.ability_modifier('dex') if hasattr(caster, 'ability_modifier') else 0)
        self.hp = 1
        self.max_hp = 1

    def is_alive(self) -> bool:
        return self.hp > 0


def mirror_image_decoy(target: Any) -> Optional[Any]:
    """
    Mirror Image: roll a d20 for an attack against the caster; on 6+ with three duplicates (8+
    with two, 11+ with one) the attack targets a duplicate instead. Returns the duplicate to attack,
    or None to attack the caster. A hit destroys it (see mirror_image_hit).
    """
    if not _has_buffs(target):
        return None
    images = next((b for b in target.buffs.active_buffs if b.metadata.get('mirror_images')), None)
    if images is None:
        return None
    if random.randint(1, 20) < MIRROR_IMAGE_TARGET.get(images.metadata['mirror_images'], 21):
        return None
    return _Duplicate(target)


def mirror_image_hit(target: Any) -> int:
    """A duplicate was hit and vanishes. Returns the duplicates left."""
    images = next(b for b in target.buffs.active_buffs if b.metadata.get('mirror_images'))
    images.metadata['mirror_images'] -= 1
    if images.metadata['mirror_images'] <= 0:
        target.buffs.active_buffs = [b for b in target.buffs.active_buffs if b is not images]
        return 0
    return images.metadata['mirror_images']


HANDLERS: Dict[str, Handler] = {
    'buff': _buff,
    'mage_armor': _mage_armor,
    'sleep': _sleep,
    'restrain': _restrain,
    'hypnotic_pattern': _hypnotic_pattern,
    'moonbeam': _moonbeam,
    'hunters_mark': _hunters_mark,
    'spiritual_weapon': _spiritual_weapon,
    'hold': _hold,
}


def debuff(caster: Any, target: Any, data: Dict[str, Any]) -> None:
    """A buff from a spell's on_failed_save data on a target that failed its save (Vicious Mockery)."""
    if not _has_buffs(target) or not target.is_alive():
        return
    target.buffs.remove_buff(data['name'])
    target.buffs.add_buff(Buff(name=data['name'], source=_name(caster), duration_rounds=data.get('duration_rounds', 1),
                               metadata=copy.deepcopy(data.get('metadata', {}))))


def call_lightning_storm(caster: Any, action: Any) -> None:
    """After the first bolt, the storm stays while the caster concentrates: later bolts take an action but no slot."""
    caster.buffs.add_buff(Buff(name='Call Lightning', source=_name(caster), duration_rounds=_duration(action),
                               concentration=True, metadata={'storm': action.spell.name,
                                                             'slot_level': action.spell_slot_level}))


def prepare(character: Any) -> Optional[Dict[str, Any]]:
    """
    Before the fight: a wizard who knows Mage Armor and isn't wearing better armor has cast it
    (spending a 1st-level slot). Returns the log entry, or None.
    """
    spell = getattr(character, 'spells', {}).get('Mage Armor')
    if spell is None or not _has_buffs(character) or character.buffs.has_buff('Mage Armor'):
        return None
    slots = getattr(character, 'spell_slots_remaining', {})
    if 13 + character.ability_modifier('dex') <= character.ac or not slots.get(1):
        return None
    slots[1] -= 1
    return {'action': 'Cast Mage Armor', 'spell': 'Mage Armor', 'type': 'spell', 'target': _name(character),
            'description': 'before the fight', **_armor(character, character)}
