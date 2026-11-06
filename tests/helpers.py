"""Helpers for tests that drive the app through its pages."""
import time

import pytest


def session_id(client) -> str:
    with client.session_transaction() as s:
        return s['session_id']


def run_simulation(client, timeout: float = 30) -> dict:
    """Start a fight of the session's party and encounter, wait for it to be saved, and return the
    finished status (with its simulation_id)."""
    assert client.get('/simulate').status_code == 200
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get('/simulate/status').get_json()
        if status.get('done'):
            assert not status.get('error'), status['error']
            assert status.get('simulation_id'), status
            return status
        time.sleep(0.01)
    pytest.fail(f'simulation did not finish within {timeout}s')


def results_page(client) -> str:
    """The results page /simulate/results sends the browser to."""
    rv = client.get('/simulate/results', follow_redirects=True)
    assert rv.status_code == 200
    return rv.get_data(as_text=True)


def shows_simulation(page: str, sim_id: int) -> bool:
    return f'<strong>Simulation ID:</strong> {sim_id}' in page
