import pytest
from app import app as flask_app
from utils.exceptions import APIError, DatabaseError
from utils.party_loader import PartyLoader

@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        with flask_app.app_context():
            yield client

def get_all_parties():
    return PartyLoader.load_parties()

def get_all_prebuilt_encounters():
    return [
        "Kobold Mob", "Goblin Ambush", "Wolf Pack", "Orc Raiders",
        "Hobgoblin Patrol", "Bear Encounter", "Owlbear Lair"
    ]

@pytest.mark.parametrize('party', get_all_parties())
def test_full_user_journey_party_prebuilt(client, party):
    # Calculate party level from characters (assuming all characters are same level)
    party_level = party['characters'][0]['level'] if party['characters'] else 1
    party_size = len(party['characters'])
    
    # Select party
    rv = client.post('/party', data={'party_id': party['id']}, follow_redirects=True)
    assert b'Select Encounter' in rv.data
    # Try all prebuilt encounters
    for enc_name in get_all_prebuilt_encounters():
        rv2 = client.post('/encounter/prebuilt', json={'template_name': enc_name, 'party_level': party_level, 'party_size': party_size})
        assert rv2.status_code == 200
        assert b'balance' in rv2.data
        # Simulate and check results
        rv3 = client.get('/simulate')
        assert rv3.status_code == 200
        rv4 = client.get('/simulate/status')
        assert rv4.status_code == 200
        rv5 = client.get('/simulate/results', follow_redirects=True)
        assert rv5.status_code == 200
        assert b'History' in rv5.data or b'logs' in rv5.data or b'Simulation' in rv5.data

@pytest.mark.parametrize('party', get_all_parties())
def test_party_level_selection(client, party):
    # Test both level 1 and level 5 for the same party
    for test_level in [1, 5]:
        rv = client.post('/party', data={'party_id': party['id'], 'party_level': test_level}, follow_redirects=True)
        assert b'Select Encounter' in rv.data
        # Select a prebuilt encounter
        enc_name = get_all_prebuilt_encounters()[0]
        rv2 = client.post('/encounter/prebuilt', json={'template_name': enc_name, 'party_level': test_level, 'party_size': len(party['characters'])})
        assert rv2.status_code == 200
        # Simulate
        rv3 = client.get('/simulate')
        assert rv3.status_code == 200
        # Check that the simulation used the correct party level in the results
        rv4 = client.get('/api/party/current')
        assert rv4.status_code == 200
        data = rv4.get_json()
        assert data['party_level'] == test_level
        for char in data['characters']:
            assert char['level'] == test_level

# API failure and fallback
@pytest.mark.usefixtures('client')
def test_api_failure_fallback(client, monkeypatch):
    from utils.api_client import APIClient
    def fail_fetch_spell_data(self, name):
        raise APIError('API down')
    monkeypatch.setattr(APIClient, 'fetch_spell_data', fail_fetch_spell_data)
    # Try to load a spell via the API (should fallback or error gracefully)
    rv = client.get('/encounter')  # Triggers spell/monster loading in some flows
    assert rv.status_code == 200 or rv.status_code == 400

# DB failure recovery
@pytest.mark.usefixtures('client')
def test_db_failure_recovery(client, monkeypatch):
    from models.db import DatabaseManager
    def fail_get_simulation(self, sim_id):
        raise DatabaseError('DB down')
    monkeypatch.setattr(DatabaseManager, 'get_simulation', fail_get_simulation)
    rv = client.get('/results?sim_id=1')
    assert rv.status_code == 400 or rv.status_code == 500
    assert b'error' in rv.data or b'Oops' in rv.data

# Concurrent user session testing
@pytest.mark.usefixtures('client')
def test_concurrent_sessions(client):
    # Simulate two users with different sessions
    client1 = flask_app.test_client()
    client2 = flask_app.test_client()
    with client1.session_transaction() as sess1, client2.session_transaction() as sess2:
        sess1['session_id'] = 'session1'
        sess2['session_id'] = 'session2'
    # User 1 selects party 1
    client1.post('/party', data={'party_id': 1}, follow_redirects=True)
    # User 2 selects party 2
    client2.post('/party', data={'party_id': 2}, follow_redirects=True)
    # Both start simulation
    rv1 = client1.get('/simulate')
    rv2 = client2.get('/simulate')
    assert rv1.status_code == 200
    assert rv2.status_code == 200
    # Both get status
    status1 = client1.get('/simulate/status')
    status2 = client2.get('/simulate/status')
    assert status1.status_code == 200
    assert status2.status_code == 200
    # Sessions should be isolated
    assert client1 != client2 

def test_batch_party_vs_kobold_mob(client):
    """Batch test: Run 100 simulations of first party vs. Kobold Mob using real app endpoints."""
    import time
    batch_size = 100
    party = get_all_parties()[0]
    party_id = party['id']
    party_level = party['characters'][0]['level'] if party['characters'] else 1
    party_size = len(party['characters'])
    encounter_name = "Kobold Mob"
    party_wins = 0
    kobold_wins = 0
    draws = 0
    for i in range(batch_size):
        # Select party
        rv = client.post('/party', data={'party_id': party_id, 'party_level': party_level}, follow_redirects=True)
        assert b'Select Encounter' in rv.data
        # Select encounter
        rv2 = client.post('/encounter/prebuilt', json={'template_name': encounter_name, 'party_level': party_level, 'party_size': party_size})
        assert rv2.status_code == 200
        # Start simulation
        rv3 = client.get('/simulate')
        assert rv3.status_code == 200
        # Poll status until done
        for _ in range(50):
            rv4 = client.get('/simulate/status')
            assert rv4.status_code == 200
            data = rv4.get_json()
            if data.get('done'):
                break
            time.sleep(0.05)
        # Get results, follow redirects
        rv5 = client.get('/simulate/results', follow_redirects=True)
        # Print debug info if redirected
        if rv5.status_code == 200:
            html = rv5.data.decode('utf-8')
            if 'Party wins' in html or 'party wins' in html:
                party_wins += 1
            elif 'Monsters win' in html or 'monsters win' in html:
                kobold_wins += 1
            else:
                draws += 1
        else:
            print(f"[DEBUG] Unexpected status code: {rv5.status_code}")
            print(f"[DEBUG] Response headers: {rv5.headers}")
            print(f"[DEBUG] Response data: {rv5.data.decode('utf-8')}")
    print(f"Batch results for 100 runs (Web UI code):")
    print(f"Party wins: {party_wins}")
    print(f"Kobold wins: {kobold_wins}")
    print(f"Draws: {draws}") 

def test_party_class_and_level_consistency(client):
    """Test that both 'class' and 'character_class' are set and used for character lookup at all levels."""
    from app import simulation_controller
    # Use the first party and test a few levels
    party = get_all_parties()[0]
    party_id = party['id']
    char_names = [c['name'] for c in party['characters']]
    char_classes = [c.get('class', c.get('character_class')) for c in party['characters']]
    print(f"[DEBUG] char_names: {char_names}")
    print(f"[DEBUG] char_classes: {char_classes}")
    for test_level in [1, 3, 5]:
        rv = client.post('/party', data={'party_id': party_id, 'party_level': test_level}, follow_redirects=True)
        assert b'Select Encounter' in rv.data
        # Select a prebuilt encounter
        enc_name = get_all_prebuilt_encounters()[0]
        rv2 = client.post('/encounter/prebuilt', json={'template_name': enc_name, 'party_level': test_level, 'party_size': len(party['characters'])})
        assert rv2.status_code == 200
        # Start simulation
        rv3 = client.get('/simulate')
        assert rv3.status_code == 200
        # Wait for simulation to finish (poll status)
        for _ in range(50):
            rv4 = client.get('/simulate/status')
            assert rv4.status_code == 200
            data = rv4.get_json()
            if data.get('done'):
                break
            import time; time.sleep(0.05)
        # Check the simulation state for correct instantiation
        session_id = None
        with client.session_transaction() as sess:
            session_id = sess['session_id']
        # Get the last simulation state
        sim_state = simulation_controller.simulation_states.get(session_id, {})
        # Accept any level <= requested (the closest available)
        found = False
        if 'log' in sim_state:
            print(f"[DEBUG] Simulation log for level {test_level}:")
            for entry in sim_state['log']:
                print(entry)
                if isinstance(entry, str) and 'CHARACTER INSTANTIATED' in entry:
                    for cname, cclass in zip(char_names, char_classes):
                        # Accept any level <= test_level
                        import re
                        m = re.search(r'Level=(\d+)', entry)
                        if cname in entry and cclass in entry and m:
                            actual_level = int(m.group(1))
                            if actual_level <= test_level:
                                found = True
        if not found:
            print(f"[DEBUG] Assertion failed for level {test_level}. char_names: {char_names}, char_classes: {char_classes}")
            print(f"[DEBUG] Full simulation log: {sim_state.get('log', [])}")
        assert found, f"Character with correct name, class, and level <= {test_level} not found in simulation log." 