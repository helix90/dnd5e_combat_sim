"""
Applying damage, with immunities, resistances and vulnerabilities.

Every place that hurts a creature should go through apply_damage so damage types
are handled the same way for weapons, spells and class features.
"""
from typing import Any, Optional


def _types(creature: Any, attribute: str) -> set:
    values = getattr(creature, attribute, None)
    return {str(v).lower() for v in values} if isinstance(values, (list, tuple, set)) else set()


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


def apply_damage(creature: Any, amount: int, damage_type: Optional[str]) -> int:
    """Reduce the creature's HP by the adjusted damage and return the damage actually dealt."""
    dealt = adjust_damage(creature, amount, damage_type)
    if hasattr(creature, 'hp'):
        creature.hp -= dealt
    return dealt
