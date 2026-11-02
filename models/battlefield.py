"""
A fight on an arena: where each creature stands, and the combat rules that depend on it.

Arena (models/arena.py) is pure geometry. Battlefield adds the creatures: it places them in
their side's start zone, moves them, and decides whether an attack or spell can reach its
target and whether distance gives disadvantage. Combat uses it to enforce the rules and the AI
uses it to plan moves (see ai/positioning.py). See docs/arena-plan.md.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from models.actions import AttackAction
from models.arena import (COVER_AC_BONUS, COVER_NONE, COVER_TOTAL, SQUARE_FEET, Arena, Placement, Square,
                          size_in_squares)
from models.buffs import is_paralyzed

PARTY = 'party'
MONSTERS = 'monsters'

# Classes that fight from the back line, so they're placed behind the front-liners
BACK_LINE_CLASSES = {'Wizard', 'Sorcerer', 'Warlock', 'Druid', 'Bard', 'Ranger'}
BACK_LINE_RANKS = 2


@dataclass
class Situation:
    """Whether an attack or spell can reach its target, and what distance does to the roll."""
    in_range: bool
    distance: int
    melee: bool = False
    disadvantage_reasons: List[str] = field(default_factory=list)
    cover: str = COVER_NONE

    @property
    def disadvantage(self) -> bool:
        return bool(self.disadvantage_reasons)

    @property
    def ac_bonus(self) -> int:
        """What the target's cover adds to its AC (and to DEX saves)."""
        return COVER_AC_BONUS.get(self.cover, 0)


# Spells whose target gains no benefit from cover (our spell text is shortened, so list them)
SPELLS_IGNORING_COVER = {'Sacred Flame'}


def ignores_cover(spell: Any) -> bool:
    """Spells like Sacred Flame say the target gains no benefit from cover."""
    return (getattr(spell, 'name', None) in SPELLS_IGNORING_COVER
            or 'no benefit from cover' in (getattr(spell, 'description', '') or '').lower())


def movement_speed(creature: Any) -> int:
    """
    Feet the creature can move in a turn. Flying is treated like walking (no elevation), so a
    creature uses its better speed.
    """
    speed = getattr(creature, 'speed', None) or {'walk': 30}
    return max(speed.get('walk', 0), speed.get('fly', 0))


def attack_distances(action: Any) -> Tuple[Optional[int], Optional[Tuple[int, int]]]:
    """(reach, (normal, long) range) of an attack. Plain actions without data reach 5 ft."""
    if isinstance(action, AttackAction):
        return action.reach, action.range
    return SQUARE_FEET, None


Threatened = Callable[[], bool]


def _ranged(distance: int, normal: int, long: int, threatened: Threatened) -> Situation:
    if distance > long:
        return Situation(False, distance)
    reasons = []
    if distance > normal:
        reasons.append('long range')
    if threatened():
        reasons.append('enemy within 5 ft')
    return Situation(True, distance, disadvantage_reasons=reasons)


def judge_attack(action: Any, distance: int, threatened: Threatened) -> Situation:
    """
    Can an attack reach a target this far away? Within reach it's a melee attack. Otherwise a
    ranged or thrown attack works out to long range, with disadvantage beyond normal range or
    when `threatened()` (a non-incapacitated enemy within 5 ft of the attacker). Area effects
    aren't limited here yet (phase 4).
    """
    if getattr(action, 'area_effect', False):
        return Situation(True, distance)
    reach, attack_range = attack_distances(action)
    if reach is not None and distance <= reach:
        return Situation(True, distance, melee=True)
    if attack_range is not None:
        return _ranged(distance, attack_range[0], attack_range[1], threatened)
    if reach is None:
        # A ranged attack with no range in its data: don't limit it
        return Situation(True, distance)
    return Situation(False, distance)


def judge_spell(spell: Any, distance: int, threatened: Threatened) -> Situation:
    """
    Can a spell target a creature this far away? It must be within the spell's range (Touch is
    5 ft, Self only the caster). A ranged spell attack has disadvantage when threatened.
    """
    range_feet = getattr(spell, 'range_feet', None)
    if range_feet is None or getattr(spell, 'area_effect', False):
        return Situation(True, distance)
    if distance > range_feet:
        return Situation(False, distance)
    if getattr(spell, 'is_attack_spell', False) and range_feet > SQUARE_FEET:
        return _ranged(distance, range_feet, range_feet, threatened)
    return Situation(True, distance, melee=range_feet <= SQUARE_FEET)


class Battlefield:
    """Creatures on an arena. `present` says whether a creature is still on the map."""

    def __init__(self, arena: Arena, sides: Dict[Any, str],
                 present: Optional[Callable[[Any], bool]] = None) -> None:
        self.arena = arena
        self.sides = dict(sides)
        self.present = present or (lambda creature: creature.is_alive())
        self.placements: Dict[Any, Placement] = {}

    # Setting up

    @staticmethod
    def _fights_from_range(creature: Any) -> bool:
        if getattr(creature, 'character_class', None) in BACK_LINE_CLASSES:
            return True
        attacks = [a for a in getattr(creature, 'actions', []) if isinstance(a, AttackAction)]
        return bool(attacks) and attacks[0].reach is None and attacks[0].range is not None

    def _zone(self, side: str) -> List[Square]:
        """The side's start zone, or the left (party) or right (monsters) quarter of the map."""
        zone = self.arena.start_zones.get(side)
        if zone:
            return list(zone)
        quarter = max(1, self.arena.width // 4)
        columns = range(quarter) if side == PARTY else range(self.arena.width - quarter, self.arena.width)
        return [(x, y) for x in columns for y in range(self.arena.height)]

    def place_all(self) -> None:
        """
        Put every creature in its side's start zone: front-liners in the squares nearest the
        other side, back-liners behind them, larger creatures first within each group.
        """
        self.placements = {}
        zones = {side: self._zone(side) for side in set(self.sides.values())}
        for side, zone in zones.items():
            others = [s for other, z in zones.items() if other != side for s in z] or zone
            cx = sum(s[0] for s in others) / len(others)
            cy = sum(s[1] for s in others) / len(others)
            # Front squares first; within a rank, start from the middle of the line
            zone_cx = sum(s[0] for s in zone) / len(zone)
            zone_cy = sum(s[1] for s in zone) / len(zone)
            def rank(s: Square) -> int:
                return round(((s[0] - cx) ** 2 + (s[1] - cy) ** 2) ** 0.5)
            front = min(rank(s) for s in zone)

            def spread(s: Square) -> float:
                return abs(s[0] - zone_cx) + abs(s[1] - zone_cy)
            front_first = sorted(zone, key=lambda s: (rank(s), spread(s), s))
            # Back-liners start two ranks (10 ft) behind the front line, or as close to that as fits
            back_line = sorted(zone, key=lambda s: (abs(rank(s) - front - BACK_LINE_RANKS), spread(s), s))
            creatures = [c for c, s in self.sides.items() if s == side]
            creatures.sort(key=lambda c: (self._fights_from_range(c), -size_in_squares(getattr(c, 'size', None))))
            for creature in creatures:
                ordered = back_line if self._fights_from_range(creature) else front_first
                self.placements[creature] = self._free_placement(creature, ordered)

    def _free_placement(self, creature: Any, ordered: List[Square]) -> Placement:
        size = size_in_squares(getattr(creature, 'size', None))
        taken = set().union(*(p.squares() for p in self.placements.values())) if self.placements else set()

        def free(square: Square) -> bool:
            placement = Placement(square, size)
            return self.arena.fits(placement) and not (placement.squares() & taken)
        for square in ordered:
            if free(square):
                return Placement(square, size)
        # The zone is full: the nearest free square outside it
        anchor = ordered[0] if ordered else (0, 0)
        outside = sorted(((x, y) for x in range(self.arena.width) for y in range(self.arena.height)),
                         key=lambda s: (abs(s[0] - anchor[0]) + abs(s[1] - anchor[1]), s))
        for square in outside:
            if free(square):
                return Placement(square, size)
        raise ValueError(f"No room on the {self.arena.name or 'arena'} map for {getattr(creature, 'name', creature)}")

    # Who is where

    def placement(self, creature: Any, at: Optional[Square] = None) -> Placement:
        placement = self.placements[creature]
        return placement if at is None else placement.moved_to(at)

    def position(self, creature: Any) -> Square:
        return self.placements[creature].position

    def is_enemy(self, a: Any, b: Any) -> bool:
        return self.sides.get(a) != self.sides.get(b)

    def creatures(self) -> List[Any]:
        return [c for c in self.placements if self.present(c)]

    def allies_of(self, creature: Any) -> List[Any]:
        return [c for c in self.creatures() if c is not creature and not self.is_enemy(c, creature)]

    def enemies_of(self, creature: Any) -> List[Any]:
        return [c for c in self.creatures() if self.is_enemy(c, creature)]

    def distance(self, a: Any, b: Any, at: Optional[Square] = None) -> int:
        """Feet between two creatures, optionally with `a` standing at another square."""
        return self.arena.distance(self.placement(a, at), self.placements[b])

    def snapshot(self) -> Dict[str, List[int]]:
        """Positions by creature name, for the combat log."""
        return {getattr(c, 'name', str(c)): list(p.position) for c, p in self.placements.items()}

    # Movement

    def speed(self, creature: Any) -> int:
        return movement_speed(creature)

    def _others(self, creature: Any) -> Tuple[List[Placement], List[Placement]]:
        allies = [self.placements[c] for c in self.allies_of(creature)]
        enemies = [self.placements[c] for c in self.enemies_of(creature)]
        return allies, enemies

    def reachable(self, creature: Any, movement_ft: float) -> Dict[Square, int]:
        """Squares the creature can end a move on with this much movement, and their cost."""
        allies, enemies = self._others(creature)
        return self.arena.reachable_squares(self.placements[creature], movement_ft, allies, enemies)

    def path(self, creature: Any, destination: Square) -> Optional[List[Square]]:
        allies, enemies = self._others(creature)
        return self.arena.path_to(self.placements[creature], destination, allies, enemies)

    def path_to_nearest(self, creature: Any, goal: Callable[[Square], bool]) -> Optional[List[Square]]:
        """Cheapest route to the nearest square the creature can end on where goal(square) is true."""
        allies, enemies = self._others(creature)
        return self.arena.path_to_nearest(self.placements[creature], goal, allies, enemies)

    def path_cost(self, creature: Any, path: List[Square]) -> int:
        return self.arena.path_cost(self.placements[creature], path)

    def can_end_at(self, creature: Any, square: Square) -> bool:
        placement = self.placement(creature, square)
        if not self.arena.fits(placement):
            return False
        return not any(placement.squares() & self.placements[c].squares()
                       for c in self.creatures() if c is not creature)

    def _clear(self, creature: Any, path: List[Square]) -> bool:
        """True if the path starts where the creature is and never enters an enemy or a wall."""
        if not path or path[0] != self.position(creature):
            return False
        enemy_squares = set().union(*(self.placements[e].squares() for e in self.enemies_of(creature)))
        return all(self.arena.fits(self.placement(creature, step))
                   and not (self.placement(creature, step).squares() & enemy_squares) for step in path)

    def move(self, creature: Any, destination: Square, movement_ft: float,
             path: Optional[List[Square]] = None) -> int:
        """
        Move the creature if it can get there with this much movement, along `path` if one is
        given and clear, or the cheapest route. Returns feet moved.
        """
        if destination == self.position(creature):
            return 0
        if path is not None and (path[-1] != destination or not self._clear(creature, path)
                                 or not self.can_end_at(creature, destination)):
            path = None
        if path is None:
            path = self.path(creature, destination)
        if path is None:
            raise ValueError(f"{getattr(creature, 'name', creature)} can't reach {destination}")
        cost = self.path_cost(creature, path)
        if cost > movement_ft:
            raise ValueError(f"{getattr(creature, 'name', creature)} needs {cost} ft to reach "
                             f"{destination} but has {movement_ft} ft")
        self.placements[creature] = self.placement(creature, destination)
        return cost

    # Rules

    def enemies_within_5ft(self, creature: Any, at: Optional[Square] = None) -> List[Any]:
        """Enemies next to the creature that aren't incapacitated (they make ranged attacks harder)."""
        placement = self.placement(creature, at)
        return [e for e in self.enemies_of(creature)
                if not is_paralyzed(e) and self.arena.distance(placement, self.placements[e]) <= SQUARE_FEET]

    def ally_next_to(self, target: Any, attacker: Any) -> bool:
        """
        True if one of the attacker's allies, other than the attacker, is within 5 ft of the
        target and not incapacitated (Sneak Attack, Pack Tactics).
        """
        return any(not is_paralyzed(a) and self.distance(a, target) <= SQUARE_FEET
                   for a in self.allies_of(attacker))

    def cover(self, attacker: Any, target: Any, at: Optional[Square] = None) -> str:
        """
        Cover the target has against the attacker (standing at `at`, or where it is), from terrain
        and from every other creature on the map.
        """
        if target is attacker:
            return COVER_NONE
        others = [self.placements[c] for c in self.creatures() if c is not attacker and c is not target]
        return self.arena.cover(self.placement(attacker, at), self.placements[target], others)

    def _with_cover(self, situation: Situation, attacker: Any, target: Any, at: Optional[Square]) -> Situation:
        """Add the target's cover; total cover means it can't be targeted at all."""
        if situation.in_range:
            situation.cover = self.cover(attacker, target, at)
            if situation.cover == COVER_TOTAL:
                situation.in_range = False
        return situation

    def attack_situation(self, attacker: Any, target: Any, action: Any,
                         at: Optional[Square] = None) -> Situation:
        """
        Can the attacker hit the target with this attack, from `at` or where it stands, and what
        cover does the target have? See judge_attack. Area effects ignore cover until phase 4.
        """
        situation = judge_attack(action, self.distance(attacker, target, at),
                                 lambda: bool(self.enemies_within_5ft(attacker, at)))
        if getattr(action, 'area_effect', False):
            return situation
        return self._with_cover(situation, attacker, target, at)

    def spell_situation(self, caster: Any, target: Any, spell: Any,
                        at: Optional[Square] = None) -> Situation:
        """Can the caster target this creature with the spell, and what cover does it have? See judge_spell."""
        distance = 0 if target is caster else self.distance(caster, target, at)
        situation = judge_spell(spell, distance, lambda: bool(self.enemies_within_5ft(caster, at)))
        if getattr(spell, 'area_effect', False) or target is caster:
            return situation
        return self._with_cover(situation, caster, target, at)

    def spell_targets_in_range(self, caster: Any, targets: Iterable[Any], spell: Any,
                               at: Optional[Square] = None) -> List[Any]:
        return [t for t in targets if self.spell_situation(caster, t, spell, at).in_range]
