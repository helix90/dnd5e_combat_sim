"""Limits for a public server: batches running at once, per visitor and in all, and rate limits
on the routes that start work."""

import threading
import time
from unittest.mock import patch

import pytest

from controllers.batch_simulation_controller import (
    MAX_RUNNING_BATCHES,
    MAX_RUNNING_BATCHES_PER_USER,
)
from models.combat import Combat
from tests.helpers import session_id


@pytest.fixture
def ready_client(client):
    """A client with a party and an encounter chosen, so it can start batches."""
    client.post("/party", data={"party_id": "1", "party_level": "1"})
    client.post(
        "/encounter/prebuilt",
        json={"template_name": "Goblin Ambush", "party_level": 1, "party_size": 4},
    )
    return client


@pytest.fixture
def controller():
    from app import batch_simulation_controller

    yield batch_simulation_controller
    batch_simulation_controller.running.clear()


def start(client, runs=2):
    return client.post("/batch/start", json={"num_runs": runs})


def wait_for(client, batch_id):
    deadline = time.time() + 60
    while not client.get(f"/batch/progress/{batch_id}").get_json().get("done"):
        assert time.time() < deadline, "batch did not finish"
        time.sleep(0.05)


def test_a_visitor_can_only_run_so_many_batches_at_once(ready_client, controller):
    controller.running[session_id(ready_client)] = MAX_RUNNING_BATCHES_PER_USER
    response = start(ready_client)
    assert response.status_code == 429
    assert "You already have 2 batches running" in response.get_json()["error"]


def test_the_server_only_runs_so_many_batches_at_once(ready_client, controller):
    for visitor in range(MAX_RUNNING_BATCHES):
        controller.running[f"visitor {visitor}"] = 1
    response = start(ready_client)
    assert response.status_code == 429
    assert "The server is busy" in response.get_json()["error"]


def test_a_finished_batch_frees_its_place(ready_client, controller):
    owner = session_id(ready_client)
    release = threading.Event()
    real_run = Combat.run

    def held_run(self):
        release.wait(30)
        return real_run(self)

    with patch("models.combat.Combat.run", held_run):
        first = start(ready_client).get_json()["batch_id"]
        start(ready_client)
        assert controller.running[owner] == 2
        assert start(ready_client).status_code == 429
        release.set()
        wait_for(ready_client, first)
    deadline = time.time() + 30
    while controller.running[owner]:
        assert time.time() < deadline, "the batches' places weren't freed"
        time.sleep(0.05)
    response = start(ready_client)
    assert response.status_code == 200
    wait_for(ready_client, response.get_json()["batch_id"])


def test_a_batch_that_fails_to_start_frees_its_place(ready_client, controller):
    with patch.object(
        controller.db, "create_batch_simulation", side_effect=RuntimeError("disk full")
    ):
        assert start(ready_client).status_code == 500
    assert not controller.running


def test_starting_batches_is_rate_limited(client):
    # Not even valid, but each try counts
    for _ in range(10):
        assert client.post("/batch/start", json={"num_runs": 0}).status_code == 400
    response = client.post("/batch/start", json={"num_runs": 0})
    assert response.status_code == 429
    assert response.get_json() == {
        "error": "Too many requests: the limit is 10 per 1 minute. Wait a little and try again."
    }


def test_starting_fights_is_rate_limited_with_a_page_that_says_so(client):
    for _ in range(10):
        assert client.get("/simulate").status_code in (200, 302)
    response = client.get("/simulate")
    assert response.status_code == 429
    assert "Too many requests: the limit is 10 per 1 minute." in response.get_data(
        as_text=True
    )


def test_reading_pages_and_polling_progress_is_not_held_to_those_limits(ready_client):
    for _ in range(40):
        assert ready_client.get("/batch").status_code == 200
        assert ready_client.get("/simulate/status").status_code == 200
