import time

from tests.helpers import results_page, run_simulation, session_id, shows_simulation


def test_index_route(client):
    rv = client.get('/')
    assert rv.status_code == 200
    assert b'Combat Simulator' in rv.data

def test_party_route(client):
    rv = client.get('/party')
    assert rv.status_code == 200
    assert b'Select Your Party' in rv.data
    rv2 = client.post('/party', data={'party_id': 1}, follow_redirects=True)
    assert b'Select Encounter' in rv2.data

def test_encounter_route(client):
    rv = client.get('/encounter')
    assert rv.status_code == 200
    assert b'Select Encounter' in rv.data
    # Simulate a custom encounter POST (now /encounter/custom)
    rv2 = client.post('/encounter/custom', json={
        'monsters': [{'name': 'Goblin', 'hp': 7, 'ac': 13, 'cr': '1/4', 'ability_scores': {'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}}],
        'party_level': 3,
        'party_size': 4
    })
    assert rv2.status_code == 200
    assert b'balance' in rv2.data

def test_simulate_route(client):
    client.post('/party', data={'party_id': 1, 'party_level': 3}, follow_redirects=True)
    client.post('/encounter/prebuilt', json={'template_name': 'Goblin Ambush', 'party_level': 3, 'party_size': 4})
    assert b'Combat Simulation' in client.get('/simulate').data
    status = run_simulation(client)
    assert status['progress'] == 100
    page = results_page(client)
    assert shows_simulation(page, status['simulation_id']) and 'Show Detailed Combat Log' in page
    # The finished fight is listed in the history
    assert f"sim_id={status['simulation_id']}" in client.get('/history').get_data(as_text=True)


def test_simulation_progress_endpoint(client, monkeypatch):
    # Simulate a running simulation state
    from app import simulation_controller
    session_id = 'test-session'
    simulation_controller.simulation_states[session_id] = {
        'progress': 50, 'log': ['Test log'], 'done': False
    }
    with client.session_transaction() as sess:
        sess['session_id'] = session_id
    rv = client.get('/simulate/status')
    assert rv.status_code == 200
    assert b'progress' in rv.data
    assert b'Test log' in rv.data

def test_simulation_error_handling(client, monkeypatch):
    # Simulate an error in the simulation state
    from app import simulation_controller
    session_id = 'error-session'
    simulation_controller.simulation_states[session_id] = {
        'progress': 0, 'log': [], 'done': True, 'error': 'Sim error!'
    }
    with client.session_transaction() as sess:
        sess['session_id'] = session_id
    rv = client.get('/simulate/status')
    assert rv.status_code == 200
    assert b'Sim error!' in rv.data

def test_simulation_execution_failure(client, monkeypatch):
    class FailingCombat:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, progress_callback=None):
            raise RuntimeError('Forced failure')
    monkeypatch.setattr('controllers.simulation_controller.Combat', FailingCombat)
    client.post('/party', data={'party_id': 1, 'party_level': 3}, follow_redirects=True)
    client.post('/encounter/prebuilt', json={'template_name': 'Goblin Ambush', 'party_level': 3, 'party_size': 4})
    assert client.get('/simulate').status_code == 200
    deadline = time.time() + 10
    while not (status := client.get('/simulate/status').get_json())['done']:
        assert time.time() < deadline
        time.sleep(0.01)
    assert status['error'] == 'Forced failure'


def test_api_prebuilt_encounters(client):
    response = client.get('/api/encounters/prebuilt')
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) >= 48 and all('name' in enc and 'level' in enc for enc in data)


def test_results_rejects_other_sessions_simulation(client):
    from app import db
    other_sim = db.save_simulation('someone-else', 3, 'goblin', 'win', 4, 12)
    rv = client.get(f'/results?sim_id={other_sim}')
    assert rv.status_code == 404
    assert b'No simulation found' in rv.data


def test_results_allows_own_simulation(client):
    from app import db
    client.get('/')  # establishes session_id
    own_sim = db.save_simulation(session_id(client), 3, 'goblin', 'win', 4, 12)
    rv = client.get(f'/results?sim_id={own_sim}')
    assert rv.status_code == 200 and shows_simulation(rv.get_data(as_text=True), own_sim)


def test_batch_results_rejects_other_sessions_batch(client):
    from app import db
    other_batch = db.create_batch_simulation('someone-else', 'b', 3, 'goblin')
    rv = client.get(f'/batch/results/{other_batch}')
    assert rv.status_code == 404
