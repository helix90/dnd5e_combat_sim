"""HTTP errors keep their status, the secret key setting, exporting a chosen simulation, the
simulation status only saying 'done' once the result is saved, and the batch routes' checks."""
import os
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from app import app as flask_app, batch_simulation_controller, db, simulation_controller
from models.character import Character
from models.monster import Monster
from models.actions import AttackAction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES = {'str': 14, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10}


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        client.get('/')  # starts a session
        yield client


def session_id(client):
    with client.session_transaction() as s:
        return s['session_id']


def saved(owner, winner):
    return db.save_simulation_result(owner, {'winner': winner, 'rounds': 3, 'party_hp_remaining': 7, 'log': []})


# HTTP errors


def test_unknown_pages_are_404(client):
    assert client.get('/no-such-page').status_code == 404


def test_wrong_method_is_405(client):
    assert client.post('/').status_code == 405


def test_unexpected_errors_are_still_500(client, monkeypatch):
    monkeypatch.setattr('app.render_template', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    response = client.get('/', headers={'Accept': 'application/json'})
    assert response.status_code == 500 and response.get_json()['type'] == 'RuntimeError'


# Secret key


@pytest.mark.parametrize('variable', ['SECRET_KEY', 'FLASK_SECRET_KEY'])
def test_the_secret_key_comes_from_either_variable(variable):
    env = {k: v for k, v in os.environ.items() if k not in ('SECRET_KEY', 'FLASK_SECRET_KEY')}
    env[variable] = 'not-the-default'
    out = subprocess.run([sys.executable, '-c', 'from app import app; print(app.secret_key)'], cwd=ROOT,
                         env=env, capture_output=True, text=True, check=True).stdout
    assert out.strip().splitlines()[-1] == 'not-the-default'


# Export


def test_export_gives_the_chosen_simulation(client):
    owner = session_id(client)
    first, second = saved(owner, 'party'), saved(owner, 'monsters')
    assert client.get(f'/results/export?sim_id={first}').get_json()['simulation']['win_loss'] == 'party'
    assert client.get(f'/results/export?sim_id={second}').get_json()['simulation']['win_loss'] == 'monsters'


def test_export_without_an_id_gives_the_latest(client):
    owner = session_id(client)
    saved(owner, 'party')
    latest = saved(owner, 'monsters')
    assert client.get('/results/export').get_json()['simulation']['id'] == latest


def test_export_refuses_another_sessions_simulation(client):
    other = saved('someone-else', 'party')
    assert client.get(f'/results/export?sim_id={other}').status_code == 404


# Simulation status


def test_status_is_only_done_once_the_result_is_saved(client):
    owner = session_id(client)
    seen = []
    real_save = simulation_controller.db.save_simulation_result

    def save_and_peek(sid, result):
        # Combat has finished and reported its last progress: the page mustn't see 'done' yet
        seen.append(dict(simulation_controller.simulation_states[sid]))
        return real_save(sid, result)

    hero = Character('Hero', 5, 'Fighter', 'Human', SCORES, hp=200, ac=18, proficiency_bonus=3,
                     actions=[AttackAction('Longsword', '', 'Longsword', '1d8+20', 'slashing', hit_bonus=20)])
    goblin = Monster('Goblin', '1/4', 7, 10, SCORES, actions=[AttackAction('Scimitar', '', 'Scimitar', '1d6', 'slashing')])
    simulation_controller.db.save_simulation_result = save_and_peek
    try:
        simulation_controller.execute_simulation([hero], [goblin], owner, party_level=5)
        finished = threading.Event()
        for _ in range(300):
            if simulation_controller.simulation_states[owner].get('done'):
                break
            finished.wait(0.1)
    finally:
        del simulation_controller.db.save_simulation_result  # back to the class's method
    assert seen and not seen[0].get('done')
    state = simulation_controller.simulation_states[owner]
    assert state['done'] and state['simulation_id'] and not state.get('error')


# Batches


@pytest.fixture
def ready(client):
    """A client with a party and an encounter chosen, ready to start a batch."""
    client.post('/party', data={'party_id': '1', 'party_level': '5'})
    client.post('/encounter/custom', json={'monsters': [{'name': 'Goblin', 'cr': '1/4', 'hp': 7, 'ac': 15}],
                                           'party_level': 5, 'party_size': 4})
    return client


def start(client, **data):
    return client.post('/batch/start', json={'num_runs': 10, **data})


def test_batch_names_can_have_apostrophes(ready):
    with patch('app.batch_simulation_controller.execute_batch_simulation', return_value=1) as batch:
        assert start(ready, batch_name="Wolf's test").status_code == 200
    assert batch.call_args.args[3] == "Wolf's test"


def test_batch_names_still_reject_markup(ready):
    assert start(ready, batch_name='<b>bold</b>').status_code == 400


def test_a_run_count_that_isnt_a_number_is_a_400(ready):
    response = start(ready, num_runs='lots')
    assert response.status_code == 400 and 'whole number' in response.get_json()['error']


def test_the_controllers_input_checks_are_400s(ready):
    with patch('app.batch_simulation_controller.execute_batch_simulation', side_effect=ValueError('Unknown map')):
        response = start(ready)
    assert response.status_code == 400 and response.get_json()['error'] == 'Unknown map'


def test_server_errors_starting_a_batch_are_500s_without_the_details(ready):
    with patch('app.batch_simulation_controller.execute_batch_simulation',
               side_effect=RuntimeError('disk I/O error at /secret/path')):
        response = start(ready)
    assert response.status_code == 500
    assert 'secret' not in response.get_json()['error']


def test_batch_progress_is_404_for_another_sessions_batch(client):
    other = db.create_batch_simulation('someone-else', 'theirs', 5, 'custom')
    assert client.get(f'/batch/progress/{other}').status_code == 404


def test_batch_progress_is_404_for_an_unknown_batch(client):
    assert client.get('/batch/progress/999999999').status_code == 404


def test_progress_of_a_batch_cut_off_by_a_restart_says_so(client):
    # Saved in the database, but no longer in the controller's memory
    batch_id = db.create_batch_simulation(session_id(client), 'mine', 5, 'custom')
    progress = client.get(f'/batch/progress/{batch_id}').get_json()
    assert progress['done'] and 'restarted' in progress['error']


def test_progress_of_a_batch_finished_before_a_restart_has_its_totals(client):
    batch_id = db.create_batch_simulation(session_id(client), 'mine', 5, 'custom')
    db.update_batch_statistics(batch_id, 10, 7, 3, 4.5, 20.0)
    progress = client.get(f'/batch/progress/{batch_id}').get_json()
    assert progress['done'] and not progress['error']
    assert (progress['completed_runs'], progress['party_wins'], progress['monster_wins']) == (10, 7, 3)


def test_progress_of_a_running_batch_comes_from_the_controller(client):
    batch_id = db.create_batch_simulation(session_id(client), 'mine', 5, 'custom')
    batch_simulation_controller.batch_states[batch_id] = {'progress': 40, 'completed_runs': 4, 'total_runs': 10,
                                                          'done': False, 'error': None}
    try:
        progress = client.get(f'/batch/progress/{batch_id}').get_json()
    finally:
        del batch_simulation_controller.batch_states[batch_id]
    assert progress['completed_runs'] == 4 and not progress['done']
