"""End-to-end: choosing a party and an encounter, fighting it, and reading the results, through
the app's pages as a browser would."""

import json
import time

import pytest

from app import db
from tests.helpers import results_page, run_simulation, session_id, shows_simulation
from utils.exceptions import DatabaseError
from utils.paths import data_path
from utils.party_loader import PartyLoader

PARTIES = PartyLoader.load_parties()
with open(data_path("encounter_templates.json")) as f:
    TEMPLATES = json.load(f)["encounters"]


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t["name"])
def test_every_prebuilt_encounter_can_be_fought_and_read(client, template):
    """Every prebuilt encounter is fought at its own level, by each party in turn, and the results
    page shows that fight."""
    party = PARTIES[TEMPLATES.index(template) % len(PARTIES)]
    level = template["level"]
    rv = client.post(
        "/party",
        data={"party_id": party["id"], "party_level": level},
        follow_redirects=True,
    )
    assert b"Select Encounter" in rv.data
    rv = client.post(
        "/encounter/prebuilt",
        json={
            "template_name": template["name"],
            "party_level": level,
            "party_size": len(party["characters"]),
        },
    )
    assert rv.status_code == 200 and b"balance" in rv.data
    status = run_simulation(client)
    assert shows_simulation(results_page(client), status["simulation_id"])
    assert db.get_simulation(status["simulation_id"])["result"] in ("party", "monsters")


@pytest.mark.parametrize("party", PARTIES, ids=lambda p: p["name"])
@pytest.mark.parametrize("level", [1, 5])
def test_party_level_selection(client, party, level):
    rv = client.post(
        "/party",
        data={"party_id": party["id"], "party_level": level},
        follow_redirects=True,
    )
    assert b"Select Encounter" in rv.data
    data = client.get("/api/party/current").get_json()
    assert data["party_level"] == level
    assert data["characters"] and all(c["level"] == level for c in data["characters"])


def test_a_database_failure_shows_the_error_page(client, monkeypatch):
    def fail_get_simulation(self, sim_id):
        raise DatabaseError("DB down")

    monkeypatch.setattr(type(db), "get_simulation", fail_get_simulation)
    rv = client.get("/results?sim_id=1")
    assert rv.status_code == 400
    assert b"DB down" in rv.data


def test_two_users_see_only_their_own_results(client):
    from app import app as flask_app

    other = flask_app.test_client()
    sims = {}
    for user, party_id in ((client, 1), (other, 2)):
        user.post(
            "/party",
            data={"party_id": party_id, "party_level": 3},
            follow_redirects=True,
        )
        user.post(
            "/encounter/prebuilt",
            json={"template_name": "Goblin Ambush", "party_level": 3, "party_size": 4},
        )
        sims[user] = run_simulation(user)["simulation_id"]
    assert sims[client] != sims[other]
    for user in (client, other):
        assert db.get_simulation(sims[user])["session_id"] == session_id(user)
        assert shows_simulation(results_page(user), sims[user])
    # Neither can open the other's results
    assert client.get(f"/results?sim_id={sims[other]}").status_code == 404
    assert other.get(f"/results?sim_id={sims[client]}").status_code == 404


def test_a_batch_through_the_pages(client):
    """Start a batch, follow its progress until it's done, and open its results and history."""
    client.post("/party", data={"party_id": 1, "party_level": 3}, follow_redirects=True)
    client.post(
        "/encounter/prebuilt",
        json={"template_name": "Kobold Mob", "party_level": 3, "party_size": 4},
    )
    rv = client.post(
        "/batch/start", json={"num_runs": 10, "batch_name": "Kobold's test"}
    )
    assert rv.status_code == 200
    batch_id = rv.get_json()["batch_id"]
    deadline = time.time() + 60
    while not (progress := client.get(f"/batch/progress/{batch_id}").get_json())[
        "done"
    ]:
        assert time.time() < deadline, "batch did not finish"
        time.sleep(0.05)
    assert not progress["error"] and progress["progress"] == 100
    assert (
        progress["completed_runs"] == 10
        and progress["party_wins"] + progress["monster_wins"] == 10
    )

    page = client.get(f"/batch/results/{batch_id}").get_data(as_text=True)
    assert "Kobold&#39;s test" in page
    history = client.get("/api/batch/history").get_json()
    mine = next(b for b in history if b["id"] == batch_id)
    assert (mine["total_runs"], mine["party_wins"]) == (10, progress["party_wins"])
    assert "Kobold&#39;s test" in client.get("/batch/history").get_data(as_text=True)
