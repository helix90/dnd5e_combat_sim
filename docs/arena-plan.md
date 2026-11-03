# Arena Plan: positions, distance, cover and ranged attacks

Status: all six phases done.

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

## Phase 2 as built

- `models/battlefield.py`: `Battlefield` holds each creature's placement on an `Arena` and the
  rules that depend on it: `attack_situation` and `spell_situation` (in reach or range, long
  range, enemy within 5 ft), `ally_next_to` (Sneak Attack, Pack Tactics), movement, and placing
  each side in its start zone (front-liners nearest the enemy, back-line classes 10 ft behind).
- `ai/positioning.py`: `fit_plan` turns the strategy's plan into one the creature can carry out.
  It scores each attack, weapon or spell from every square the creature can reach this turn
  (expected damage, the strategy's target counting 30% more, then shorter moves and more
  distance from enemies), keeps the strategy's target when it can, and otherwise picks another.
  A creature that has to use a weaker attack where it stands (a fighter's crossbow, a giant's
  rock) attacks and then moves toward its target (`move_after`). A creature that can't reach
  anyone Dashes. Creatures whose ranged and melee attacks are equally good (goblins, skeletons)
  stay at range and shoot.
- Combat: `Combat(participants, arena=None)`. Plans may carry `move_to`, `move_after` and a
  planned `path`; Combat checks paths against speed and enemies. Attacks and spells out of reach
  or range don't happen (and spend no spell slot). Multiattack picks the routine whose attacks
  reach (a wight's longbows). Results and log entries include `movement`, `distance` and
  `disadvantage_reasons`; the fight's result includes `arena` and `start_positions`.
- Maps: `data/arenas.json` has the Open Field (28 x 20 squares, sides about 55 ft apart),
  loaded by `models/arena_library.py`.
- App: an Arena choice on the encounter page (saved in the session by `POST /encounter/arena`),
  used by single and batch simulations; the arena name is stored with simulations and batches
  (new `arena` columns, added to existing databases on startup) and shown on the batch and results
  pages.
- Without an arena nothing changes: a 3,000-run Kobold Mob check gives 8.6% party wins on `main`
  and 8.1% on the branch.
- Speed: an arena fight takes about 40-80 ms against about 5 ms without one, so a 1,000-run
  arena batch takes around a minute.

## Phase 3 as built

- Cover: `Arena.cover` uses the DMG corner-to-corner lines; `Battlefield.cover` also counts other
  creatures as obstacles (half cover). Half cover adds +2 and three-quarters +5 to AC and to DEX
  saves; total cover means the target can't be targeted. Melee targets next to the attacker,
  area effects and Sacred Flame ignore cover. Results carry `cover` (and `cover_bonus` for
  saves), and the log shows it, e.g. "(30 ft, half cover)".
- AI: attacks are scored against the target's cover from each square, so creatures move for a
  clearer line and never aim at a target in total cover. On maps with cover terrain, a creature
  attacking from range also values shelter from the three nearest enemies. The AI judges cover
  from terrain only (creatures in the way move too often to be worth the time); the attack itself
  counts them. Only the 12 best squares from a rough pass are rescored with cover.
- Speed: terrain cover is cached per line and per pair of squares on the Arena, which a batch
  reuses for every run. In a 200-run sweep, fights on the encounter maps took 46-666 ms (mean
  about 200 ms; the big undead fights in the Catacombs and the Field of Bones are the slowest)
  and on the Open Field 41-184 ms, so a 1,000-run batch takes from under a minute to 11 minutes.
- Sweep (party win %, 200 runs, no arena / Open Field / own map): melee swarms get much easier
  on a map (Kobold Mob 5 / 61 / 64, Wolf Pack 24 / 61 / 66, Orc Raiders 47.5 / 50.5 / 79), while
  archers and undead mobs get harder (Goblin Ambush 51.5 / 36 / 34, Undead Crypt 23.5 / 5 / 11,
  Skeleton Horde 11.5 / 4 / 3.5). Most other encounters move by less than 10 points.
- Maps: `data/arenas.json` has four generic maps (Open Field, Forest, Corridor, Ruins) and a map
  for each pre-built encounter, which names it in `encounter_templates.json` (`"arena"`). Only
  that field was added to the templates; their monsters are unchanged. Terrain may be given as
  rectangles (`"rects"`) and carries a `kind` for drawing later.
- App: the arena choice adds "The encounter's own map" (`@encounter`); a custom encounter has no
  map, so it gets the Open Field.

## Phase 4 as built

- Data: spells and monster actions can have an `area` (`{"shape": "sphere", "size": 20}`):
  Fireball is a 20-ft-radius sphere, Web a 20-ft cube, and the Young Dragon's Fire Breath a 30-ft
  cone with `"recharge": 5`.
- Geometry: `Area` (sphere, cube, cone, line) in `models/arena.py`; `area_squares`, `in_area`,
  and `cover_from_point` (cover from an area's origin). `Battlefield.can_aim` and `area_hits`
  apply the rules: spheres and cubes are placed within the spell's range, cones and lines start
  at the edge of the creature's space, every creature in the area is affected (allies too, but
  never the creature using a cone), total cover from the origin protects, and other cover adds
  to DEX saves.
- AI: `ai/aiming.py` tries sphere centres and cube corners around each enemy, and cones from the
  creature's square or the 16 nearest an enemy, pointed at each enemy and 20 degrees either side.
  Each is scored by expected damage to enemies minus twice that to allies. If the best is worth
  less than the creature's best ordinary attack or cantrip, it uses that instead and keeps its
  spell slot or breath.
- Recharge: an action with `recharge` can't be used again until a d6 at the start of the
  creature's turn rolls that number or higher. The monster AI uses a ready area attack first.
  Before this the dragon never breathed: the AI always took its first special (Multiattack).
  This changes results without an arena too.
- An area action catching a single creature now calls for a save; it used to make an attack roll.
- Sweep (party win %, 200 runs, phase 3 -> phase 4): the Young Dragon now breathes and wins
  almost every fight (Young Dragon's Den, no arena 96.5 -> 0, own map 96 -> 2.5). On arenas,
  Fireball no longer hits every enemy on the map, so encounters with spread-out monsters got much
  harder (own map: Vampire's Lair 37 -> 2, Wraith's Domain 90 -> 22.5, Vampire Spawn Pack 87 ->
  45.5). That isn't friendly fire: with the AI refusing to hit allies the results are the same.
  Fights on the encounter maps take 59-667 ms (mean about 210 ms).
- Combat: area results carry `aim` (origin and direction), `area` and `cover_by_target`; an area
  that would catch no one isn't used and spends no slot. Logs read e.g. "uses Fire Breath on
  Aldric, Dax: 80 damage (30-ft cone)" and "Young Dragon's Fire Breath recharges."

## Phase 5 as built

- Opportunity attacks: `Battlefield.provoked` walks a move's path and gives each enemy that can
  react (on the map, not incapacitated, reaction unused) one melee attack the first time the mover
  leaves its reach, from the square the mover is leaving. Reach comes from the creature's melee
  attacks (`melee_reach`), so the Hill Giant's 10-ft greatclub provokes further out and an archer
  with no melee attack doesn't provoke at all. Combat makes the attack with the enemy's best melee
  attack that reaches (one attack, never a Multiattack; Sneak Attack applies) and logs it as that
  enemy's entry ("Opportunity Attack: Orc uses Greataxe on Aldric: 9 damage (5 ft)."). An attack
  that drops the mover ends its move there, and it loses its action. A creature's reaction comes
  back at the start of its turn (`Battlefield.reacted`).
- Disengage: a plan of type `disengage` (the action) or a `bonus_action` of `Disengage` stops
  opportunity attacks for the rest of the turn. Combat honours a bonus action only for creatures
  with the feature: Cunning Action (rogues: Disengage or Dash) and Nimble Escape (goblins:
  Disengage). Dash as a bonus action adds the creature's speed again, so a rogue can move 60 ft
  and still attack, or 90 ft with the Dash action too.
- AI: a square is worth less by the expected damage of the opportunity attacks that ending a move
  there provokes (from enemies whose reach the creature is in now and that can react). A creature
  that can Disengage as a bonus action does so when its move leaves an enemy's reach and pays
  nothing; a rogue moving beyond its speed uses the bonus action to Dash instead and pays for the
  attacks. If reaching the strategy's target provokes, the creature compares it with every other
  target first, so an orc held by a fighter keeps hitting the fighter rather than walking past it
  to the wizard. Archers and casters in melee usually stay and shoot with disadvantage.
- Sweep (party win %, 200 runs, phase 4 -> phase 5; without an arena nothing changed, which a
  seeded run of 400 fights confirms exactly): on the Open Field, Orc Raiders 48 -> 64.5 (orcs
  that switch targets get cut down by opportunity attacks), while Goblin Ambush 42.5 -> 30.5,
  Wolf Pack 64.5 -> 51 and Vampire Spawn Pack 19.5 -> 11 got harder (the party can no longer step
  back from melee for free). On the encounter maps: Kobold Mob 65.5 -> 56, Vampire Spawn Pack
  45.5 -> 32.5, Ghoul Nest 88 -> 81, Undead Crypt 16 -> 10, Wraith's Domain 22.5 -> 15.5; the
  rest moved by 6 points or less. Goblins rarely use Nimble Escape: in melee their scimitar is as
  good as their bow, so they stay and stab.
- Speed: fights on the encounter maps take 68-763 ms (mean about 250 ms).

## Phase 6 as built

- Replay: on an arena, Combat records a frame for every action it logs (`CombatLogger.on_action`):
  where each creature still on the map stands, everyone's HP, the moves the action made, the
  squares of an area effect and the targets. Frame i goes with the i-th action of the log, so it
  lines up with the stored log rows; an opportunity attack's frame shows the mover where it was
  attacked. `Combat.replay()` adds the map (`Arena.drawing()`: size and each terrain square with
  its kind from the map file), the creatures (side, size, max HP) and the start positions, and
  the fight's result carries it as `replay`. Recording adds about 3 ms to a fight.
- Storage: `simulations.replay` holds it as zlib-compressed JSON (1-3 KB instead of 10-60 KB), for
  single simulations and batch runs alike; `DatabaseManager.get_replay` reads it, and
  `get_simulation` and the history leave it out. Older databases get the column on startup.
- Results page: fights on an arena get a "Battle Map" card: an SVG grid with terrain coloured by
  kind, creatures as tokens coloured by side and sized by their space, with HP bars, the acting
  creature ringed, its targets dashed, its moves as arrows and area effects shaded. Buttons step
  by action or by round, play it back, and a slider scrubs through it; the log beside the map
  follows along (naming the target of each attack) and clicking a line jumps there. The legend
  lists only the terrain the map has.
- Batches: with an arena chosen, the batch page offers (and ticks by default) "Also run every
  fight without the arena". Each run is then fought on the map and without it; the no-arena runs
  are saved as their own batch ("<name> (no arena)"), which the arena batch points to
  (`batch_simulations.baseline_batch_id`). Progress shows both, and both results pages get a
  "With and Without the Arena" table: party win rate, average rounds and average party HP left,
  with the arena's effect on each. Fights without an arena take a few milliseconds, so the
  comparison adds little time.

## Simplifications

- Flying is treated like walking (no elevation); a creature moves at its best speed, so the
  wraith moves 60 ft.
- Without an arena, an area effect still hits every enemy.
- Areas follow the grid's diagonal rule, so with 5-ft diagonals a sphere is a square block.
- Cover against an area effect comes from terrain only, and Web is never cast (the AI only picks
  damaging spells).
- The AI never takes the Disengage action itself (it only Disengages as a bonus action), and it
  judges opportunity attacks by where a move ends: an enemy whose reach it passes through on the
  way still attacks, but the AI doesn't foresee it.
- Opportunity attacks need no sight of the mover, and reach-extending reactions (Sentinel,
  Polearm Master), Hide and other bonus actions aren't modelled.
- Squeezing, and moving through a hostile creature two sizes larger, aren't modelled.
- Facing, elevation and light/vision aren't modelled.
- The replay shows each action's result, not the steps of a move: a move is an arrow from start
  to end.
