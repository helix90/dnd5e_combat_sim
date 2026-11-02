"""
Arena geometry: a 5-ft square grid with terrain, creature footprints, distance, movement,
cover and area-of-effect templates.

This module only does geometry. The combat rules that use it (reach, range, cover bonuses,
who an area effect hits) live in Combat. See docs/arena-plan.md.

Coordinates: squares are (x, y) with (0, 0) at the top left. A creature's position is the
top-left square of its footprint. Points used for cover lines and area templates are grid
intersections in square units, so square (x, y) spans (x, y) to (x + 1, y + 1).
"""
import heapq
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

SQUARE_FEET = 5

Square = Tuple[int, int]
Point = Tuple[float, float]

SIZE_SQUARES = {'tiny': 1, 'small': 1, 'medium': 1, 'large': 2, 'huge': 3, 'gargantuan': 4}

# Diagonal movement rules: every diagonal costs 5 ft (PHB), or alternating 5/10/5 ft (DMG variant)
DIAGONALS_FIVE = '5'
DIAGONALS_ALTERNATING = '5/10/5'

COVER_NONE = 'none'
COVER_HALF = 'half'
COVER_THREE_QUARTERS = 'three_quarters'
COVER_TOTAL = 'total'
COVER_LEVELS = [COVER_NONE, COVER_HALF, COVER_THREE_QUARTERS, COVER_TOTAL]
COVER_AC_BONUS = {COVER_NONE: 0, COVER_HALF: 2, COVER_THREE_QUARTERS: 5}

_EPS = 1e-9
_STEPS = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


def size_in_squares(size: Optional[str]) -> int:
    """Squares per side a creature of this size occupies (Medium if no size is given)."""
    if size is None:
        return 1
    try:
        return SIZE_SQUARES[str(size).lower()]
    except KeyError:
        raise ValueError(f"Unknown creature size: {size!r}")


DEFAULT_SPEED = 30
SPEED_MODES = ('walk', 'fly', 'climb', 'swim', 'burrow')


def normalize_speed(speed: Any) -> Dict[str, Any]:
    """
    Speeds in feet by movement mode, e.g. {'walk': 30, 'fly': 60, 'hover': True}. A plain number
    is a walking speed; no speed means the default 30 ft.
    """
    if speed is None:
        return {'walk': DEFAULT_SPEED}
    if isinstance(speed, (int, float)) and not isinstance(speed, bool):
        speed = {'walk': speed}
    if not isinstance(speed, dict):
        raise ValueError(f"Invalid speed: {speed!r}")
    normalized: Dict[str, Any] = {}
    for mode, value in speed.items():
        if mode == 'hover':
            normalized['hover'] = bool(value)
        elif mode in SPEED_MODES and isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            normalized[mode] = int(value)
        else:
            raise ValueError(f"Invalid speed entry {mode!r}: {value!r}")
    normalized.setdefault('walk', 0)
    return normalized


def _cover_rank(level: str) -> int:
    return COVER_LEVELS.index(level)


@dataclass(frozen=True)
class Terrain:
    """What a square contains. Squares not listed in an arena are open ground."""
    difficult: bool = False
    impassable: bool = False
    cover: str = COVER_NONE  # cover the square gives to creatures behind it

    def __post_init__(self) -> None:
        if self.cover not in COVER_LEVELS:
            raise ValueError(f"Unknown cover level: {self.cover!r}")


OPEN = Terrain()


@dataclass(frozen=True)
class Placement:
    """Where a creature is: its top-left square and how many squares wide it is."""
    position: Square
    size: int = 1

    def squares(self) -> Set[Square]:
        x, y = self.position
        return {(x + dx, y + dy) for dx in range(self.size) for dy in range(self.size)}

    def moved_to(self, position: Square) -> 'Placement':
        return Placement(position, self.size)

    def corners(self) -> Set[Point]:
        """Every grid intersection on a square of the footprint."""
        return {(x + cx, y + cy) for x, y in self.squares() for cx in (0, 1) for cy in (0, 1)}


def _square_corners(square: Square) -> List[Point]:
    x, y = square
    return [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]


def _crosses_interior(p: Point, q: Point, square: Square) -> bool:
    """
    True if the segment p-q passes through the inside of the square. Running along an edge or
    touching a corner doesn't count, so a line that grazes an obstacle isn't blocked by it.
    """
    t0, t1 = 0.0, 1.0
    for start, delta, low in ((p[0], q[0] - p[0], square[0]), (p[1], q[1] - p[1], square[1])):
        high = low + 1
        if abs(delta) < _EPS:
            if start <= low + _EPS or start >= high - _EPS:
                return False
            continue
        ta, tb = (low - start) / delta, (high - start) / delta
        t0, t1 = max(t0, min(ta, tb)), min(t1, max(ta, tb))
        if t1 - t0 <= _EPS:
            return False
    return t1 - t0 > _EPS


def _seam_blocker(p: Point, q: Point, blockers: Dict[Square, str]) -> Optional[str]:
    """
    A line that runs exactly along the edge between two obstacle squares is inside the obstacle,
    not grazing it (otherwise a solid wall would leak along every grid line). Returns the cover
    level of the weaker of the two squares on the strongest such edge, or None.
    """
    strongest = None
    vertical = abs(p[0] - q[0]) < _EPS and abs(p[0] - round(p[0])) < _EPS
    horizontal = abs(p[1] - q[1]) < _EPS and abs(p[1] - round(p[1])) < _EPS
    if not (vertical or horizontal):
        return None
    fixed = round(p[0] if vertical else p[1])
    low, high = sorted((p[1], q[1]) if vertical else (p[0], q[0]))
    for along in range(int(low // 1), int(-(-high // 1))):
        if min(high, along + 1) - max(low, along) <= _EPS:
            continue
        pair = ((fixed - 1, along), (fixed, along)) if vertical else ((along, fixed - 1), (along, fixed))
        if pair[0] in blockers and pair[1] in blockers:
            level = min(blockers[pair[0]], blockers[pair[1]], key=_cover_rank)
            if strongest is None or _cover_rank(level) > _cover_rank(strongest):
                strongest = level
    return strongest


class Arena:
    """A battle map: a grid of squares with terrain and start zones for each side."""

    def __init__(self, width: int, height: int, terrain: Optional[Dict[Square, Terrain]] = None,
                 start_zones: Optional[Dict[str, List[Square]]] = None,
                 diagonals: str = DIAGONALS_FIVE, name: str = '') -> None:
        if width < 1 or height < 1:
            raise ValueError("Arena width and height must be at least 1 square")
        if diagonals not in (DIAGONALS_FIVE, DIAGONALS_ALTERNATING):
            raise ValueError(f"Unknown diagonal rule: {diagonals!r}")
        self.name = name
        self.width = width
        self.height = height
        self.diagonals = diagonals
        self.terrain = dict(terrain or {})
        self._cover_squares = [s for s, kind in self.terrain.items() if kind.cover != COVER_NONE]
        self.start_zones = {side: list(squares) for side, squares in (start_zones or {}).items()}
        for square in list(self.terrain) + [s for zone in self.start_zones.values() for s in zone]:
            if not self.in_bounds(square):
                raise ValueError(f"Square {square} is outside the {width}x{height} arena")

    # Loading

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Arena':
        """
        Build an arena from its JSON description:

            {"name": "Bridge", "width": 20, "height": 12, "diagonals": "5",
             "terrain": [{"rect": [0, 0, 19, 3], "impassable": true, "cover": "total"},
                         {"squares": [[9, 6]], "cover": "half"}],
             "start_zones": {"party": {"rect": [0, 4, 2, 7]}, "monsters": {"squares": [[17, 5]]}}}

        A "rect" is [x1, y1, x2, y2] with both corners included; "rects" is a list of them.
        """
        terrain = {}
        for entry in data.get('terrain', []):
            kind = Terrain(difficult=bool(entry.get('difficult', False)),
                           impassable=bool(entry.get('impassable', False)),
                           cover=entry.get('cover', COVER_NONE))
            for square in cls._squares_from(entry):
                terrain[square] = kind
        zones = {side: cls._squares_from(zone) for side, zone in data.get('start_zones', {}).items()}
        return cls(data['width'], data['height'], terrain, zones,
                   data.get('diagonals', DIAGONALS_FIVE), data.get('name', ''))

    @staticmethod
    def _squares_from(entry: Dict[str, Any]) -> List[Square]:
        squares = [tuple(s) for s in entry.get('squares', [])]
        rects = entry.get('rects', []) + ([entry['rect']] if 'rect' in entry else [])
        for x1, y1, x2, y2 in rects:
            squares += [(x, y) for y in range(min(y1, y2), max(y1, y2) + 1)
                        for x in range(min(x1, x2), max(x1, x2) + 1)]
        return list(dict.fromkeys(squares))

    # Squares

    def in_bounds(self, square: Square) -> bool:
        return 0 <= square[0] < self.width and 0 <= square[1] < self.height

    def terrain_at(self, square: Square) -> Terrain:
        return self.terrain.get(square, OPEN)

    def fits(self, placement: Placement) -> bool:
        """True if every square of the footprint is on the map and passable."""
        return all(self.in_bounds(s) and not self.terrain_at(s).impassable for s in placement.squares())

    # Distance

    def _feet(self, dx: float, dy: float) -> float:
        """Grid distance in feet for a move of dx, dy squares under the arena's diagonal rule."""
        dx, dy = abs(dx), abs(dy)
        diagonal, straight = min(dx, dy), abs(dx - dy)
        if self.diagonals == DIAGONALS_ALTERNATING:
            return SQUARE_FEET * (straight + diagonal + diagonal // 2)
        return SQUARE_FEET * (straight + diagonal)

    def distance(self, a: Placement, b: Placement) -> int:
        """
        Feet between the nearest squares of two footprints. Adjacent creatures are 5 ft apart,
        so a melee attack with 5-ft reach works at distance 5.
        """
        return self.distance_at(a.position, a.size, b)

    def distance_at(self, position: Square, size: int, b: Placement) -> int:
        """distance() for a creature of this size at this position, without building a Placement."""
        ax, ay = position
        bx, by = b.position
        dx = max(0, bx - (ax + size - 1), ax - (bx + b.size - 1))
        dy = max(0, by - (ay + size - 1), ay - (by + b.size - 1))
        if self.diagonals == DIAGONALS_FIVE:
            return SQUARE_FEET * max(dx, dy)
        return int(self._feet(dx, dy))

    # Movement

    def _search(self, mover: Placement, budget: Optional[float], enemies: Iterable[Placement],
                goal: Optional[Callable[[Square], bool]] = None
                ) -> Tuple[Dict[Square, float], Dict[Any, Any], Dict[Square, Any], Optional[Square]]:
        """
        Cheapest movement cost to every position the mover can pass through, or until the
        cheapest position for which goal(position) is true (returned last, else None). A state
        includes whether the next diagonal is a 10-ft one, since the 5/10/5 rule depends on the
        count so far.
        """
        size = mover.size
        offsets = [(dx, dy) for dx in range(size) for dy in range(size)]
        blocked = {s for s, kind in self.terrain.items() if kind.impassable}
        for enemy in enemies:
            blocked |= enemy.squares()
        difficult = {s for s, kind in self.terrain.items() if kind.difficult}
        # Top-left positions where the whole footprint is on the map and not blocked
        open_positions = {(x, y) for x in range(self.width - size + 1) for y in range(self.height - size + 1)}
        for bx, by in blocked:
            for dx, dy in offsets:
                open_positions.discard((bx - dx, by - dy))

        def enters_difficult(here: Square, there: Square) -> bool:
            return any((there[0] + dx, there[1] + dy) in difficult
                       and not (0 <= there[0] + dx - here[0] < size and 0 <= there[1] + dy - here[1] < size)
                       for dx, dy in offsets)

        alternating = self.diagonals == DIAGONALS_ALTERNATING
        start = (mover.position, False)
        costs = {start: 0.0}
        previous: Dict[Any, Any] = {start: None}
        best: Dict[Square, Any] = {mover.position: start}
        queue = [(0.0, mover.position, False)]
        reached = None
        while queue:
            cost, position, odd = heapq.heappop(queue)
            if cost > costs.get((position, odd), float('inf')):
                continue
            if goal is not None and goal(position):
                reached = position
                best[position] = (position, odd)
                break
            px, py = position
            for dx, dy in _STEPS:
                nxt = (px + dx, py + dy)
                if nxt not in open_positions:
                    continue
                diagonal = dx != 0 and dy != 0
                # No squeezing between two blocked squares diagonally
                if diagonal and (px + dx, py) not in open_positions and (px, py + dy) not in open_positions:
                    continue
                step = SQUARE_FEET
                next_odd = odd
                if diagonal and alternating:
                    step = 2 * SQUARE_FEET if odd else SQUARE_FEET
                    next_odd = not odd
                if difficult and enters_difficult(position, nxt):
                    step *= 2
                new_cost = cost + step
                if budget is not None and new_cost > budget:
                    continue
                state = (nxt, next_odd)
                if new_cost < costs.get(state, float('inf')):
                    costs[state] = new_cost
                    previous[state] = (position, odd)
                    heapq.heappush(queue, (new_cost, nxt, next_odd))
                    if nxt not in best or new_cost < costs[best[nxt]]:
                        best[nxt] = state
        return {square: costs[state] for square, state in best.items()}, previous, best, reached

    def _can_end_at(self, placement: Placement, occupied: Iterable[Placement]) -> bool:
        return not any(placement.squares() & other.squares() for other in occupied)

    def reachable_squares(self, mover: Placement, movement_ft: float,
                          allies: Iterable[Placement] = (),
                          enemies: Iterable[Placement] = ()) -> Dict[Square, int]:
        """
        Positions the mover can end its move in, with the movement each one costs. Movement can
        pass through allies but not enemies, can't end in an occupied square, and difficult
        terrain costs double. The starting position is included at cost 0.
        """
        allies, enemies = list(allies), list(enemies)
        costs, _, _, _ = self._search(mover, movement_ft, enemies)
        occupied = set().union(*(other.squares() for other in allies + enemies))
        return {square: int(cost) for square, cost in costs.items()
                if square == mover.position or not (mover.moved_to(square).squares() & occupied)}

    def path_to(self, mover: Placement, destination: Square, allies: Iterable[Placement] = (),
                enemies: Iterable[Placement] = ()) -> Optional[List[Square]]:
        """
        The cheapest route to a destination as a list of positions, starting with the current
        one, or None if the mover can't get there or can't end its move there.
        """
        allies, enemies = list(allies), list(enemies)
        if destination != mover.position and not self._can_end_at(mover.moved_to(destination),
                                                                  allies + enemies):
            return None
        return self.path_to_nearest(mover, lambda position: position == destination, allies, enemies)

    def path_to_nearest(self, mover: Placement, goal: Callable[[Square], bool],
                        allies: Iterable[Placement] = (),
                        enemies: Iterable[Placement] = ()) -> Optional[List[Square]]:
        """
        The cheapest route to the nearest position for which goal(position) is true and where the
        mover can end its move, or None if there isn't one.
        """
        allies, enemies = list(allies), list(enemies)
        occupied = set().union(*(other.squares() for other in allies + enemies))

        def reachable_goal(position: Square) -> bool:
            return goal(position) and (position == mover.position
                                       or not (mover.moved_to(position).squares() & occupied))
        _, previous, best, reached = self._search(mover, None, enemies, goal=reachable_goal)
        if reached is None:
            return None
        path, state = [], best[reached]
        while state is not None:
            path.append(state[0])
            state = previous[state]
        return path[::-1]

    def path_cost(self, mover: Placement, path: List[Square]) -> int:
        """Movement in feet a path costs, following the same rules as reachable_squares."""
        cost, odd = 0, False
        for here, there in zip(path, path[1:]):
            dx, dy = there[0] - here[0], there[1] - here[1]
            if max(abs(dx), abs(dy)) != 1:
                raise ValueError(f"Path step {here} -> {there} is not between neighbouring squares")
            step = SQUARE_FEET
            if dx and dy and self.diagonals == DIAGONALS_ALTERNATING:
                step = 2 * SQUARE_FEET if odd else SQUARE_FEET
                odd = not odd
            entered = mover.moved_to(there).squares() - mover.moved_to(here).squares()
            if any(self.terrain_at(s).difficult for s in entered):
                step *= 2
            cost += step
        return cost

    # Cover

    def cover(self, attacker: Placement, target: Placement, others: Iterable[Placement] = ()) -> str:
        """
        Cover the target has against the attacker, using the DMG grid method. From a corner of the
        attacker's space, trace lines to the four corners of one square of the target. One or two
        blocked lines give half cover, three or four give three-quarters, and if every line is
        blocked by total-cover terrain the target has total cover. The attacker gets the best
        corner and target square.

        Blockers are terrain with cover and the other creatures in `others`, which give at most
        half cover. A line blocked only by low obstacles gives no more cover than they do, so
        a row of half-cover walls never gives three-quarters cover.
        """
        own = attacker.squares() | target.squares()
        # Every line stays inside the box around both creatures, so only blockers there matter
        # (plus one square around it, for lines running along the box's edge between two blockers)
        x1 = min(attacker.position[0], target.position[0]) - 1
        y1 = min(attacker.position[1], target.position[1]) - 1
        x2 = max(attacker.position[0] + attacker.size, target.position[0] + target.size)
        y2 = max(attacker.position[1] + attacker.size, target.position[1] + target.size)

        def inside(square: Square) -> bool:
            return x1 <= square[0] <= x2 and y1 <= square[1] <= y2 and square not in own
        blockers: Dict[Square, str] = {}
        if self._cover_squares:
            for square in self._cover_squares:
                if inside(square):
                    blockers[square] = self.terrain[square].cover
        for creature in others:
            for square in creature.squares():
                if inside(square) and _cover_rank(blockers.get(square, COVER_NONE)) < _cover_rank(COVER_HALF):
                    blockers[square] = COVER_HALF
        if not blockers:
            return COVER_NONE

        best = COVER_TOTAL
        for corner in attacker.corners():
            for target_square in target.squares():
                result = self._cover_from(corner, target_square, blockers)
                if _cover_rank(result) < _cover_rank(best):
                    best = result
                    if best == COVER_NONE:
                        return best
        return best

    def _cover_from(self, corner: Point, target_square: Square, blockers: Dict[Square, str]) -> str:
        lines = []
        for end in _square_corners(target_square):
            strongest = _seam_blocker(corner, end, blockers)
            ax, bx = sorted((corner[0], end[0]))
            ay, by = sorted((corner[1], end[1]))
            for square, level in blockers.items():
                # A square can only be crossed if it overlaps the line's span (cheap check first)
                if square[0] >= bx or square[0] + 1 <= ax or square[1] >= by or square[1] + 1 <= ay:
                    if not (ax == bx or ay == by):
                        continue
                if (strongest is None or _cover_rank(level) > _cover_rank(strongest)) \
                        and _crosses_interior(corner, end, square):
                    strongest = level
            lines.append(strongest)
        blocked = [level for level in lines if level is not None]
        if not blocked:
            return COVER_NONE
        if len(blocked) == 4 and all(level == COVER_TOTAL for level in blocked):
            return COVER_TOTAL
        level = COVER_HALF if len(blocked) <= 2 else COVER_THREE_QUARTERS
        cap = max((min(_cover_rank(b), _cover_rank(COVER_THREE_QUARTERS)) for b in blocked))
        return COVER_LEVELS[min(_cover_rank(level), cap)]

    # Areas of effect. A square is in the area if its center is.

    def _all_squares(self) -> Iterable[Square]:
        return ((x, y) for y in range(self.height) for x in range(self.width))

    def squares_in_sphere(self, center: Point, radius_ft: float) -> Set[Square]:
        """A sphere or circle (e.g. Fireball) centred on a grid intersection."""
        return {s for s in self._all_squares()
                if self._feet(s[0] + 0.5 - center[0], s[1] + 0.5 - center[1]) <= radius_ft + _EPS}

    def squares_in_cube(self, corner: Square, side_ft: float) -> Set[Square]:
        """An axis-aligned cube (e.g. Web) whose top-left square is `corner`."""
        n = int(side_ft // SQUARE_FEET)
        return {(corner[0] + dx, corner[1] + dy) for dx in range(n) for dy in range(n)
                if self.in_bounds((corner[0] + dx, corner[1] + dy))}

    def _along_and_across(self, origin: Point, toward: Point) -> Optional[Any]:
        vx, vy = toward[0] - origin[0], toward[1] - origin[1]
        length = (vx * vx + vy * vy) ** 0.5
        if length < _EPS:
            return None
        ux, uy = vx / length, vy / length

        def measure(square: Square) -> Tuple[float, float]:
            px, py = square[0] + 0.5 - origin[0], square[1] + 0.5 - origin[1]
            return (px * ux + py * uy) * SQUARE_FEET, abs(px * uy - py * ux) * SQUARE_FEET
        return measure

    def squares_in_cone(self, origin: Point, toward: Point, length_ft: float) -> Set[Square]:
        """A cone (e.g. a breath weapon) from a point, aimed at another point. Its width at any
        distance from the origin equals that distance."""
        measure = self._along_and_across(origin, toward)
        if measure is None:
            return set()
        squares = set()
        for s in self._all_squares():
            along, across = measure(s)
            if _EPS < along <= length_ft + _EPS and across <= along / 2 + _EPS:
                squares.add(s)
        return squares

    def squares_in_line(self, origin: Point, toward: Point, length_ft: float,
                        width_ft: float = SQUARE_FEET) -> Set[Square]:
        """A line (e.g. Lightning Bolt) from a point, aimed at another point."""
        measure = self._along_and_across(origin, toward)
        if measure is None:
            return set()
        squares = set()
        for s in self._all_squares():
            along, across = measure(s)
            if _EPS < along <= length_ft + _EPS and across <= width_ft / 2 + _EPS:
                squares.add(s)
        return squares

    @staticmethod
    def creatures_in(squares: Set[Square], placements: Dict[Any, Placement]) -> List[Any]:
        """The creatures with at least one square of their footprint in the area."""
        return [creature for creature, placement in placements.items() if placement.squares() & squares]
