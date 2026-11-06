"""
Work out which attacks a monster's Multiattack makes from its description.

Shared by Combat (which makes the attacks) and the arena AI (which needs to know which
attacks a Multiattack can make from a given distance).
"""

import re
from typing import Any, Callable, List, Optional

_COUNTS = {"one": 1, "two": 2, "three": 3, "four": 4, "1": 1, "2": 2, "3": 3, "4": 4}
_COUNT_WORDS = "|".join(_COUNTS)


def _parse_routine(description: str, attack_actions: List[Any]) -> List[Any]:
    """The attacks one routine makes, e.g. "one with its bite and two with its claws"."""

    def find_action(word: str) -> Optional[Any]:
        singular = word.rstrip("s")
        return next(
            (
                a
                for a in attack_actions
                if word in a.name.lower() or singular in a.name.lower()
            ),
            None,
        )

    attacks = []
    # "one with its bite and two with its claws", "one with its bite and one to constrict"
    for count, word in re.findall(
        rf"\b({_COUNT_WORDS})\s+(?:attacks?\s+)?(?:with\s+(?:its\s+)?|to\s+)(\w+)",
        description,
    ):
        action = find_action(word)
        if action:
            attacks.extend([action] * _COUNTS[count])
    if not attacks:
        # "two greatclub attacks"
        for count, word in re.findall(
            rf"\b({_COUNT_WORDS})\s+(\w+)\s+attacks?\b", description
        ):
            action = find_action(word)
            if action:
                attacks.extend([action] * _COUNTS[count])
    return attacks


def _one_restricted(description: str, attack_actions: List[Any]) -> List[Any]:
    """ "two attacks, only one of which can be a bite attack" -> the first other attack, then the bite."""
    match = re.search(r"only one of which can be an? (\w+) attack", description)
    restricted = (
        _parse_routine(f"one with {match.group(1)}", attack_actions) if match else []
    )
    others = [a for a in attack_actions if a not in restricted]
    if not restricted or not others:
        return []
    return [others[0]] * (_attack_count(description) - 1) + restricted


def for_target(attacks: List[Any], target: Any) -> List[Any]:
    """
    The routine against one target: an attack it can't be used on (a vampire spawn's bite on a
    creature that isn't grappled, incapacitated or restrained) is replaced by the routine's first
    attack that can.
    """

    def usable(a: Any) -> bool:
        return not callable(getattr(a, "usable_on", None)) or a.usable_on(target)

    fallback = next((a for a in attacks if usable(a)), None)
    return [
        a if usable(a) else fallback
        for a in attacks
        if usable(a) or fallback is not None
    ]


def _attack_count(description: str) -> int:
    match = re.search(rf"\b({_COUNT_WORDS})\s+attacks\b", description)
    return _COUNTS[match.group(1)] if match else 2


def parse_multiattack(
    description: str,
    attack_actions: List[Any],
    usable: Optional[Callable[[Any], bool]] = None,
) -> List[Any]:
    """
    The attacks a Multiattack makes, e.g.
      "three attacks: one with its bite and two with its claws" -> Bite, Claw, Claw
      "two greatclub attacks"                                    -> Greatclub, Greatclub
      "two longsword attacks or two longbow attacks"             -> Longsword, Longsword
      "two attacks, only one of which can be a bite attack"      -> Claws, Bite (see for_target)

    Without `usable`, the first routine is used. With it (in an arena), the first routine whose
    attacks can all be used is chosen, so a wight out of sword reach uses its longbows; if no
    routine fits, only the usable attacks of the first one are made.
    """
    description = description.lower()
    routines = description.split(" or ")
    parsed = [
        _parse_routine(routine, attack_actions)
        or _one_restricted(routine, attack_actions)
        for routine in routines
    ]

    if usable is None:
        attacks = parsed[0]
        if not attacks and attack_actions:
            # "makes two attacks" with no breakdown: repeat the primary attack
            attacks = [attack_actions[0]] * _attack_count(routines[0])
        return attacks

    for attacks in parsed:
        if attacks and all(usable(a) for a in attacks):
            return attacks
    if parsed[0]:
        return [a for a in parsed[0] if usable(a)]
    candidates = [a for a in attack_actions if usable(a)]
    return [candidates[0]] * _attack_count(routines[0]) if candidates else []
