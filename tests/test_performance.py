import os
import time
import pytest
from app import app as flask_app

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

@pytest.mark.skipif(not os.environ.get('BENCHMARK'), reason="Skip performance benchmarks unless BENCHMARK env var is set.")
def test_combat_simulation_benchmarks(client):
    """
    Run combat simulations for all party and encounter combinations and measure timing.
    """
    timings = []
    parties = get_all_parties()
    encounters = get_all_prebuilt_encounters()
    for party in parties:
        party_level = party['characters'][0]['level'] if party['characters'] else 1
        party_size = len(party['characters'])
        # Select party
        client.post('/party', data={'party_id': party['id']}, follow_redirects=True)
        for enc_name in encounters:
            # Select encounter
            client.post('/encounter/prebuilt', json={'template_name': enc_name, 'party_level': party_level, 'party_size': party_size})
            # Time the simulation
            start = time.time()
            rv = client.get('/simulate')
            assert rv.status_code == 200
            # Wait for simulation to finish (poll status)
            for _ in range(30):
                status = client.get('/simulate/status')
                if b'complete' in status.data or b'finished' in status.data:
                    break
                time.sleep(0.2)
            end = time.time()
            elapsed = end - start
            timings.append(elapsed)
            print(f"Party: {party['name']}, Encounter: {enc_name}, Time: {elapsed:.2f}s")
    if timings:
        print(f"\nCombat Simulation Benchmark Results:")
        print(f"Runs: {len(timings)}")
        print(f"Min: {min(timings):.2f}s, Max: {max(timings):.2f}s, Avg: {sum(timings)/len(timings):.2f}s")

@pytest.mark.skipif(not os.environ.get('BENCHMARK'), reason="Skip performance benchmarks unless BENCHMARK env var is set.")
def test_endpoint_response_times(client):
    """
    Measure response times for key API endpoints.
    """
    endpoints = {
        '/': 'Home page',
        '/party': 'Party selection page',
        '/encounter': 'Encounter selection page',
        '/api/monsters': 'Monster API',
        '/api/monsters?cr=1/4': 'Monster API with CR filter',
        '/history': 'Simulation history page'
    }
    
    # Test each endpoint multiple times
    results = {}
    num_runs = 10
    
    for endpoint, description in endpoints.items():
        timings = []
        for _ in range(num_runs):
            start = time.time()
            rv = client.get(endpoint)
            end = time.time()
            elapsed = (end - start) * 1000  # Convert to milliseconds
            timings.append(elapsed)
            assert rv.status_code in [200, 302]  # Allow redirects
        
        results[endpoint] = {
            'description': description,
            'min': min(timings),
            'max': max(timings),
            'avg': sum(timings) / len(timings),
            'status_code': rv.status_code
        }
    
    # Test POST endpoints with sample data
    post_endpoints = {
        '/party': {'data': {'party_id': 1}},
        '/encounter/prebuilt': {'json': {'template_name': 'Kobold Mob', 'party_level': 5, 'party_size': 4}},
        '/encounter/custom': {'json': {'monsters': [{'name': 'Goblin', 'hp': 7, 'ac': 15, 'cr': '1/4'}], 'party_level': 5, 'party_size': 4}},
        '/api/encounter/balance': {'json': {'monsters': [{'name': 'Goblin', 'hp': 7, 'ac': 15, 'cr': '1/4'}], 'party_level': 5, 'party_size': 4}}
    }
    
    for endpoint, request_data in post_endpoints.items():
        timings = []
        for _ in range(num_runs):
            start = time.time()
            if 'data' in request_data:
                rv = client.post(endpoint, data=request_data['data'], follow_redirects=True)
            else:
                rv = client.post(endpoint, json=request_data['json'])
            end = time.time()
            elapsed = (end - start) * 1000  # Convert to milliseconds
            timings.append(elapsed)
            assert rv.status_code in [200, 302]  # Allow redirects
        
        results[endpoint] = {
            'description': f'POST {endpoint}',
            'min': min(timings),
            'max': max(timings),
            'avg': sum(timings) / len(timings),
            'status_code': rv.status_code
        }
    
    # Print results
    print(f"\nEndpoint Response Time Results ({num_runs} runs each):")
    print("-" * 80)
    print(f"{'Endpoint':<30} {'Description':<25} {'Min(ms)':<8} {'Max(ms)':<8} {'Avg(ms)':<8}")
    print("-" * 80)
    
    for endpoint, data in results.items():
        print(f"{endpoint:<30} {data['description']:<25} {data['min']:<8.1f} {data['max']:<8.1f} {data['avg']:<8.1f}")
    
    # Check for performance issues
    slow_endpoints = []
    for endpoint, data in results.items():
        if data['avg'] > 1000:  # Flag endpoints taking more than 1 second on average
            slow_endpoints.append((endpoint, data['avg']))
    
    if slow_endpoints:
        print(f"\n⚠️  Slow endpoints detected (>1s average):")
        for endpoint, avg_time in slow_endpoints:
            print(f"   {endpoint}: {avg_time:.1f}ms")
    else:
        print(f"\n✅ All endpoints performing well (<1s average)") 