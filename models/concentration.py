"""
Concentration: a caster keeps one concentration spell going at a time.

Casting one puts a marker buff on the caster that names the spell and remembers the creatures
whose buffs and conditions depend on it (Bless's targets, the creatures Entangle restrains, the
creature in a Moonbeam). Ending concentration removes every concentration buff from the caster on
those creatures. It ends when the caster casts another concentration spell, drops to 0 HP, is
incapacitated, or fails the CON save that damage calls for (DC 10 or half the damage, whichever
is higher). See models/damage.py, which calls take_damage for every hit.
"""

from typing import Any, Dict, Iterable, List, Optional

from models.buffs import Buff, BuffManager, is_incapacitated
from models.rolls import roll_saving_throw

MARKER = "Concentration"


def _buffs(creature: Any) -> Optional[BuffManager]:
    buffs = getattr(creature, "buffs", None)
    return buffs if isinstance(buffs, BuffManager) else None


def _marker(caster: Any) -> Optional[Buff]:
    buffs = _buffs(caster)
    if buffs is None:
        return None
    return next(
        (
            b
            for b in buffs.active_buffs
            if b.name == MARKER and b.metadata.get("concentrating_on")
        ),
        None,
    )


def concentrating_on(caster: Any) -> Optional[str]:
    """The spell the caster is concentrating on, or None."""
    marker = _marker(caster)
    return marker.metadata["concentrating_on"] if marker else None


def held_by(caster: Any) -> List[Any]:
    """Creatures with effects that depend on the caster's concentration."""
    marker = _marker(caster)
    return list(marker.metadata["creatures"]) if marker else []


def start(
    caster: Any,
    spell_name: str,
    creatures: Iterable[Any],
    duration_rounds: int = -1,
    slot_level: Optional[int] = None,
) -> None:
    """Begin concentrating on a spell whose effects are on these creatures (ending any other)."""
    end(caster)
    buffs = _buffs(caster)
    if buffs is None:
        return
    buffs.add_buff(
        Buff(
            name=MARKER,
            source=getattr(caster, "name", str(caster)),
            duration_rounds=duration_rounds,
            metadata={
                "concentrating_on": spell_name,
                "creatures": list(dict.fromkeys(creatures)),
                "slot_level": slot_level,
            },
        )
    )


def add_creature(caster: Any, creature: Any) -> None:
    """Another creature now has an effect of the spell (Moonbeam moved onto it)."""
    marker = _marker(caster)
    if marker is not None and creature not in marker.metadata["creatures"]:
        marker.metadata["creatures"].append(creature)


def end(caster: Any) -> Optional[str]:
    """Stop concentrating: the spell's buffs and conditions end. Returns the spell, if there was one."""
    marker = _marker(caster)
    if marker is None:
        return None
    name = getattr(caster, "name", str(caster))
    for creature in [caster] + marker.metadata["creatures"]:
        buffs = _buffs(creature)
        if buffs is not None:
            buffs.active_buffs = [
                b
                for b in buffs.active_buffs
                if not (b.concentration and b.source == name)
            ]
    _buffs(caster).active_buffs = [
        b for b in _buffs(caster).active_buffs if b is not marker
    ]
    return marker.metadata["concentrating_on"]


def _log(caster: Any, entry: Dict[str, Any]) -> None:
    entries = getattr(caster, "pending_log_entries", None)
    if isinstance(entries, list):
        entries.append(entry)


def take_damage(caster: Any, damage: int) -> None:
    """
    Damage to a concentrating caster: at 0 HP concentration ends, otherwise a CON save against
    DC max(10, damage // 2) keeps it. The outcome is queued on the caster for the combat log.
    """
    spell = concentrating_on(caster)
    if spell is None or damage <= 0:
        return
    if getattr(caster, "hp", 1) <= 0:
        end(caster)
        _log(
            caster,
            {
                "action": "Concentration",
                "type": "condition",
                "condition": "concentration",
                "description": f"drops to 0 HP and loses concentration on {spell}",
            },
        )
        return
    dc = max(10, damage // 2)
    save = roll_saving_throw(caster, "con", dc)
    if save["save_success"]:
        outcome = (
            f"keeps concentrating on {spell} (DC {dc} CON save: {save['total_save']})"
        )
    else:
        end(caster)
        outcome = (
            f"loses concentration on {spell} (DC {dc} CON save: {save['total_save']})"
        )
    _log(
        caster,
        {
            "action": "Concentration",
            "type": "condition",
            "condition": "concentration",
            "description": outcome,
            **save,
        },
    )


def check_incapacitated(caster: Any) -> None:
    """An incapacitated caster (stunned, paralyzed, asleep) loses concentration."""
    spell = concentrating_on(caster)
    if spell is not None and is_incapacitated(caster):
        end(caster)
        _log(
            caster,
            {
                "action": "Concentration",
                "type": "condition",
                "condition": "concentration",
                "description": f"is incapacitated and loses concentration on {spell}",
            },
        )
