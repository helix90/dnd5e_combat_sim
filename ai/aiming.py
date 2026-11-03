"""
Aiming area effects on an arena: where to centre a Fireball, which way to point a breath weapon.

aim_area tries the placements that could matter (spheres and cubes around each enemy, cones and
lines from the creature's edge toward each enemy, from where it stands or a square it can move
to) and scores each by the damage it's expected to do to enemies, minus damage to allies, which
count for more. See docs/arena-plan.md.
"""
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from models.actions import AttackAction
from models.arena import COVER_AC_BONUS, Area, Point, Square
from models.battlefield import Battlefield, area_of, area_range

# Hurting an ally is worse than hurting an enemy is good
ALLY_WEIGHT = 2.0
# Small tie-breaker against moving
MOVE_PENALTY_PER_FT = 0.002
# Squares besides its own a creature considers using a cone or line from: those nearest an enemy
CONE_SQUARES = 16
# Turns (in radians) either side of pointing a cone or line straight at an enemy
CONE_TURNS = (0.0, 0.35, -0.35)
# How far around an enemy's squares (in squares) sphere centres are tried
SPHERE_SPREAD = 2
# Spells that do half damage on a successful save (breath weapons always do)
HALF_ON_SAVE_SPELLS = {'Fireball', 'Lightning Bolt'}


@dataclass
class Aim:
    """Where to stand and how to place an area, what it catches and what that's worth."""
    value: float
    square: Square
    origin: Point
    toward: Optional[Point]
    hits: List[Tuple[Any, str]] = field(default_factory=list)  # (creature, cover from the origin)

    def plan_fields(self) -> Dict[str, Any]:
        aim = {'origin': list(self.origin)}
        if self.toward is not None:
            aim['toward'] = [round(v, 3) for v in self.toward]
        return {'aim': aim, 'target': [creature for creature, _ in self.hits]}


class _Effect:
    """The damage and save of an area action or spell, for estimating what it does."""

    def __init__(self, creature: Any, action: Any) -> None:
        spell = getattr(action, 'spell', None)
        if spell is not None:
            self.dice = spell.damage_dice
            self.damage_type = spell.damage_type
            self.save_type = spell.save_type
            self.dc = spell.get_save_dc(creature) if spell.save_type else None
            self.half_on_save = spell.name in HALF_ON_SAVE_SPELLS
        else:
            self.dice = action.damage_dice
            self.damage_type = action.damage_type
            self.save_type = action.save_type
            self.dc = action.save_dc
            self.half_on_save = True
        self.average = _average(self.dice)

    def expected(self, target: Any, cover: str) -> float:
        """Expected damage to one creature, at most its hit points. 1 for an effect without damage."""
        if not self.average:
            return 1.0
        damage = self.average
        if self.save_type and self.dc:
            bonus = target.saving_throw_bonus(self.save_type) if hasattr(target, 'saving_throw_bonus') else 0
            if self.save_type == 'dex':
                bonus += COVER_AC_BONUS.get(cover, 0)
            saves = min(0.95, max(0.05, (21 + bonus - self.dc) / 20))
            damage *= (1 - saves) + (0.5 * saves if self.half_on_save else 0)
        if self.damage_type in getattr(target, 'damage_immunities', []):
            return 0.0
        if self.damage_type in getattr(target, 'damage_resistances', []):
            damage /= 2
        return min(damage, max(getattr(target, 'hp', damage), 0))


def _average(dice: Optional[str]) -> float:
    try:
        num, die, mod = AttackAction.parse_dice(str(dice))
        return num * (die + 1) / 2 + mod
    except (TypeError, ValueError):
        return 0.0


def _center(square: Square) -> Point:
    return (square[0] + 0.5, square[1] + 0.5)


def _turned(origin: Point, toward: Point, angle: float) -> Point:
    if not angle:
        return toward
    dx, dy = toward[0] - origin[0], toward[1] - origin[1]
    cos, sin = math.cos(angle), math.sin(angle)
    return (origin[0] + dx * cos - dy * sin, origin[1] + dx * sin + dy * cos)


def _score(bf: Battlefield, creature: Any, effect: _Effect, hits: List[Tuple[Any, str]]) -> float:
    value = 0.0
    for target, cover in hits:
        damage = effect.expected(target, cover)
        value += -ALLY_WEIGHT * damage if not bf.is_enemy(creature, target) else damage
    return value


def _placed_aims(bf: Battlefield, creature: Any, area: Area, enemies: List[Any]) -> List[Point]:
    """Sphere centres or cube corners worth trying: around each enemy's squares."""
    points = set()
    for enemy in enemies:
        for x, y in bf.placements[enemy].squares():
            if area.shape == 'cube':
                n = area.size // 5
                points |= {(float(x - i), float(y - j)) for i in range(n) for j in range(n)}
            else:
                points |= {(float(x + i), float(y + j)) for i in range(-SPHERE_SPREAD, SPHERE_SPREAD + 2)
                           for j in range(-SPHERE_SPREAD, SPHERE_SPREAD + 2)}
    return sorted(points)


def aim_area(bf: Battlefield, creature: Any, action: Any, squares: Dict[Square, int],
             penalty: Optional[Callable[[Square], float]] = None) -> Optional[Aim]:
    """
    The best way to use an area action or spell this turn, standing where the creature is or
    on one of `squares` (reachable squares and their movement cost). `penalty(square)` is taken
    off the value of moving there (e.g. opportunity attacks). None if it can't catch any enemy.
    """
    area = area_of(action)
    if area is None:
        return None
    effect = _Effect(creature, action)
    enemies = bf.enemies_of(creature)
    if not enemies:
        return None
    here = bf.position(creature)
    best: Optional[Aim] = None

    def consider(value: float, square: Square, origin: Point, toward: Optional[Point],
                 hits: List[Tuple[Any, str]]) -> None:
        nonlocal best
        if not any(bf.is_enemy(creature, t) for t, _ in hits):
            return
        value -= MOVE_PENALTY_PER_FT * squares.get(square, 0)
        if penalty is not None and square != here:
            value -= penalty(square)
        if best is None or value > best.value:
            best = Aim(value, square, origin, toward, hits)

    if area.from_self:
        # From here, or from the squares nearest an enemy
        def nearest_enemy(square: Square) -> float:
            placement = bf.placement(creature, square)
            return min(bf.arena.distance(placement, bf.placements[e]) for e in enemies)
        options = sorted((s for s in squares if s != here), key=lambda s: (nearest_enemy(s), squares[s], s))
        for square in [here] + options[:CONE_SQUARES]:
            if nearest_enemy(square) > area.size:
                continue
            edges = bf.arena.edge_points(bf.placement(creature, square))
            for enemy in enemies:
                if bf.arena.distance(bf.placement(creature, square), bf.placements[enemy]) > area.size:
                    continue
                target = _center(min(bf.placements[enemy].squares()))
                origin = min(edges, key=lambda p: (math.dist(p, target), p))
                for angle in CONE_TURNS:
                    toward = _turned(origin, target, angle)
                    hits = bf.area_hits(creature, area, origin, toward, at=square)
                    consider(_score(bf, creature, effect, hits), square, origin, toward, hits)
        return best

    # Spheres and cubes: score each placement from where the creature stands (its own position
    # only matters if it's caught), then find the cheapest square it can be placed from
    range_feet = area_range(action)
    scored = []
    for origin in _placed_aims(bf, creature, area, enemies):
        hits = bf.area_hits(creature, area, origin)
        if any(bf.is_enemy(creature, t) for t, _ in hits):
            scored.append((_score(bf, creature, effect, hits), origin, hits))
    scored.sort(key=lambda item: (-item[0], item[1]))
    for value, origin, hits in scored:
        if best is not None and best.value >= value:
            break  # in order of value, so nothing from here on can do better
        if bf.can_aim(creature, area, range_feet, origin):
            consider(value, here, origin, None, hits)
        else:
            within = [s for s in squares if bf.can_aim(creature, area, range_feet, origin, at=s)]
            if within:
                square = min(within, key=lambda s: (squares[s], s))
                hits = bf.area_hits(creature, area, origin, at=square)
                consider(_score(bf, creature, effect, hits), square, origin, None, hits)
    return best
