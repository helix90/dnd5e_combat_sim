"""Fights and batches are deleted RETENTION_DAYS (30) days after they're run, and the pages say
when."""

import time
from unittest.mock import patch

import pytest

import app as app_module
from models.db import DatabaseManager
from tests.helpers import run_simulation, session_id


@pytest.fixture
def fought(client):
    """A finished 3-run batch and a single fight, for the level 1 party against goblins."""
    client.post("/party", data={"party_id": "1", "party_level": "1"})
    client.post(
        "/encounter/prebuilt",
        json={"template_name": "Goblin Ambush", "party_level": 1, "party_size": 4},
    )
    batch_id = client.post("/batch/start", json={"num_runs": 3}).get_json()["batch_id"]
    deadline = time.time() + 60
    while not client.get(f"/batch/progress/{batch_id}").get_json().get("done"):
        assert time.time() < deadline, "batch did not finish"
        time.sleep(0.05)
    fight_id = run_simulation(client)["simulation_id"]
    return client, batch_id, fight_id


def age(table, row_id, days):
    with DatabaseManager()._get_connection() as conn:
        conn.execute(
            f"UPDATE {table} SET created_at = datetime('now', ?) WHERE id = ?",
            (f"-{days} days", row_id),
        )
        conn.commit()


def count(sql, *args):
    with DatabaseManager()._get_connection() as conn:
        return conn.execute(sql, args).fetchone()[0]


def test_batches_and_fights_older_than_the_limit_are_deleted(fought):
    client, batch_id, fight_id = fought
    db = DatabaseManager()
    run_ids = [r["simulation_id"] for r in db.get_batch_runs(batch_id)]
    assert count("SELECT COUNT(*) FROM combat_logs WHERE simulation_id = ?", run_ids[0])

    age("batch_simulations", batch_id, 31)
    age("simulations", fight_id, 31)
    newer_fight = run_simulation(client)["simulation_id"]
    age("simulations", newer_fight, 29)

    assert db.purge_expired(30) == {
        "batches": 1,
        "batch_fights": 3,
        "fights": 1,
        "sessions": 0,  # the session still has its newer fight
    }
    assert db.get_batch_simulation(batch_id) is None
    assert count("SELECT COUNT(*) FROM batch_simulation_runs WHERE batch_id = ?", batch_id) == 0
    placeholders = ",".join("?" * (len(run_ids) + 1))
    assert count(
        f"SELECT COUNT(*) FROM simulations WHERE id IN ({placeholders})", *run_ids, fight_id
    ) == 0
    assert count(
        f"SELECT COUNT(*) FROM combat_logs WHERE simulation_id IN ({placeholders})",
        *run_ids,
        fight_id,
    ) == 0
    assert db.get_simulation(newer_fight)
    assert client.get(f"/batch/results/{batch_id}").status_code == 404


def test_a_batch_goes_by_its_own_age_not_its_fights(fought):
    _, batch_id, _ = fought
    db = DatabaseManager()
    for run in db.get_batch_runs(batch_id):
        age("simulations", run["simulation_id"], 31)
    assert db.purge_expired(30)["batch_fights"] == 0
    assert len(db.get_batch_runs(batch_id)) == 3


def test_old_sessions_with_nothing_left_are_deleted(client):
    client.get("/")
    owner = session_id(client)
    with DatabaseManager()._get_connection() as conn:
        conn.execute(
            "UPDATE sessions SET created_at = datetime('now', '-31 days') WHERE session_id = ?",
            (owner,),
        )
        conn.commit()
    assert DatabaseManager().purge_expired(30)["sessions"] >= 1
    assert count("SELECT COUNT(*) FROM sessions WHERE session_id = ?", owner) == 0


def test_requests_look_for_expired_history_once_an_hour(client):
    with patch.object(app_module.db, "purge_expired", return_value={}) as purge, patch.object(
        app_module, "_last_purge", None
    ):
        app_module.app.config["TESTING"] = False
        try:
            client.get("/healthz")
            deadline = time.time() + 5
            while not purge.called:
                assert time.time() < deadline, "the purge didn't run"
                time.sleep(0.01)
            client.get("/healthz")
        finally:
            app_module.app.config["TESTING"] = True
    purge.assert_called_once_with(30)


def test_pages_say_when_history_is_deleted(fought):
    client, batch_id, fight_id = fought
    batch = DatabaseManager().get_batch_simulation(batch_id)
    kept_until = app_module.expires(batch["created_at"])
    assert kept_until[:10] > str(batch["created_at"])[:10]

    page = client.get(f"/batch/results/{batch_id}").get_data(as_text=True)
    assert "kept until <time" in page and f"{kept_until[:16]} UTC" in page
    results = client.get(f"/results?sim_id={fight_id}").get_data(as_text=True)
    assert "Kept until <time" in results
    history = client.get("/history").get_data(as_text=True)
    assert "Fights and batches are deleted 30 days after they're run." in history


def test_the_session_cookie_lasts_as_long_as_the_history():
    assert app_module.app.config["PERMANENT_SESSION_LIFETIME"].days == 30
