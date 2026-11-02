"""Arena geometry: distance, movement, cover and area templates on fixed layouts."""
import pytest

from models.arena import (
    COVER_HALF, COVER_NONE, COVER_THREE_QUARTERS, COVER_TOTAL, DIAGONALS_ALTERNATING,
    Arena, Placement, Terrain, size_in_squares,
)

WALL = Terrain(impassable=True, cover=COVER_TOTAL)
LOW_WALL = Terrain(cover=COVER_HALF)
MUD = Terrain(difficult=True)


def at(x, y, size=1):
    return Placement((x, y), size)


# Sizes and distance

@pytest.mark.parametrize('size, squares', [
    (None, 1), ('Tiny', 1), ('small', 1), ('Medium', 1), ('Large', 2), ('huge', 3), ('Gargantuan', 4)])
def test_size_in_squares(size, squares):
    assert size_in_squares(size) == squares


def test_unknown_size_is_an_error():
    with pytest.raises(ValueError):
        size_in_squares('enormous')


@pytest.mark.parametrize('a, b, feet', [
    (at(0, 0), at(1, 0), 5),     # adjacent
    (at(0, 0), at(1, 1), 5),     # adjacent diagonally
    (at(0, 0), at(6, 0), 30),
    (at(0, 0), at(4, 3), 20),    # diagonals cost 5 ft
    (at(0, 0), at(0, 0), 0),
])
def test_distance_medium(a, b, feet):
    arena = Arena(20, 20)
    assert arena.distance(a, b) == feet == arena.distance(b, a)


def test_distance_uses_nearest_squares_of_large_creatures():
    arena = Arena(20, 20)
    troll = at(2, 2, 2)          # occupies (2..3, 2..3)
    assert arena.distance(troll, at(4, 3)) == 5    # next to its right edge
    assert arena.distance(troll, at(1, 1)) == 5    # next to its top-left corner
    assert arena.distance(troll, at(7, 2)) == 20   # 3 empty squares between x=3 and x=7
    giant = at(10, 10, 3)        # Huge: (10..12, 10..12)
    assert arena.distance(giant, troll) == 35      # nearest squares (3, 3) and (10, 10) are 7 squares apart


def test_alternating_diagonals():
    arena = Arena(20, 20, diagonals=DIAGONALS_ALTERNATING)
    assert arena.distance(at(0, 0), at(1, 1)) == 5
    assert arena.distance(at(0, 0), at(2, 2)) == 15
    assert arena.distance(at(0, 0), at(4, 3)) == 25   # 3 diagonals (5+10+5) + 1 straight


# Movement

def test_open_ground_movement_is_a_square_of_reach():
    arena = Arena(20, 20)
    reachable = arena.reachable_squares(at(10, 10), 30)
    assert set(reachable) == {(x, y) for x in range(4, 17) for y in range(4, 17)}
    assert reachable[(16, 16)] == 30 and reachable[(10, 10)] == 0


def test_movement_goes_around_walls():
    # A wall from (5, 0) to (5, 8) with a gap at y = 9
    arena = Arena(12, 12, {(5, y): WALL for y in range(9)})
    path = arena.path_to(at(4, 0), (6, 0))
    assert path[0] == (4, 0) and path[-1] == (6, 0)
    assert all(arena.terrain_at(s) != WALL for s in path)
    assert arena.path_cost(at(4, 0), path) == 90   # down 9 rows, through the gap, back up 9
    assert (6, 0) not in arena.reachable_squares(at(4, 0), 30)


def test_no_squeezing_diagonally_between_walls():
    arena = Arena(5, 5, {(1, 0): WALL, (0, 1): WALL})
    assert (1, 1) not in arena.reachable_squares(at(0, 0), 30)


def test_difficult_terrain_costs_double():
    arena = Arena(10, 1, {(x, 0): MUD for x in range(1, 4)})
    reachable = arena.reachable_squares(at(0, 0), 30)
    assert reachable[(3, 0)] == 30 and (4, 0) not in reachable


def test_pass_through_allies_but_not_enemies_and_never_end_on_anyone():
    corridor = Arena(10, 1)
    ally, enemy = at(2, 0), at(2, 0)
    through_ally = corridor.reachable_squares(at(0, 0), 30, allies=[ally])
    assert (3, 0) in through_ally and (2, 0) not in through_ally
    blocked = corridor.reachable_squares(at(0, 0), 30, enemies=[enemy])
    assert set(blocked) == {(0, 0), (1, 0)}
    assert corridor.path_to(at(0, 0), (2, 0), allies=[ally]) is None


def test_large_creature_needs_room():
    # A 1-square gap in a wall lets a Medium creature through but not a Large one
    arena = Arena(10, 10, {(5, y): WALL for y in range(10) if y != 4})
    assert arena.path_to(at(2, 4), (8, 4)) is not None
    assert arena.path_to(at(2, 4, 2), (8, 4)) is None


def test_path_cost_rejects_jumps():
    with pytest.raises(ValueError):
        Arena(10, 10).path_cost(at(0, 0), [(0, 0), (2, 0)])


# Cover

def test_no_cover_in_the_open():
    assert Arena(20, 20).cover(at(0, 0), at(10, 3)) == COVER_NONE


def test_wall_between_gives_total_cover():
    arena = Arena(20, 20, {(5, y): WALL for y in range(20)})
    assert arena.cover(at(2, 5), at(8, 5)) == COVER_TOTAL


def test_low_wall_gives_half_cover():
    arena = Arena(20, 20, {(5, y): LOW_WALL for y in range(20)})
    assert arena.cover(at(2, 5), at(8, 5)) == COVER_HALF


def test_corner_of_a_wall_gives_partial_cover():
    # The target is just behind the end of a wall; some lines get past, some don't
    arena = Arena(20, 20, {(5, y): WALL for y in range(6)})
    result = arena.cover(at(2, 5), at(7, 5))
    assert result in (COVER_HALF, COVER_THREE_QUARTERS)
    # Further from the end of the wall, the attacker can see the target clearly
    assert arena.cover(at(2, 9), at(7, 9)) == COVER_NONE


def test_gap_in_a_wall_is_clear_head_on_and_three_quarters_at_an_angle():
    # A solid wall down column 5 with a one-square gap at (5, 5); the target stands just behind it
    arena = Arena(12, 12, {(5, y): WALL for y in range(12) if y != 5})
    target = at(6, 5)
    assert arena.cover(at(0, 5), target) == COVER_NONE              # looking straight through
    assert arena.cover(at(0, 0), target) == COVER_THREE_QUARTERS    # most lines hit the wall
    assert arena.cover(at(0, 0), at(6, 9)) != COVER_NONE
    assert arena.cover(at(0, 9), at(6, 11)) == COVER_TOTAL          # no line gets through


def test_creatures_give_half_cover_at_most():
    arena = Arena(20, 20)
    shield_wall = [at(5, y) for y in range(20)]
    assert arena.cover(at(2, 5), at(8, 5), others=shield_wall) == COVER_HALF
    assert arena.cover(at(2, 5), at(8, 5), others=[at(5, 5)]) == COVER_HALF


def test_attacker_and_target_squares_never_block():
    arena = Arena(20, 20, {(2, 5): LOW_WALL, (8, 5): LOW_WALL})
    assert arena.cover(at(2, 5), at(8, 5)) == COVER_NONE


def test_grazing_an_obstacle_corner_does_not_block():
    # The line from (1,1) to the target's corners runs along the obstacle's edge
    arena = Arena(10, 10, {(1, 0): WALL})
    assert arena.cover(at(0, 0), at(2, 0)) != COVER_NONE  # directly behind it
    assert arena.cover(at(0, 1), at(2, 1)) == COVER_NONE  # one row down, the wall is beside the line


# Areas of effect

def test_fireball_sphere_is_40_ft_across():
    arena = Arena(30, 30)
    squares = arena.squares_in_sphere((15, 15), 20)
    assert squares == {(x, y) for x in range(11, 19) for y in range(11, 19)}


def test_sphere_is_clipped_to_the_map():
    assert len(Arena(10, 10).squares_in_sphere((0, 0), 20)) == 16


def test_cube():
    assert Arena(30, 30).squares_in_cube((2, 3), 20) == {(x, y) for x in range(2, 6) for y in range(3, 7)}


def test_cone_widens_with_distance():
    arena = Arena(30, 30)
    cone = arena.squares_in_cone((10, 10.5), (20, 10.5), 30)   # 30-ft cone pointing right
    assert (10, 10) in cone and (15, 10) in cone and (16, 10) not in cone
    assert (9, 10) not in cone                                # nothing behind the origin
    widths = {x: len([s for s in cone if s[0] == x]) for x in range(10, 16)}
    assert widths[10] == 1 and widths[15] > widths[12] > widths[10]


def test_line():
    arena = Arena(30, 30)
    line = arena.squares_in_line((0, 5.5), (10, 5.5), 50)
    assert line == {(x, 5) for x in range(10)}


def test_creatures_in_area():
    placements = {'troll': at(5, 5, 2), 'goblin': at(9, 9), 'kobold': at(20, 20)}
    area = Arena(30, 30).squares_in_sphere((8, 8), 10)
    assert sorted(Arena.creatures_in(area, placements)) == ['goblin', 'troll']


# Loading

def test_from_dict():
    arena = Arena.from_dict({
        'name': 'Bridge', 'width': 20, 'height': 12, 'diagonals': '5/10/5',
        'terrain': [{'rect': [0, 0, 19, 3], 'impassable': True, 'cover': 'total'},
                    {'squares': [[9, 6]], 'cover': 'half'},
                    {'rect': [5, 8, 6, 9], 'difficult': True}],
        'start_zones': {'party': {'rect': [0, 4, 1, 5]}, 'monsters': {'squares': [[17, 5]]}},
    })
    assert arena.name == 'Bridge' and arena.diagonals == DIAGONALS_ALTERNATING
    assert arena.terrain_at((19, 3)) == WALL and arena.terrain_at((9, 6)).cover == COVER_HALF
    assert arena.terrain_at((6, 9)).difficult and arena.terrain_at((7, 9)).difficult is False
    assert sorted(arena.start_zones['party']) == [(0, 4), (0, 5), (1, 4), (1, 5)]
    assert arena.start_zones['monsters'] == [(17, 5)]


@pytest.mark.parametrize('kwargs', [
    {'width': 0, 'height': 5},
    {'width': 5, 'height': 5, 'diagonals': 'hex'},
    {'width': 5, 'height': 5, 'terrain': {(5, 0): WALL}},
    {'width': 5, 'height': 5, 'start_zones': {'party': [(-1, 0)]}},
])
def test_invalid_arenas(kwargs):
    with pytest.raises(ValueError):
        Arena(**kwargs)


def test_invalid_cover_level():
    with pytest.raises(ValueError):
        Terrain(cover='partial')
