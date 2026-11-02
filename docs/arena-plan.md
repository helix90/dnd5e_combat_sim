# Arena Plan: positions, distance, cover and ranged attacks

Status: phase 1 done; phase 2 next.

## Why

Without positions the simulator treats every fight as if everyone can reach everyone, and it uses
stand-ins for rules that depend on where creatures are:

- Any creature can attack any enemy on any turn, so melee monsters reach the back line for free.
- Area effects hit every enemy: Fireball hits every monster, and the dragon's 30-ft cone hits the
  whole party (`ai/strategy.py`, the `area_effect` branches).
- "An ally within 5 feet of the target" (Sneak Attack, Pack Tactics) is approximated by "an ally is
  alive" (`Combat._has_active_ally`), and paralysis auto-crits assume the attacker is adjacent.
- Monsters always use their first attack, so goblins, skeletons and hobgoblins never use their
  bows and the Hill Giant never throws rocks.

The arena removes these approximations. It also shows another way Challenge Rating misses the
point: the same monsters can be much easier or harder depending on terrain and distance, and CR
ignores both.

## Decisions

1. **Grid**: a 5-ft square grid. Diagonals cost 5 ft (PHB default); the DMG 5/10/5 variant is an
   option on the arena.
2. **Optional**: "No arena" stays the default. Without an arena, combat runs exactly as it does now,
   so existing results stay reproducible and can be compared with arena results.
3. **Maps**: each pre-built encounter gets its own map (a bridge for Troll Bridge, a maze for
   Minotaur Maze, and so on). The encounters' monster mixes don't change. Custom encounters choose
   from a set of generic maps (open field, forest, corridor, ruins).
4. **Opportunity attacks** come in phase 5, together with Disengage, Dash and Cunning Action.

## Design

### Geometry: `models/arena.py`

Pure geometry, no combat rules.

- An `Arena` has a width and height in squares, per-square terrain and start zones for each side.
  Terrain marks a square as difficult (double movement cost), impassable, and/or an obstacle that
  gives half, three-quarters or total cover.
- Creature sizes take up squares: Tiny, Small and Medium 1×1; Large 2×2; Huge 3×3;
  Gargantuan 4×4. A position is the creature's top-left square.
- `distance()` measures between the nearest squares two creatures occupy, which is what reach
  needs.
- `reachable_squares()` finds where a creature can move with its movement. It goes around
  obstacles, pays double for difficult terrain, can pass through allies but not enemies, and can't
  end in an occupied square. `path_to()` returns the route.
- `cover()` uses the DMG grid method. The attacker picks a corner of its space, and lines are traced
  to the four corners of one square of the target. One or two blocked lines give half cover; three
  or four give three-quarters. If every line is blocked by total-cover terrain, the target has total
  cover. Creatures in the way count as obstacles that give at most half cover, and low obstacles
  cap the result at their own cover level. The attacker gets the best corner and target square.
- Area templates for spheres, cubes, cones and lines return the squares and creatures they cover.
  A square is in the area if its center is.

### Data

- Creatures get `speed` (walk, plus fly/climb where they have them) and `size`. Character speed
  follows race (dwarves, halflings and gnomes 25 ft) plus Unarmored Movement and Fast Movement.
- Attacks get `reach` (melee, default 5 ft, 10 ft for e.g. the Hill Giant's greatclub) and
  `range: [normal, long]` (ranged and thrown, e.g. shortbow 80/320, rock 60/240).
- Spells convert their text range to feet (`"120 feet"` → 120, `"Touch"` → 5, `"Self"` → 0).
  Area shapes are added in phase 4.
- `data/arenas.json` holds the maps; encounter templates refer to their map by name.

### Combat: `Combat(participants, arena=None)`

- With an arena, combat tracks each creature's position and puts positions and a read-only view of
  the arena into the combat state for the AI.
- AI plans can include `move_before` and `move_after`. Combat checks the path against the
  creature's speed. Dash doubles movement and uses the action.
- One place, `Combat._attack_situation(attacker, target, action)`, decides for every attack:
  - in reach or range; long range gives disadvantage;
  - ranged attack with a non-incapacitated enemy within 5 ft gives disadvantage;
  - cover: +2 AC (half), +5 AC (three-quarters), can't be targeted (total);
  - real adjacency for Sneak Attack, Pack Tactics and paralysis auto-crits.
- `AttackAction.execute` and `SpellAction.execute` take an `ac_bonus` for cover. DEX saves get the
  cover bonus measured from the effect's point of origin.
- Log entries record positions so a fight can be replayed.

### AI

- Melee creatures move to and attack the best target they can reach, weighing threat against
  distance, and Dash when nobody is in reach.
- Ranged creatures and casters stay within normal range, back away from adjacent enemies, and prefer
  squares with cover.
- Weapon choice depends on distance (bow vs. sword, rock vs. greatclub) for monsters and characters.
- Healing needs the target within the spell's range.
- Area effects are aimed where they hit the most enemies without catching allies (phase 4).

### App, storage and UI

- Encounter page: an arena option. "No arena" is the default; pre-built encounters offer their
  own map, and custom encounters offer the generic maps. Batches accept an arena too.
- The database stores the arena with each simulation and batch.
- The simulation page gets a battle-map replay (SVG grid, round by round) next to the log, and log
  lines mention distance and cover.
- Batch results compare the same encounter with and without its arena.

## Phases

Each phase is its own branch, merged only when the full test suite passes.

| Phase | Contents | Visible result |
|---|---|---|
| 1 | Geometry module; speed, size, reach and range data; spell ranges in feet; shared monster builder | No change to fights; the base is tested |
| 2 | Positions, movement, reach and range, ranged-in-melee, real adjacency, weapon choice by distance, AI movement, an open-field map, arena option in the app | First arena fights; bows and thrown rocks get used |
| 3 | Cover from terrain and creatures, AI uses cover, a map for every pre-built encounter plus the generic maps | Terrain matters |
| 4 | Area shapes and aiming, breath weapon recharge | Fireball and dragon breath hit only who is in the area |
| 5 | Opportunity attacks, Disengage, Dash, Cunning Action, Nimble Escape | Moving away from melee has a cost |
| 6 | Battle-map replay, arena vs. no-arena comparison in results | Fights can be watched, and the arena's effect measured |

## Testing

- Geometry: distance (including Large and Huge creatures), pathing around obstacles and through
  allies, each cover level, each area shape. Fixed layouts, no dice.
- Rules: each attack rule with mocked rolls, as the existing combat tests do.
- Regression: all existing tests pass unchanged, and a sweep without an arena matches current
  results.
- Performance: a 1,000-run arena batch stays acceptably fast.

## Simplifications

- Flying creatures move like walking ones until phase 2 decides how flying works on the grid.
- Squeezing, and moving through a hostile creature two sizes larger, aren't modelled.
- Facing, elevation and light/vision aren't modelled.
