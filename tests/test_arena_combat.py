"""Arena phase 2: positions, movement, reach and range, adjacency, weapon choice and AI movement."""
import sqlite3
from unittest.mock import patch

import pytest

from ai.positioning import fit_plan
from models.actions import Action, AttackAction
from models.arena import Arena, Placement, Terrain, COVER_TOTAL
from models.arena_library import arena_choices, get_arena, load_arena_definitions
from models.battlefield import MONSTERS, PARTY
from models.buffs import create_paralyzed_condition
from models.character import Character
from models.combat import Combat
from models.db import DatabaseManager
from models.monster import Monster
from models.multiattack import parse_multiattack
from models.spells import Spell, SpellAction

SCORES = {'str': 14, 'dex': 14, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}


def sword(**kwargs):
    return AttackAction('Longsword', '', 'Longsword', '1d8+2', 'slashing', hit_bonus=5, **kwargs)


def bow(**kwargs):
    return AttackAction('Shortbow', '', 'Shortbow', '1d6+2', 'piercing', hit_bonus=4,
                        weapon_type='ranged', range=[80, 320], **kwargs)


def hero(name='Hero', actions=None, character_class='Fighter', hp=30, speed=30):
    return Character(name, 1, character_class, 'Human', SCORES, hp=hp, ac=12, proficiency_bonus=2,
                     actions=actions if actions is not None else [sword()], speed=speed)


def monster(name='Orc', actions=None, hp=15, speed=30, size='medium', abilities=None):
    return Monster(name, '1/2', hp, 13, SCORES, actions=actions if actions is not None else [sword()],
                   speed=speed, size=size, special_abilities=abilities or [])


def fight(*creatures, width=30, height=20):
    """A Combat on an empty arena, with creatures placed where the test puts them."""
    return Combat(list(creatures), arena=Arena(width, height, name='Test'))


def put(combat, creature, x, y):
    size = combat.battlefield.placements[creature].size
    combat.battlefield.placements[creature] = Placement((x, y), size)


def plan_for(combat, creature, plan):
    return fit_plan(creature, plan, combat._build_combat_state(creature))


def always_hit(roll=10):
    """Every d20 and damage die rolls `roll`."""
    return patch('random.randint', return_value=roll)


# Placement

def test_open_field_places_each_side_in_its_zone_with_back_line_behind():
    arena = get_arena('Open Field')
    fighter, wizard = hero('Fighter'), hero('Wizard', character_class='Wizard')
    giant = monster('Giant', size='huge')
    goblins = [monster(f'Goblin {i}') for i in range(6)]
    combat = Combat([fighter, wizard, giant] + goblins, arena=arena)
    bf = combat.battlefield
    taken = []
    for creature, placement in bf.placements.items():
        assert arena.fits(placement)
        taken += list(placement.squares())
        side = PARTY if isinstance(creature, Character) else MONSTERS
        assert placement.position in arena.start_zones[side]
    assert len(taken) == len(set(taken))  # nobody overlaps
    # The wizard starts 10 ft behind the fighter
    assert bf.position(wizard)[0] == bf.position(fighter)[0] - 2
    assert combat.start_positions['Giant'] == list(bf.position(giant))


def test_no_room_in_the_zone_spills_over_to_nearby_squares():
    arena = Arena(10, 3, start_zones={'party': [(0, 0)], 'monsters': [(9, 0)]})
    heroes = [hero(f'H{i}') for i in range(3)]
    combat = Combat(heroes + [monster()], arena=arena)
    positions = [combat.battlefield.position(h) for h in heroes]
    assert len(set(positions)) == 3 and (0, 0) in positions


# Reach and range rules

@pytest.mark.parametrize('distance_squares, in_range, reasons', [
    (1, True, []), (16, True, []), (17, True, ['long range']), (64, True, ['long range']), (65, False, []),
])
def test_bow_ranges(distance_squares, in_range, reasons):
    archer, target = hero(actions=[bow()]), monster()
    combat = fight(archer, target, width=70)
    put(combat, archer, 0, 0)
    put(combat, target, distance_squares, 0)
    situation = combat.battlefield.attack_situation(archer, target, archer.actions[0])
    assert situation.in_range == in_range
    # An adjacent target is also an enemy within 5 ft
    expected = reasons + (['enemy within 5 ft'] if distance_squares == 1 else [])
    assert situation.disadvantage_reasons == (expected if in_range else [])


def test_reach_and_thrown_weapons():
    giant_club = AttackAction('Greatclub', '', 'Greatclub', '3d8+5', 'bludgeoning', hit_bonus=8, reach=10)
    javelin = AttackAction('Javelin', '', 'Javelin', '1d6+2', 'piercing', hit_bonus=4,
                           weapon_type='thrown', reach=5, range=[30, 120])
    a, b = hero(actions=[giant_club, javelin]), monster()
    combat = fight(a, b)
    bf = combat.battlefield
    put(combat, a, 0, 0)
    put(combat, b, 2, 0)    # 10 ft
    assert bf.attack_situation(a, b, giant_club).melee
    assert not bf.attack_situation(a, b, sword()).in_range
    javelin_10 = bf.attack_situation(a, b, javelin)
    assert javelin_10.in_range and not javelin_10.melee and not javelin_10.disadvantage
    put(combat, b, 1, 0)    # adjacent: the javelin is a melee attack, no disadvantage
    assert bf.attack_situation(a, b, javelin).melee and not bf.attack_situation(a, b, javelin).disadvantage


def test_paralyzed_enemy_next_to_an_archer_does_not_hinder_it():
    archer, ghoul, target = hero(actions=[bow()]), monster('Ghoul'), monster('Target')
    combat = fight(archer, ghoul, target)
    put(combat, archer, 0, 0)
    put(combat, ghoul, 1, 0)
    put(combat, target, 6, 0)
    assert combat.battlefield.attack_situation(archer, target, bow()).disadvantage
    ghoul.buffs.add_buff(create_paralyzed_condition('Hero', 'con', 10))
    assert not combat.battlefield.attack_situation(archer, target, bow()).disadvantage


def test_spell_ranges():
    caster, ally, enemy = hero('Cleric'), hero('Ally'), monster()
    combat = fight(caster, ally, enemy)
    bf = combat.battlefield
    put(combat, caster, 0, 0)
    put(combat, ally, 2, 0)
    put(combat, enemy, 1, 1)
    touch = Spell('Cure Wounds', 1, 'Evocation', '1 action', 'Touch', '', '', healing=True)
    self_only = Spell('Shield', 1, 'Abjuration', '1 reaction', 'Self', '', '')
    bolt = Spell('Fire Bolt', 0, 'Evocation', '1 action', '120 feet', '', '', damage_dice='1d10',
                 is_attack_spell=True)
    assert not bf.spell_situation(caster, ally, touch).in_range        # 10 ft away
    assert bf.spell_situation(caster, caster, self_only).in_range
    assert not bf.spell_situation(caster, ally, self_only).in_range
    fire_bolt = bf.spell_situation(caster, enemy, bolt)
    assert fire_bolt.in_range and fire_bolt.disadvantage_reasons == ['enemy within 5 ft']


# Combat enforces the rules

def test_attack_out_of_reach_does_nothing():
    attacker, target = monster('Orc'), hero()
    combat = fight(attacker, target)
    put(combat, attacker, 0, 0)
    put(combat, target, 5, 0)
    result = combat._execute_action(attacker, {'type': 'attack', 'action': attacker.actions[0], 'target': target})
    assert result['reason'] == 'out of range' and result['distance'] == 25 and target.hp == 30


def test_long_range_attack_has_disadvantage():
    archer, target = monster('Archer', actions=[bow()]), hero()
    combat = fight(archer, target, width=70)
    put(combat, archer, 0, 0)
    put(combat, target, 30, 0)
    with patch('random.randint', side_effect=[18, 3, 4]):
        result = combat._execute_action(archer, {'type': 'attack', 'action': archer.actions[0], 'target': target})
    assert result['disadvantage'] and result['attack_roll'] == 3
    assert result['distance'] == 150 and result['disadvantage_reasons'] == ['long range']


def test_paralysis_crits_need_the_attacker_within_5_ft():
    club = AttackAction('Greatclub', '', 'Greatclub', '1d8+5', 'bludgeoning', hit_bonus=50, reach=10)
    giant, target = monster('Giant', actions=[club]), hero()
    combat = fight(giant, target)
    target.buffs.add_buff(create_paralyzed_condition('Ghoul', 'con', 10))
    put(combat, giant, 0, 0)
    put(combat, target, 2, 0)   # 10 ft: in reach, but too far for an automatic critical hit
    with always_hit():
        far = combat._execute_action(giant, {'type': 'attack', 'action': club, 'target': target})
    assert far['hit'] and not far['critical']
    put(combat, target, 1, 0)
    with always_hit():
        near = combat._execute_action(giant, {'type': 'attack', 'action': club, 'target': target})
    assert near['critical']


def test_ranged_attack_from_within_5_ft_of_a_paralyzed_target_crits():
    archer, target = monster('Archer', actions=[AttackAction(
        'Shortbow', '', 'Shortbow', '1d6+2', 'piercing', hit_bonus=50, weapon_type='ranged', range=[80, 320])]), hero()
    combat = fight(archer, target)
    target.buffs.add_buff(create_paralyzed_condition('Ghoul', 'con', 10))
    put(combat, archer, 0, 0)
    put(combat, target, 1, 0)
    with always_hit():
        result = combat._execute_action(archer, {'type': 'attack', 'action': archer.actions[0], 'target': target})
    assert result['critical']


def test_pack_tactics_needs_an_ally_next_to_the_target():
    kobold, ally, target = (monster('Kobold', abilities=['Pack Tactics']), monster('Kobold 2'), hero())
    combat = fight(kobold, ally, target)
    put(combat, kobold, 0, 0)
    put(combat, target, 1, 0)
    put(combat, ally, 10, 10)
    assert not combat._pack_tactics(kobold, target)
    put(combat, ally, 2, 0)
    assert combat._pack_tactics(kobold, target)


def test_sneak_attack_needs_an_ally_next_to_the_target():
    rogue = Character('Rogue', 3, 'Rogue', 'Human', SCORES, hp=20, ac=14, proficiency_bonus=2,
                      class_features=['Sneak Attack (2d6)'], actions=[AttackAction('Shortbow', '', 'Shortbow', '1d6', 'piercing', hit_bonus=50,
                                            weapon_type='ranged', range=[80, 320])])
    ally, target = hero('Fighter'), monster(hp=200)
    combat = fight(rogue, ally, target)
    put(combat, rogue, 0, 0)
    put(combat, target, 8, 0)
    put(combat, ally, 0, 5)
    plan = {'type': 'attack', 'action': rogue.actions[0], 'target': target}
    with always_hit(3):
        assert 'sneak_attack' not in combat._execute_action(rogue, plan)
    put(combat, ally, 9, 0)
    with always_hit(3):
        assert combat._execute_action(rogue, plan)['sneak_attack'] > 0


def test_spell_out_of_range_keeps_its_slot():
    cleric, ally, enemy = hero('Cleric', character_class='Cleric'), hero('Ally', hp=5), monster()
    cleric.spell_slots_remaining = {1: 1}
    cure = Spell('Cure Wounds', 1, 'Evocation', '1 action', 'Touch', '', '', healing=True, damage_dice='1d8')
    combat = fight(cleric, ally, enemy)
    put(combat, cleric, 0, 0)
    put(combat, ally, 4, 0)
    result = combat._execute_action(cleric, {'type': 'cast_spell', 'spell': SpellAction(cure), 'target': ally})
    assert result['reason'] == 'out of range' and cleric.spell_slots_remaining == {1: 1}


def test_multiattack_switches_to_longbows_out_of_sword_reach():
    longsword = AttackAction('Longsword', '', 'Longsword', '1d8+2', 'slashing', hit_bonus=4)
    longbow = AttackAction('Longbow', '', 'Longbow', '1d8+2', 'piercing', hit_bonus=4,
                           weapon_type='ranged', range=[150, 600])
    multi = Action('special', 'Multiattack', 'The wight makes two longsword attacks or two longbow attacks.')
    wight, target = monster('Wight', actions=[multi, longsword, longbow]), hero(hp=200)
    combat = fight(wight, target)
    put(combat, wight, 0, 0)
    put(combat, target, 8, 0)
    with always_hit():
        far = combat._execute_action(wight, {'type': 'special', 'action': multi, 'target': target})
    assert [a['action'] for a in far['individual_attacks']] == ['Longbow', 'Longbow']
    put(combat, target, 1, 0)
    with always_hit():
        near = combat._execute_action(wight, {'type': 'special', 'action': multi, 'target': target})
    assert [a['action'] for a in near['individual_attacks']] == ['Longsword', 'Longsword']


def test_parse_multiattack_without_positions_uses_the_first_routine():
    longsword, longbow = sword(), bow()
    longbow.name = 'Longbow'
    text = 'The wight makes two longsword attacks or two longbow attacks.'
    assert [a.name for a in parse_multiattack(text, [longsword, longbow])] == ['Longsword', 'Longsword']
    assert parse_multiattack(text, [longsword, longbow], usable=lambda a: False) == []


def test_moves_are_limited_by_speed_and_enemies():
    runner, blocker = hero(speed=30), monster()
    combat = fight(runner, blocker, width=20, height=1)
    put(combat, runner, 0, 0)
    put(combat, blocker, 3, 0)
    bf = combat.battlefield
    with pytest.raises(ValueError):
        bf.move(runner, (5, 0), 30)    # the enemy blocks the only row
    assert bf.move(runner, (2, 0), 30) == 10
    with pytest.raises(ValueError):
        bf.move(runner, (0, 0), 5)     # 10 ft back with 5 ft of movement


def test_dash_doubles_movement():
    runner, target = monster(speed=30), hero()
    combat = fight(runner, target, width=40)
    put(combat, runner, 0, 0)
    put(combat, target, 30, 0)
    result = combat._take_turn(runner, {'type': 'dash', 'move_to': (12, 0), 'target': target})
    assert result['type'] == 'dash' and result['movement']['feet'] == 60
    assert combat.battlefield.position(runner) == (12, 0)


# AI movement and weapon choice

def test_melee_monster_moves_next_to_its_target_and_attacks():
    orc, target = monster(speed=30), hero()
    combat = fight(orc, target)
    put(combat, orc, 0, 0)
    put(combat, target, 6, 0)   # 30 ft: 25 ft of movement brings it adjacent
    plan = plan_for(combat, orc, {'type': 'attack', 'action': orc.actions[0], 'target': target})
    assert plan['type'] == 'attack' and plan['target'] is target
    assert combat.battlefield.arena.distance(Placement(plan['move_to']), Placement((6, 0))) == 5
    result = combat._take_turn(orc, plan)
    assert result['movement']['feet'] == 25 and result['distance'] == 5


def test_monster_with_a_bow_shoots_instead_of_charging():
    goblin, target = monster('Goblin', actions=[sword(), bow()]), hero()
    combat = fight(goblin, target)
    put(combat, goblin, 0, 0)
    put(combat, target, 11, 0)   # 55 ft
    plan = plan_for(combat, goblin, {'type': 'attack', 'action': goblin.actions[0], 'target': target})
    assert plan['action'].name == 'Shortbow' and 'move_to' not in plan


def test_far_away_melee_creature_dashes():
    zombie, target = monster('Zombie', speed=20), hero()
    combat = fight(zombie, target, width=40)
    put(combat, zombie, 0, 0)
    put(combat, target, 20, 0)
    plan = plan_for(combat, zombie, {'type': 'attack', 'action': zombie.actions[0], 'target': target})
    assert plan['type'] == 'dash' and plan['move_to'] == (8, 0)
    assert combat._take_turn(zombie, plan)['movement']['feet'] == 40


def test_archer_steps_away_from_melee_before_shooting():
    ranger, orc = hero('Ranger', actions=[bow()], character_class='Ranger'), monster()
    combat = fight(ranger, orc)
    put(combat, ranger, 5, 5)
    put(combat, orc, 6, 5)
    combat.battlefield.reacted.add(orc)   # no opportunity attack to fear
    # Ranger: the bow is its only attack; standing still would mean disadvantage
    plan = plan_for(combat, ranger, {'type': 'attack', 'action': ranger.actions[0], 'target': orc})
    assert plan['action'].name == 'Shortbow' and 'move_to' in plan
    assert combat.battlefield.arena.distance(Placement(plan['move_to']), Placement((6, 5))) > 5


def test_fighter_out_of_reach_shoots_then_advances():
    crossbow = AttackAction('Light Crossbow', '', 'Light Crossbow', '1d8', 'piercing', hit_bonus=2,
                            weapon_type='ranged', range=[80, 320])
    fighter, target = hero(actions=[sword(), crossbow]), monster()
    combat = fight(fighter, target)
    put(combat, fighter, 0, 0)
    put(combat, target, 11, 0)   # 55 ft: too far to close and swing this turn
    plan = plan_for(combat, fighter, {'type': 'attack', 'action': fighter.actions[0], 'target': target})
    assert plan['action'] is crossbow and 'move_to' not in plan and plan['move_after'] == (6, 0)
    result = combat._take_turn(fighter, plan)
    assert result['movement_after']['feet'] == 30 and combat.battlefield.position(fighter) == (6, 0)


def test_healer_moves_into_touch_range():
    cleric, wounded, enemy = hero('Cleric', character_class='Cleric'), hero('Wounded', hp=30), monster()
    cure = Spell('Cure Wounds', 1, 'Evocation', '1 action', 'Touch', '', '', healing=True, damage_dice='1d8')
    combat = fight(cleric, wounded, enemy)
    put(combat, cleric, 0, 0)
    put(combat, wounded, 4, 0)
    put(combat, enemy, 15, 15)
    plan = plan_for(combat, cleric, {'type': 'cast_spell', 'spell': SpellAction(cure), 'target': wounded})
    assert plan['type'] == 'cast_spell' and plan['target'] is wounded
    assert combat.battlefield.arena.distance(Placement(plan['move_to']), Placement((4, 0))) == 5


def test_strategy_target_out_of_reach_switches_to_one_in_reach():
    orc, near, far = monster(speed=30), hero('Near'), hero('Far')
    combat = fight(orc, near, far, width=40)
    put(combat, orc, 0, 0)
    put(combat, near, 1, 0)
    put(combat, far, 30, 0)
    plan = plan_for(combat, orc, {'type': 'attack', 'action': orc.actions[0], 'target': far})
    assert plan['target'] is near and 'move_to' not in plan


# Whole fights

@pytest.mark.parametrize('seed', range(5))
def test_arena_fights_finish_and_creatures_never_overlap(seed):
    import random
    random.seed(seed)
    arena = get_arena('Open Field')
    party = [hero('Fighter'), hero('Archer', actions=[sword(), bow()], character_class='Ranger')]
    monsters = [monster(f'Orc {i}') for i in range(3)] + [monster('Ogre', size='large', hp=40)]
    combat = Combat(party + monsters, arena=arena)
    combat.roll_initiative()
    while not combat.is_combat_over() and combat.current_round <= 30:
        combat.next_turn()
        squares = [s for c in combat.battlefield.creatures() for s in combat.battlefield.placements[c].squares()]
        assert len(squares) == len(set(squares))
        assert all(arena.fits(combat.battlefield.placements[c]) for c in combat.battlefield.creatures())
    assert combat.is_combat_over()
    lines = combat.format_log_for_web()
    assert any(' ft' in line for line in lines)


def test_result_reports_the_arena_and_start_positions():
    combat = Combat([hero(), monster(hp=1)], arena=get_arena('Open Field'))
    result = combat.run()
    assert result['arena'] == 'Open Field' and set(result['start_positions']) == {'Hero', 'Orc'}


def test_without_an_arena_nothing_changes():
    combat = Combat([hero(), monster()])
    assert combat.battlefield is None and 'battlefield' not in combat._build_combat_state(combat.participants[0])
    result = Combat([hero(), monster(hp=1)]).run()
    assert 'arena' not in result and 'start_positions' not in result


def test_walls_block_and_movement_goes_around():
    wall = {(10, y): Terrain(impassable=True, cover=COVER_TOTAL) for y in range(19)}
    arena = Arena(30, 20, wall, name='Wall')
    orc, target = monster(speed=30), hero()
    combat = Combat([orc, target], arena=arena)
    put(combat, orc, 8, 0)
    put(combat, target, 12, 0)
    plan = plan_for(combat, orc, {'type': 'attack', 'action': orc.actions[0], 'target': target})
    # 10 ft away, but the way round the wall is far longer than 30 ft
    assert plan['type'] == 'dash'
    combat._take_turn(orc, plan)
    assert combat.battlefield.position(orc)[1] > 0


# Maps

def test_every_map_loads_with_start_zones_for_both_sides():
    for definition in load_arena_definitions():
        arena = Arena.from_dict(definition)
        for zone in (arena.start_zones.get('party'), arena.start_zones.get('monsters')):
            assert zone and sum(arena.fits(Placement(s)) for s in zone) >= 12
    assert [a['name'] for a in arena_choices()][0] == 'Open Field'


def test_get_arena():
    assert get_arena(None) is None and get_arena('') is None
    assert get_arena('Open Field').width == 28
    with pytest.raises(ValueError):
        get_arena('Moon Base')


# App and storage


def test_choosing_an_arena(client):
    assert client.post('/encounter/arena', json={'arena': 'Open Field'}).get_json()['arena'] == 'Open Field'
    with client.session_transaction() as s:
        assert s['arena'] == 'Open Field'
    page = client.get('/encounter').get_data(as_text=True)
    assert '<option value="Open Field"' in page and 'selected>Open Field' in page.replace('  ', ' ')
    assert client.post('/encounter/arena', json={'arena': ''}).get_json()['arena'] is None
    with client.session_transaction() as s:
        assert 'arena' not in s


def test_unknown_arena_is_rejected(client):
    response = client.post('/encounter/arena', json={'arena': 'Moon Base'})
    assert response.status_code == 400
    with client.session_transaction() as s:
        assert 'arena' not in s


def test_simulate_and_batch_use_the_chosen_arena(client):
    client.post('/party', data={'party_id': '1', 'party_level': '1'})
    client.post('/encounter/arena', json={'arena': 'Open Field'})
    with client.session_transaction() as s:
        s['encounter_monsters'] = [{'name': 'Goblin', 'hp': 7, 'ac': 15}]
    with patch('app.simulation_controller.execute_simulation') as run:
        client.get('/simulate')
    assert run.call_args.kwargs['arena_name'] == 'Open Field'
    with patch('app.batch_simulation_controller.execute_batch_simulation', return_value=1) as batch:
        client.post('/batch/start', json={'num_runs': 10})
    assert batch.call_args.kwargs['arena_name'] == 'Open Field'


def test_arena_is_saved_with_simulations_and_batches(tmp_path):
    db = DatabaseManager(str(tmp_path / 'arena.db'))
    log = [{'type': 'action', 'actor': 'Orc', 'round': 1,
            'result': {'action': 'Greataxe', 'type': 'attack', 'target': 'Hero', 'hit': True, 'damage': 7,
                       'distance': 5, 'movement': {'from': [0, 0], 'to': [5, 0], 'feet': 25}}},
           {'type': 'action', 'actor': 'Zombie', 'round': 1,
            'result': {'action': 'Dash', 'type': 'dash', 'target': 'Hero',
                       'movement': {'from': [0, 0], 'to': [8, 0], 'feet': 40}}}]
    sim_id = db.save_simulation_result('s1', {'winner': 'party', 'arena': 'Open Field', 'log': log})
    assert db.get_simulation(sim_id)['arena'] == 'Open Field'
    texts = [entry['result'] for entry in db.get_combat_logs(sim_id)]
    assert texts == ['Moves 25 ft; hit for 7 damage (5 ft)', 'Dashes 40 ft toward Hero']
    batch_id = db.create_batch_simulation('s1', 'b', 1, 'custom', arena='Open Field')
    assert db.get_batch_simulation(batch_id)['arena'] == 'Open Field'
    assert db.get_simulation(db.save_simulation_result('s1', {'winner': 'party'}))['arena'] is None


def test_old_databases_get_the_arena_column(tmp_path):
    path = str(tmp_path / 'old.db')
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE simulations (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
                 "party_level INTEGER, encounter_type TEXT, result TEXT, rounds INTEGER DEFAULT 0, "
                 "party_hp_remaining INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    conn.close()
    DatabaseManager._initialized_paths.discard(path)
    db = DatabaseManager(path)
    assert db.get_simulation(db.save_simulation_result('s1', {'winner': 'party', 'arena': 'Open Field'}))['arena'] == 'Open Field'
