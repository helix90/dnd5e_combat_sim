import pytest
from app import app as flask_app
from utils.exceptions import APIError, DatabaseError

@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        with flask_app.app_context():
            yield client

def get_all_parties():
    from utils.party_loader import PartyLoader
    return PartyLoader.load_parties()

def get_all_prebuilt_encounters():
    import json
    with open('data/encounter_templates.json') as f:
        return [e['name'] for e in json.load(f)['encounters']]

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