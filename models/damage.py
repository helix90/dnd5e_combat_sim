"""
Applying damage, with immunities, resistances and vulnerabilities.

Every place that hurts a creature should go through apply_damage so damage types
and damage-triggered abilities (Undead Fortitude) work the same way for weapons,
spells and class features.
"""
from typing import Any, Optional

from models.rolls import roll_saving_throw


def _types(creature: Any, attribute: str) -> set:
    values = getattr(creature, attribute, None)
    return {str(v).lower() for v in values} if isinstance(values, (list, tuple, set)) else set()


def has_ability(creature: Any, name: str) -> bool:
    """True if the creature's special_abilities include the named ability."""
    abilities = getattr(creature, 'special_abilities', None)
    return isinstance(abilities, list) and name in abilities


def adjust_damage(creature: Any, amount: int, damage_type: Optional[str]) -> int:
    """
    Damage after the creature's defenses: 0 if immune, halved (rounded down) if resistant,
    doubled if vulnerable. Resistance and vulnerability to the same type cancel out.
    """
    if amount <= 0 or not damage_type:
        return max(0, amount)
    kind = damage_type.lower()
    if kind in _types(creature, 'damage_immunities'):
        return 0
    resistant = kind in _types(creature, 'damage_resistances')
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


def apply_damage(creature: Any, amount: int, damage_type: Optional[str], critical: bool = False) -> int:
    """Reduce the creature's HP by the adjusted damage and return the damage actually dealt."""
    dealt = adjust_damage(creature, amount, damage_type)
    if hasattr(creature, 'hp'):
        hp_before = creature.hp
        creature.hp -= dealt
        if (dealt > 0 and hp_before > 0 and creature.hp <= 0
                and has_ability(creature, 'Undead Fortitude')
                and isinstance(getattr(creature, 'pending_log_entries', None), list)):
            _undead_fortitude(creature, dealt, damage_type, critical)
    return dealt
