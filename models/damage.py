"""
Applying damage, with immunities, resistances and vulnerabilities.

Every place that hurts a creature should go through apply_damage so damage types
and damage-triggered abilities (Undead Fortitude) work the same way for weapons,
spells and class features.
"""
from typing import Any, Optional

from models import concentration
from models.buffs import BuffManager, cannot_regain_hp, close_wounds, end_on_damage
from models.rolls import roll_saving_throw

# The SRD monsters here that resist weapon damage (wraith, vampire spawn, mummy) resist it "from
# nonmagical attacks", so a magical attack (e.g. a monk's Ki-Empowered Strikes) gets through.
WEAPON_DAMAGE_TYPES = {'bludgeoning', 'piercing', 'slashing'}


def _types(creature: Any, attribute: str) -> set:
    values = getattr(creature, attribute, None)
    return {str(v).lower() for v in values} if isinstance(values, (list, tuple, set)) else set()


def _buff_resistances(creature: Any) -> set:
    """Resistances from active effects, e.g. a raging barbarian's to weapon damage."""
    buffs = getattr(creature, 'buffs', None)
    if not isinstance(buffs, BuffManager):
        return set()
    return {str(t).lower() for b in buffs.active_buffs for t in b.metadata.get('resistances', ())}


def has_ability(creature: Any, name: str) -> bool:
    """True if the creature's special_abilities include the named ability."""
    abilities = getattr(creature, 'special_abilities', None)
    return isinstance(abilities, list) and name in abilities


def adjust_damage(creature: Any, amount: int, damage_type: Optional[str], magical: bool = False) -> int:
    """
    Damage after the creature's defenses: 0 if immune, halved (rounded down) if resistant,
    doubled if vulnerable. Resistance and vulnerability to the same type cancel out. A magical
    attack ignores a monster's resistance to weapon damage (see WEAPON_DAMAGE_TYPES).
    """
    if amount <= 0 or not damage_type:
        return max(0, amount)
    kind = damage_type.lower()
    if kind in _types(creature, 'damage_immunities'):
        return 0
    resistant = (kind in _types(creature, 'damage_resistances')
                 and not (magical and kind in WEAPON_DAMAGE_TYPES)) or kind in _buff_resistances(creature)
    vulnerable = kind in _types(creature, 'damage_vulnerabilities')
    if resistant and not vulnerable:
        return amount // 2
    if vulnerable and not resistant:
        return amount * 2
    return amount


def _undead_fortitude(creature: Any, dealt: int, damage_type: Optional[str], critical: bool) -> None:
    """
    Undead Fortitude (SRD zombie): damage that drops it to 0 HP calls for a CON save, DC 5 + the
    damage taken, unless the damage is radiant or from a critical hit. On a success it drops to
    1 HP instead. The outcome is queued on the creature for the combat log.
    """
    if critical or (damage_type or '').lower() == 'radiant':
        return
    dc = 5 + dealt
    save = roll_saving_throw(creature, 'con', dc)
    if save['save_success']:
        creature.hp = 1
        outcome = f"succeeds on a DC {dc} CON save ({save['total_save']}) and drops to 1 HP instead"
    else:
        outcome = f"fails a DC {dc} CON save ({save['total_save']}) and goes down"
    creature.pending_log_entries.append({
        'action': 'Undead Fortitude',
        'type': 'condition',
        'condition': 'undead_fortitude',
        'description': f"is reduced to 0 HP; Undead Fortitude: {outcome}",
        **save,
    })


def apply_damage(creature: Any, amount: int, damage_type: Optional[str], critical: bool = False,
                 magical: bool = False) -> int:
    """
    Reduce the creature's HP by the adjusted damage and return the damage actually dealt. Any
    damage ends turning, magical sleep and Hypnotic Pattern on the creature, and a concentrating
    creature has to save to keep concentrating (see models/concentration.py).
    """
    dealt = adjust_damage(creature, amount, damage_type, magical)
    if dealt > 0:
        end_on_damage(creature)
    if hasattr(creature, 'hp'):
        hp_before = creature.hp
        creature.hp -= dealt
        if (dealt > 0 and hp_before > 0 and creature.hp <= 0
                and has_ability(creature, 'Undead Fortitude')
                and isinstance(getattr(creature, 'pending_log_entries', None), list)):
            _undead_fortitude(creature, dealt, damage_type, critical)
    if dealt > 0:
        concentration.take_damage(creature, dealt)
    return dealt


def damage_after_save(creature: Any, damage: int, save_type: Optional[str], saved: bool,
                      half_on_save: bool) -> int:
    """
    Damage from an effect that allows a saving throw: full on a failure, and on a success half
    (Fireball, breath weapons) or none (Sacred Flame). Evasion turns a DEX save for half into
    none on a success and half on a failure.
    """
    evasion = (half_on_save and save_type == 'dex'
               and 'Evasion' in (getattr(creature, 'class_features', None) or []))
    if saved:
        return 0 if evasion or not half_on_save else damage // 2
    return damage // 2 if evasion else damage


def regain_hp(creature: Any, amount: int, magical: bool = True) -> int:
    """
    Heal the creature by amount, up to its hit point maximum, and return the hit points it
    regained. A creature cursed with mummy rot regains none. Magical healing (spells, Lay on Hands)
    also closes infernal wounds.
    """
    if cannot_regain_hp(creature):
        return 0
    if magical:
        close_wounds(creature)
    hp_before = creature.hp
    creature.hp = min(creature.hp + max(0, amount), getattr(creature, 'max_hp', creature.hp))
    return max(0, creature.hp - hp_before)


def reduce_max_hp(creature: Any, amount: int) -> int:
    """
    Reduce the creature's hit point maximum (a wight's or wraith's Life Drain, a vampire spawn's
    bite) until it finishes a long rest; its hit points can't stay above the new maximum. A
    creature whose maximum reaches 0 dies, so healing can't bring it back. Returns the reduction.
    """
    max_hp = getattr(creature, 'max_hp', None)
    if not isinstance(max_hp, int) or amount <= 0:
        return 0
    reduced = min(amount, max_hp)
    creature.max_hp = max_hp - reduced
    creature.hp = min(creature.hp, creature.max_hp)
    return reduced
