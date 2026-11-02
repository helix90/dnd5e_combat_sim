"""Arena phase 3: cover in combat, the AI using cover, and the encounter and generic maps."""
import copy
import json
import random
from unittest.mock import patch

import pytest

from ai.positioning import _Planner, fit_plan
from app import app as flask_app
from models.actions import AttackAction
from models.arena import COVER_HALF, COVER_TOTAL, Arena, Placement, Terrain
from models.arena_library import (DEFAULT_MAP, ENCOUNTER_MAP, arena_choices, get_arena, load_arena_definitions,
                                  resolve_arena_choice)
from models.character import Character
from models.character_builder import build_party
from models.combat import Combat
from models.monster import Monster
from models.monster_builder import build_monsters
from models.spells import Spell, SpellAction
from utils.party_loader import PartyLoader
from utils.paths import data_path

SCORES = {'str': 14, 'dex': 14, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}
WALL = Terrain(impassable=True, cover=COVER_TOTAL)
LOW_WALL = Terrain(difficult=True, cover=COVER_HALF)
BOULDER = Terrain(impassable=True, cover='three_quarters')
TEMPLATES = json.load(open(data_path('encounter_templates.json')))['encounters']
MONSTERS = {m['name']: m for m in json.load(open(data_path('monsters.json')))['monsters']}


def bow(hit_bonus=4):
    return AttackAction('Shortbow', '', 'Shortbow', '1d6+2', 'piercing', hit_bonus=hit_bonus,
                        weapon_type='ranged', range=[80, 320])


def archer(name='Archer', side='party', hit_bonus=4):
    if side == 'party':
        return Character(name, 1, 'Ranger', 'Human', SCORES, hp=30, ac=12, proficiency_bonus=2,
                         actions=[bow(hit_bonus)])
    return Monster(name, '1/4', 30, 12, SCORES, actions=[bow(hit_bonus)])


def target(name='Orc', hp=30):
    return Monster(name, '1/2', hp, 13, SCORES, actions=[AttackAction('Greataxe', '', 'Greataxe', '1d12+3', 'slashing', hit_bonus=5)])


def fight(creatures, terrain=None, width=30, height=20):
    return Combat(creatures, arena=Arena(width, height, terrain or {}, name='Test'))


def put(combat, creature, x, y):
    size = combat.battlefield.placements[creature].size
    combat.battlefield.placements[creature] = Placement((x, y), size)


def shoot(combat, attacker, victim, roll=10):
    with patch('random.randint', return_value=roll):
        return combat._execute_action(attacker, {'type': 'attack', 'action': attacker.actions[0], 'target': victim})


# Cover in combat

@pytest.mark.parametrize('terrain, cover, bonus', [(LOW_WALL, 'half', 2), (BOULDER, 'three_quarters', 5)])
def test_cover_adds_to_ac(terrain, cover, bonus):
    a, t = archer(), target()
    combat = fight([a, t], {(5, y): terrain for y in range(20)})
    put(combat, a, 0, 5)
    put(combat, t, 8, 5)
    result = shoot(combat, a, t)
    assert result['cover'] == cover and result['target_ac'] == 13 + bonus


def test_total_cover_blocks_the_attack():
    a, t = archer(), target()
    combat = fight([a, t], {(5, y): WALL for y in range(20)})
    put(combat, a, 0, 5)
    put(combat, t, 8, 5)
    result = shoot(combat, a, t)
    assert result['reason'] == 'out of range' and result['cover'] == COVER_TOTAL and t.hp == 30
    combat.logger.log_action(a, result, 1)
    assert combat.format_log_for_web()[-1] == 'Archer can\'t see Orc (total cover).'


def test_a_creature_in_the_way_gives_half_cover():
    a, t, ally = archer(), target(), Character('Fighter', 1, 'Fighter', 'Human', SCORES, hp=30, ac=16, proficiency_bonus=2)
    combat = fight([a, ally, t])
    put(combat, a, 0, 5)
    put(combat, ally, 4, 5)
    put(combat, t, 8, 5)
    assert shoot(combat, a, t)['cover'] == COVER_HALF
    put(combat, ally, 4, 15)
    assert 'cover' not in shoot(combat, a, t)


def test_remembered_terrain_cover_still_counts_creatures_that_move_in():
    arena = Arena(20, 20, {(5, 2): LOW_WALL, **{(x, 9): WALL for x in range(20)}})
    a, t = Placement((0, 5)), Placement((8, 5))
    assert arena.cover(a, t) == 'none'
    assert arena.cover(a, t, [Placement((4, 5))]) == COVER_HALF
    assert arena.cover(a, t) == 'none'
    # A low wall's cover isn't raised by a creature, and nothing adds to total cover
    assert arena.cover(Placement((5, 0)), Placement((5, 4)), [Placement((4, 2))]) == COVER_HALF
    assert arena.cover(Placement((9, 7)), Placement((9, 11)), [Placement((9, 8))]) == COVER_TOTAL


def test_melee_next_to_a_low_wall_is_not_covered_by_it():
    fighter = Character('Fighter', 1, 'Fighter', 'Human', SCORES, hp=30, ac=16, proficiency_bonus=2,
                        actions=[AttackAction('Longsword', '', 'Longsword', '1d8+2', 'slashing', hit_bonus=5)])
    t = target()
    combat = fight([fighter, t], {(4, 4): LOW_WALL})
    put(combat, fighter, 4, 5)
    put(combat, t, 5, 5)
    assert 'cover' not in shoot(combat, fighter, t)


def spell(name, **kwargs):
    return Spell(name, 0, 'Evocation', '1 action', '120 feet', '', '', damage_dice='1d10', damage_type='fire', **kwargs)


def test_spell_attacks_and_dex_saves_get_cover_but_sacred_flame_ignores_it():
    caster = Character('Wizard', 1, 'Wizard', 'Human', SCORES, hp=20, ac=12, proficiency_bonus=2)
    t = target(hp=200)
    combat = fight([caster, t], {(5, y): LOW_WALL for y in range(20)})
    put(combat, caster, 0, 5)
    put(combat, t, 8, 5)

    def cast(s):
        with patch('random.randint', return_value=10):
            return combat._execute_action(caster, {'type': 'cast_spell', 'spell': SpellAction(s), 'target': t})
    bolt = cast(spell('Fire Bolt', is_attack_spell=True))
    assert bolt['cover'] == 'half' and bolt['target_ac'] == 15
    saved = cast(spell('Poison Spray', save_type='dex'))
    assert saved['cover_bonus'] == 2
    flame = cast(spell('Sacred Flame', save_type='dex'))
    assert 'cover_bonus' not in flame and 'cover' not in flame


# The AI and cover

def test_archer_moves_to_shoot_around_cover():
    # The target hides behind a short wall (total cover from here); moving along the wall gives
    # the best line the archer can reach this turn, half cover
    a, t = archer(), target()
    combat = fight([a, t], {(10, y): WALL for y in range(3, 8)})
    put(combat, a, 2, 5)
    put(combat, t, 12, 5)
    assert combat.battlefield.cover(a, t) == COVER_TOTAL
    plan = fit_plan(a, {'type': 'attack', 'action': a.actions[0], 'target': t}, combat._build_combat_state(a))
    assert plan['target'] is t and 'move_to' in plan
    assert combat.battlefield.arena.cover(Placement(plan['move_to']), Placement((12, 5))) == COVER_HALF


def test_ranged_attacker_takes_cover_while_shooting():
    # An enemy archer 50 ft away; a low wall two squares from the party archer
    a, enemy = archer(), archer('Goblin', side='monsters')
    combat = fight([a, enemy], {(4, y): LOW_WALL for y in range(3, 8)})
    put(combat, a, 2, 5)
    put(combat, enemy, 13, 5)
    plan = fit_plan(a, {'type': 'attack', 'action': a.actions[0], 'target': enemy}, combat._build_combat_state(a))
    spot = plan.get('move_to', (2, 5))
    assert combat.battlefield.arena.cover(Placement((13, 5)), Placement(spot)) != 'none'
    # ...and still has a clear enough shot
    assert combat.battlefield.cover(a, enemy, spot) != COVER_TOTAL


def test_ai_does_not_shoot_at_a_target_in_total_cover():
    a, hidden, visible = archer(), target('Hidden'), target('Visible')
    terrain = {(x, 9): WALL for x in range(30)}   # a wall across the whole map
    combat = fight([a, hidden, visible], terrain)
    put(combat, a, 5, 5)
    put(combat, hidden, 5, 12)
    put(combat, visible, 15, 5)
    plan = fit_plan(a, {'type': 'attack', 'action': a.actions[0], 'target': hidden}, combat._build_combat_state(a))
    assert plan['target'] is visible


def test_no_cover_seeking_on_maps_without_cover_terrain():
    a, enemy = archer(), archer('Goblin', side='monsters')
    combat = fight([a, enemy])
    assert not _Planner(combat.battlefield, a).seeks_cover


# Maps

def test_every_template_names_an_encounter_map_and_the_generic_maps_are_listed():
    definitions = {d['name']: d for d in load_arena_definitions()}
    for template in TEMPLATES:
        assert template['arena'] in definitions and not definitions[template['arena']].get('generic')
    assert len({t['arena'] for t in TEMPLATES}) == len(TEMPLATES)   # each encounter has its own map
    assert sorted(a['name'] for a in arena_choices() if a['generic']) == ['Corridor', 'Forest', 'Open Field', 'Ruins']


def encounter(template):
    party = build_party(PartyLoader.get_party_with_level(1, template['level'])['characters'])
    monsters = []
    for entry in template['monsters']:
        for i in range(entry['count']):
            data = copy.deepcopy(MONSTERS[entry['name']])
            data['name'] = f"{entry['name']} {i + 1}"
            monsters.append(data)
    return party, build_monsters(monsters)


@pytest.mark.parametrize('template', TEMPLATES, ids=lambda t: t['name'])
def test_encounter_fits_its_map_and_every_monster_can_reach_the_party(template):
    party, monsters = encounter(template)
    arena = get_arena(template['arena'])
    combat = Combat(party + monsters, arena=arena)
    bf = combat.battlefield
    for creature, placement in bf.placements.items():
        assert placement.position in arena.start_zones['party' if creature in party else 'monsters']
    for monster in monsters:
        size = bf.placements[monster].size
        near_party = lambda sq: any(arena.distance_at(sq, size, bf.placements[h]) <= 5 for h in party)
        assert arena.path_to_nearest(bf.placements[monster], near_party) is not None, monster.name


@pytest.mark.parametrize('template', TEMPLATES[::4], ids=lambda t: t['name'])
def test_fights_on_encounter_maps_finish(template):
    random.seed(1)
    party, monsters = encounter(template)
    result = Combat(party + monsters, arena=get_arena(template['arena'])).run()
    assert result['winner'] in ('party', 'monsters') and result['arena'] == template['arena']


@pytest.mark.parametrize('choice, template, expected', [
    ('', {'arena': 'Troll Bridge'}, None),
    (ENCOUNTER_MAP, {'arena': 'Troll Bridge'}, 'Troll Bridge'),
    (ENCOUNTER_MAP, None, DEFAULT_MAP),
    ('Forest', {'arena': 'Troll Bridge'}, 'Forest'),
])
def test_resolve_arena_choice(choice, template, expected):
    assert resolve_arena_choice(choice, template) == expected


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client


def test_encounter_map_choice_uses_the_prebuilt_encounters_map(client):
    client.post('/party', data={'party_id': '1', 'party_level': '5'})
    assert client.post('/encounter/arena', json={'arena': ENCOUNTER_MAP}).status_code == 200
    client.post('/encounter/prebuilt', json={'template_name': 'Troll Bridge', 'party_level': 5, 'party_size': 4})
    with patch('app.simulation_controller.execute_simulation') as run:
        client.get('/simulate')
    assert run.call_args.kwargs['arena_name'] == 'Troll Bridge'
    assert 'Troll Bridge' in client.get('/batch').get_data(as_text=True)
    # A custom encounter has no map of its own, so it's fought on the Open Field
    client.post('/encounter/custom', json={'monsters': [{'name': 'Goblin', 'cr': '1/4', 'hp': 7, 'ac': 15}],
                                           'party_level': 5, 'party_size': 4})
    with patch('app.batch_simulation_controller.execute_batch_simulation', return_value=1) as batch:
        client.post('/batch/start', json={'num_runs': 10})
    assert batch.call_args.kwargs['arena_name'] == DEFAULT_MAP


def test_encounter_page_lists_generic_and_encounter_maps(client):
    page = client.get('/encounter').get_data(as_text=True)
    assert 'Maps for any encounter' in page and 'Pre-built encounter maps' in page
    assert f'value="{ENCOUNTER_MAP}"' in page and '<option value="Troll Bridge"' in page
