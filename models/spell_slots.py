"""
A caster's spell slots, as spell_slots_remaining: a dict of spell level to slots left, with int
keys (Character normalizes the JSON's strings). Every check and spend goes through here, so a
spell is never paid for with a slot below its level.
"""

from typing import Any, Dict, Optional


def remaining(creature: Any) -> Dict[int, int]:
    """The creature's slots left by level, or {} if it has none."""
    slots = getattr(creature, "spell_slots_remaining", None)
    return slots if isinstance(slots, dict) else {}


def lowest_slot(creature: Any, level: int) -> Optional[int]:
    """The lowest spell slot of at least this level the creature has left, or None."""
    return min(
        (slot for slot, left in remaining(creature).items() if slot >= level and left > 0),
        default=None,
    )


def can_spend(creature: Any, spell_level: int, slot_level: Optional[int] = None) -> bool:
    """
    Whether the creature can cast a spell of spell_level with a slot of slot_level (the spell's
    own level if None). A cantrip needs no slot; a slot below the spell's level can't cast it.
    """
    if spell_level == 0:
        return True
    slot_level = slot_level or spell_level
    return slot_level >= spell_level and remaining(creature).get(slot_level, 0) > 0


def spend(creature: Any, spell_level: int, slot_level: Optional[int] = None) -> bool:
    """Spend the slot can_spend checks, if it can; returns whether it did."""
    if not can_spend(creature, spell_level, slot_level):
        return False
    if spell_level:
        remaining(creature)[slot_level or spell_level] -= 1
    return True
