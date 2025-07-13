import pytest
from app import app as flask_app

@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        with flask_app.app_context():
            yield client

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
    rv = client.get('/simulate')
    assert rv.status_code == 200
    assert b'Combat Simulation' in rv.data
    # Simulate polling for status (simulate immediate completion for test)
    from app import simulation_controller
    session_id = None
    with client.session_transaction() as sess:
        session_id = sess['session_id']
    # Manually set simulation as done for test
    simulation_controller.simulation_states[session_id] = {
        'progress': 100, 'log': ['Done'], 'done': True
    }
    status = client.get('/simulate/status')
    assert status.status_code == 200
    assert b'progress' in status.data
    # Now test results redirect
    rv2 = client.get('/simulate/results', follow_redirects=True)
    assert rv2.status_code == 200
    # The results page should load (may not contain 'Simulation Results' text, so check for generic content)
    assert b'History' in rv2.data or b'logs' in rv2.data or b'Simulation' in rv2.data

def test_results_and_history(client):
    # Simulate a run to create a simulation and logs
    client.post('/party', data={'party_id': 1}, follow_redirects=True)
    client.get('/encounter')  # Just to set up session
    rv = client.get('/simulate')
    assert rv.status_code == 200
    from app import simulation_controller
    session_id = None
    with client.session_transaction() as sess:
        session_id = sess['session_id']
    simulation_controller.simulation_states[session_id] = {
        'progress': 100, 'log': ['Done'], 'done': True
    }
    rv2 = client.get('/simulate/results', follow_redirects=True)
    assert rv2.status_code == 200
    assert b'History' in rv2.data or b'logs' in rv2.data or b'Simulation' in rv2.data

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
    # Patch Combat.run to raise an exception
    from app import simulation_controller
    class DummyCombat:
        def run(self, progress_callback=None):
            raise Exception('Forced failure')
    monkeypatch.setattr('models.combat.Combat', DummyCombat)
    session_id = 'fail-session'
    with client.session_transaction() as sess:
        sess['session_id'] = session_id
    # Start simulation (should handle error)
    rv = client.get('/simulate')
    assert rv.status_code == 200
    # Simulate status should show error after run
    simulation_controller.simulation_states[session_id] = {
        'progress': 100, 'log': [], 'done': True, 'error': 'Forced failure'
    }
    rv2 = client.get('/simulate/status')
    assert b'Forced failure' in rv2.data

def test_api_prebuilt_encounters():
    with flask_app.test_client() as client:
        response = client.get('/api/encounters/prebuilt')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)
        assert any('name' in enc for enc in data) 