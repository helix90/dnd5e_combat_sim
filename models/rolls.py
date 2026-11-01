"""
d20 rolls with advantage and disadvantage for D&D 5e Combat Simulator.

Effects grant advantage or disadvantage by listing roll keys in their Buff metadata:

    Buff(..., metadata={"advantage": ["attacks_against"]})        # e.g. Paralyzed
    Buff(..., metadata={"advantage": ["saving_throws:dex"]})      # e.g. Haste
    Buff(..., metadata={"disadvantage": ["attack_rolls"]})        # e.g. Poisoned

Roll keys:
    attack_rolls         attacks the creature makes
    attacks_against      attacks made against the creature
    saving_throws        all of the creature's saving throws
    saving_throws:<ab>   saving throws for one ability ('str', 'dex', 'con', ...)

Callers can also pass advantage/disadvantage explicitly for situational sources
(e.g. an attacker that is hidden) that aren't modelled as buffs.

Per 5e rules, multiple sources of advantage don't stack, and any advantage plus any
disadvantage cancel out to a single straight roll.
"""
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List

from models.buffs import BuffManager, is_paralyzed

ATTACK_ROLLS = 'attack_rolls'
ATTACKS_AGAINST = 'attacks_against'
SAVING_THROWS = 'saving_throws'


@dataclass
class D20Roll:
    """Outcome of a d20 roll. `result` is the die that counts; `rolls` are all dice rolled."""
    result: int
    rolls: List[int] = field(default_factory=list)
    advantage: bool = False
    disadvantage: bool = False


def roll_d20(advantage: bool = False, disadvantage: bool = False) -> D20Roll:
    """Roll a d20, rolling twice and keeping the higher/lower die on advantage/disadvantage."""
    if advantage and disadvantage:
        advantage = disadvantage = False
    first = random.randint(1, 20)
    if not (advantage or disadvantage):
        return D20Roll(first, [first])
    rolls = [first, random.randint(1, 20)]
    return D20Roll(max(rolls) if advantage else min(rolls), rolls, advantage, disadvantage)


def _buffs(creature: Any):
    buffs = getattr(creature, 'buffs', None)
    # isinstance guards against test doubles whose auto-created attributes are truthy
    return buffs if isinstance(buffs, BuffManager) else None


def has_advantage(creature: Any, *roll_keys: str) -> bool:
    """True if any active effect on the creature grants advantage on one of the roll keys."""
    buffs = _buffs(creature)
    return bool(buffs) and any(buffs.grants('advantage', key) for key in roll_keys)


def has_disadvantage(creature: Any, *roll_keys: str) -> bool:
    """True if any active effect on the creature imposes disadvantage on one of the roll keys."""
    buffs = _buffs(creature)
    return bool(buffs) and any(buffs.grants('disadvantage', key) for key in roll_keys)


def attack_roll(attacker: Any, target: Any, advantage: bool = False, disadvantage: bool = False) -> D20Roll:
    """Roll an attack's d20, combining effects on the attacker and the target with any explicit sources."""
    return roll_d20(
        advantage=advantage or has_advantage(attacker, ATTACK_ROLLS) or has_advantage(target, ATTACKS_AGAINST),
        disadvantage=disadvantage or has_disadvantage(attacker, ATTACK_ROLLS) or has_disadvantage(target, ATTACKS_AGAINST),
    )


def roll_saving_throw(creature: Any, save_type: str, save_dc: int,
                      advantage: bool = False, disadvantage: bool = False) -> Dict[str, Any]:
    """
    Roll a saving throw for a creature, including buff bonuses (e.g. Bless) and
    advantage/disadvantage. A paralyzed creature automatically fails STR and DEX saves.
    """
    keys = (SAVING_THROWS, f'{SAVING_THROWS}:{save_type}')
    d20 = roll_d20(
        advantage=advantage or has_advantage(creature, *keys),
        disadvantage=disadvantage or has_disadvantage(creature, *keys),
    )
    save_bonus = creature.saving_throw_bonus(save_type) if hasattr(creature, 'saving_throw_bonus') else 0
    buff_bonus = creature.buffs.calculate_total_bonus('saving_throws') if hasattr(creature, 'buffs') else 0
    total_save = d20.result + save_bonus + buff_bonus
    auto_fail = save_type in ('str', 'dex') and is_paralyzed(creature)
    return {
        'save_roll': d20.result,
        'save_rolls': d20.rolls,
        'advantage': d20.advantage,
        'disadvantage': d20.disadvantage,
        'save_bonus': save_bonus,
        'buff_bonus': buff_bonus,
        'total_save': total_save,
        'save_success': not auto_fail and total_save >= save_dc,
        'auto_fail': auto_fail,
    }
