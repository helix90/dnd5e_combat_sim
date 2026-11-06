"""Arena phase 6: the battle-map replay and comparing a batch with and without its arena."""
import copy
import json
from unittest.mock import patch


from controllers.batch_simulation_controller import BatchSimulationController
from models.actions import AttackAction
from models.arena import Arena, Placement
from models.arena_library import get_arena
from models.character import Character
from models.combat import Combat
from models.db import DatabaseManager
from models.monster import Monster
from utils.party_loader import PartyLoader
from utils.paths import data_path

SCORES = {'str': 14, 'dex': 14, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}


def sword():
    return AttackAction('Longsword', '', 'Longsword', '1d8+2', 'slashing', hit_bonus=5)


def hero(name='Hero', hp=30):
    return Character(name, 1, 'Fighter', 'Human', SCORES, hp=hp, ac=12, proficiency_bonus=2, actions=[sword()])


def monster(name='Orc', hp=15):
    return Monster(name, '1/2', hp, 13, SCORES, actions=[sword()])


def put(combat, creature, x, y):
    combat.battlefield.placements[creature] = Placement((x, y), combat.battlefield.placements[creature].size)


def goblins(count=2):
    goblin = next(m for m in json.load(open(data_path('monsters.json')))['monsters'] if m['name'] == 'Goblin')
    return [dict(copy.deepcopy(goblin), name=f"Goblin {i + 1}") for i in range(count)]


def action_entries(log):
    return [e for e in log if e['type'] == 'action']


# Recording


def test_a_fight_on_an_arena_records_a_frame_for_every_action():
    combat = Combat([hero('Aldric'), hero('Dax'), monster('Orc 1'), monster('Orc 2')],
                    arena=get_arena('Open Field'))
    result = combat.run()
    replay = result['replay']
    assert len(replay['frames']) == len(action_entries(result['log']))
    assert replay['arena']['name'] == 'Open Field' and replay['arena']['width'] == 28
    assert {c['name']: c['side'] for c in replay['creatures']} == {
        'Aldric': 'party', 'Dax': 'party', 'Orc 1': 'monsters', 'Orc 2': 'monsters'}
    assert replay['start']['positions'] == result['start_positions']
    assert replay['start']['hp'] == {'Aldric': 30, 'Dax': 30, 'Orc 1': 15, 'Orc 2': 15}
    for frame, entry in zip(replay['frames'], action_entries(result['log'])):
        assert frame['actor'] == entry['actor'] and frame['round'] == entry['round']
    # The replay is plain data, ready to store
    json.dumps(replay)


def test_frames_show_moves_positions_and_hit_points():
    mover, orc = hero(), monster()
    combat = Combat([mover, orc], arena=Arena(20, 10, name='Test'))
    put(combat, mover, 5, 5)
    put(combat, orc, 6, 5)
    with patch('random.randint', return_value=8):
        result = combat._take_turn(mover, {'type': 'defend', 'move_to': (2, 5)})
    combat.logger.log_action(mover, result, 1)
    opportunity, turn = combat.frames
    # The orc's opportunity attack is drawn with the hero still next to it
    assert opportunity['actor'] == 'Orc' and opportunity['positions']['Hero'] == [5, 5]
    assert opportunity['hp']['Hero'] == 20 and opportunity['targets'] == ['Hero']
    assert turn['actor'] == 'Hero' and turn['positions']['Hero'] == [2, 5]
    assert turn['moves'] == [[[5, 5], [2, 5]]]


def test_frames_show_the_squares_of_an_area_effect():
    breath = AttackAction('Fire Breath', '', 'Fire Breath', '4d6', 'fire', save_dc=13, save_type='dex',
                          area_effect=True, area={'shape': 'cone', 'size': 15})
    dragon = Monster('Dragon', '2', 40, 15, SCORES, actions=[breath])
    target = hero()
    combat = Combat([target, dragon], arena=Arena(20, 10, name='Test'))
    put(combat, dragon, 5, 5)
    put(combat, target, 7, 5)
    result = combat._take_turn(dragon, {'type': 'attack', 'action': breath, 'target': [target]})
    combat.logger.log_action(dragon, result, 1)
    [frame] = combat.frames
    assert [7, 5] in frame['area'] and [5, 5] not in frame['area']


def test_no_replay_without_an_arena():
    result = Combat([hero(), monster()]).run()
    assert 'replay' not in result


def test_drawing_keeps_the_terrain_kinds():
    drawing = get_arena('Ruins').drawing()
    kinds = {kind for _, _, kind, _, _, _ in drawing['terrain']}
    assert kinds and '' not in kinds
    x, y, kind, impassable, difficult, cover = drawing['terrain'][0]
    assert isinstance(x, int) and impassable in (0, 1) and difficult in (0, 1)


# Storage and the results page


def test_replay_is_stored_compressed_and_lines_up_with_the_log(tmp_path):
    db = DatabaseManager(str(tmp_path / 'replay.db'))
    result = Combat([hero('Aldric'), monster('Orc 1'), monster('Orc 2')], arena=get_arena('Open Field')).run()
    sim_id = db.save_simulation_result('s1', result)
    assert 'replay' not in db.get_simulation(sim_id)
    replay = db.get_replay(sim_id)
    assert replay == json.loads(json.dumps(result['replay']))
    assert len(db.get_combat_logs(sim_id)) == len(replay['frames'])
    assert db.get_replay(db.save_simulation_result('s1', Combat([hero(), monster()]).run())) is None


def test_results_page_shows_the_battle_map(client, tmp_path):
    test_db = DatabaseManager(str(tmp_path / 'page.db'))
    client.get('/')
    with client.session_transaction() as s:
        session_id = s['session_id']
    with patch('app.db', test_db), patch('app.results_controller.db', test_db):
        result = Combat([hero('Aldric'), monster('Orc 1')], arena=get_arena('Open Field')).run()
        sim_id = test_db.save_simulation_result(session_id, result)
        page = client.get(f'/results?sim_id={sim_id}').get_data(as_text=True)
        assert 'Battle Map: Open Field' in page and 'id="replayData"' in page and 'replaySlider' in page
        plain = test_db.save_simulation_result(session_id, Combat([hero(), monster()]).run())
        assert 'Battle Map' not in client.get(f'/results?sim_id={plain}').get_data(as_text=True)


# Batches with and without the arena


def run_batch(tmp_path, compare):
    controller = BatchSimulationController()
    controller.db = DatabaseManager(str(tmp_path / 'batch.db'))
    party = PartyLoader.get_party_with_level(1, 1)['characters']
    batch_id = controller.execute_batch_simulation(party, goblins(), 3, 'Goblins', 's1', arena_name='Open Field',
                                                   compare_without_arena=compare)
    controller.batch_threads[batch_id].join(timeout=60)
    return controller, batch_id


def test_batch_compares_with_a_run_without_the_arena(tmp_path):
    controller, batch_id = run_batch(tmp_path, compare=True)
    progress = controller.get_batch_progress(batch_id)
    assert progress['done'] and progress['progress'] == 100
    assert progress['baseline']['completed_runs'] == 3
    results = controller.get_batch_results(batch_id)
    comparison = results['comparison']
    baseline = controller.db.get_batch_simulation(comparison['baseline_batch_id'])
    assert baseline['arena'] is None and baseline['total_runs'] == 3 and baseline['batch_name'] == 'Goblins (no arena)'
    assert results['batch']['total_runs'] == 3 and comparison['arena'] == 'Open Field'
    win_rate = next(row for row in comparison['rows'] if row['key'] == 'win_rate')
    assert win_rate['with_arena'] == results['statistics']['win_rate']
    assert win_rate['difference'] == round(win_rate['with_arena'] - win_rate['without_arena'], 2)
    # The baseline's page shows the same comparison
    assert controller.get_batch_results(baseline['id'])['comparison']['arena_batch_id'] == batch_id


def test_batch_without_comparison_has_none(tmp_path):
    controller, batch_id = run_batch(tmp_path, compare=False)
    assert controller.get_batch_results(batch_id)['comparison'] is None
    assert 'baseline' not in controller.get_batch_progress(batch_id)


def test_batch_page_offers_the_comparison_only_with_an_arena(client):
    with client.session_transaction() as s:
        s['arena'] = 'Open Field'
    page = client.get('/batch').get_data(as_text=True)
    assert 'id="compareWithoutArena"' in page and 'mb-3 d-none" id="compareWithoutArenaGroup"' not in page
    with client.session_transaction() as s:
        s.pop('arena', None)
    assert 'mb-3 d-none" id="compareWithoutArenaGroup"' in client.get('/batch').get_data(as_text=True)
    with client.session_transaction() as s:
        s['arena'] = 'Open Field'
        s['encounter_monsters'] = goblins(1)
    client.post('/party', data={'party_id': '1', 'party_level': '1'})
    with patch('app.batch_simulation_controller.execute_batch_simulation', return_value=1) as batch:
        client.post('/batch/start', json={'num_runs': 10, 'compare_without_arena': True})
    assert batch.call_args.kwargs['compare_without_arena'] is True
