"""HTTP errors keep their status, the secret key setting, exporting a chosen simulation, and the
simulation status only saying 'done' once the result is saved."""
import os
import subprocess
import sys
import threading

import pytest

from app import app as flask_app, db, simulation_controller
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
