"""What's fought is saved with each fight and batch, and shown on the results and history pages:
the encounter's name, the party's name, and the DMG's difficulty rating of the encounter for the
party. Also the shared page layout: the menu and the error page."""

import sqlite3
import time

import pytest

from app import describe_monsters
from models.db import DatabaseManager
from tests.helpers import run_simulation, session_id


@pytest.fixture
def goblin_ambush(client):
    """Classic Adventurers at level 1 against Goblin Ambush: 6 goblins, 300 XP, adjusted to 600,
    over the 400 a party of 4 at level 1 needs for Deadly."""
    client.post("/party", data={"party_id": "1", "party_level": "1"})
    client.post(
        "/encounter/prebuilt",
        json={"template_name": "Goblin Ambush", "party_level": 1, "party_size": 4},
    )
    return client


EXPECTED = {
    "encounter_type": "prebuilt",
    "encounter_name": "Goblin Ambush",
    "party_name": "Classic Adventurers",
    "party_level": 1,
    "predicted_difficulty": "deadly",
    "encounter_xp": 600,
}


def saved_details(record):
    return {key: record[key] for key in EXPECTED}


def wait_for_batch(client, batch_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.get(f"/batch/progress/{batch_id}").get_json().get("done"):
            return
        time.sleep(0.05)
    pytest.fail(f"batch {batch_id} did not finish within {timeout}s")


def test_a_fight_is_saved_with_what_was_fought(goblin_ambush):
    sim_id = run_simulation(goblin_ambush)["simulation_id"]
    assert saved_details(DatabaseManager().get_simulation(sim_id)) == EXPECTED

    page = goblin_ambush.get(f"/results?sim_id={sim_id}").get_data(as_text=True)
    assert "Goblin Ambush against Classic Adventurers, level 1" in page
    assert '>Deadly</span> <small class="text-muted">600 XP</small>' in page

    history = goblin_ambush.get("/history").get_data(as_text=True)
    assert "Goblin Ambush" in history and ">Deadly</span>" in history


def test_the_headline_says_who_won(goblin_ambush):
    sim_id = run_simulation(goblin_ambush)["simulation_id"]
    record = DatabaseManager().get_simulation(sim_id)
    rounds = record["rounds"]
    headline = {
        "party": "Party victory in",
        "monsters": "Party defeated in",
        "unknown": "No winner after",
    }[record["result"]]
    page = goblin_ambush.get(f"/results?sim_id={sim_id}").get_data(as_text=True)
    assert f"{headline} {rounds} round" in page


def test_a_batch_and_its_runs_are_saved_with_what_was_fought(goblin_ambush):
    rv = goblin_ambush.post(
        "/batch/start", json={"num_runs": 2, "batch_name": "Goblins"}
    )
    batch_id = rv.get_json()["batch_id"]
    wait_for_batch(goblin_ambush, batch_id)

    db = DatabaseManager()
    assert saved_details(db.get_batch_simulation(batch_id)) == EXPECTED
    runs = db.get_batch_runs(batch_id)
    assert len(runs) == 2
    for run in runs:
        assert saved_details(db.get_simulation(run["simulation_id"])) == EXPECTED

    page = goblin_ambush.get(f"/batch/results/{batch_id}").get_data(as_text=True)
    assert "Goblin Ambush" in page and "Classic Adventurers, level 1" in page
    assert ">Deadly</span>" in page
    assert ">Deadly</span>" in goblin_ambush.get("/batch/history").get_data(
        as_text=True
    )


def test_a_baseline_batch_is_saved_with_what_was_fought(goblin_ambush):
    goblin_ambush.post("/encounter/arena", json={"arena": "Forest Road"})
    rv = goblin_ambush.post(
        "/batch/start",
        json={"num_runs": 1, "batch_name": "Goblins", "compare_without_arena": True},
    )
    batch_id = rv.get_json()["batch_id"]
    wait_for_batch(goblin_ambush, batch_id)
    db = DatabaseManager()
    baseline_id = db.get_batch_simulation(batch_id)["baseline_batch_id"]
    assert saved_details(db.get_batch_simulation(baseline_id)) == EXPECTED


def test_a_batch_is_named_after_its_encounter_by_default(goblin_ambush):
    batch_id = goblin_ambush.post("/batch/start", json={"num_runs": 1}).get_json()[
        "batch_id"
    ]
    wait_for_batch(goblin_ambush, batch_id)
    assert DatabaseManager().get_batch_simulation(batch_id)["batch_name"] == (
        "Goblin Ambush"
    )


def test_a_custom_encounter_is_named_by_its_monsters(client):
    client.post("/party", data={"party_id": "1", "party_level": "1"})
    goblin = {"name": "Goblin", "cr": "1/4", "hp": 7, "ac": 15}
    bugbear = {"name": "Bugbear", "cr": "1", "hp": 27, "ac": 16}
    client.post(
        "/encounter/custom",
        json={"monsters": [goblin, goblin, bugbear], "party_level": 1, "party_size": 4},
    )
    record = DatabaseManager().get_simulation(run_simulation(client)["simulation_id"])
    # 50 + 50 + 200 XP, times 2 for three monsters: 600, Deadly for 4 level 1 characters
    assert record["encounter_type"] == "custom"
    assert record["encounter_name"] == "2× Goblin · 1× Bugbear"
    assert record["predicted_difficulty"] == "deadly"
    assert record["encounter_xp"] == 600


def test_describe_monsters_keeps_the_order_they_were_added():
    monsters = [{"name": "Orc"}, {"name": "Goblin"}, {"name": "Orc"}]
    assert describe_monsters(monsters) == "2× Orc · 1× Goblin"


def test_no_rating_is_saved_when_a_monster_has_no_cr(client):
    client.post("/party", data={"party_id": "1", "party_level": "1"})
    with client.session_transaction() as s:
        s["encounter_monsters"] = [{"name": "Goblin", "hp": 7, "ac": 15}]
    record = DatabaseManager().get_simulation(run_simulation(client)["simulation_id"])
    assert record["encounter_name"] == "1× Goblin"
    assert record["predicted_difficulty"] is None
    assert record["encounter_xp"] is None


def test_fights_saved_before_details_were_recorded_say_so(client):
    client.get("/")
    sim_id = DatabaseManager().save_simulation_result(
        session_id(client), {"winner": "party", "rounds": 3, "party_level": 2}
    )
    page = client.get(f"/results?sim_id={sim_id}").get_data(as_text=True)
    assert "Not recorded" in page and "Party victory in 3 rounds" in page
    assert "Not recorded" in client.get("/history").get_data(as_text=True)


def test_old_databases_get_the_fight_detail_columns(tmp_path):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE simulations (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
        "party_level INTEGER, encounter_type TEXT, result TEXT, rounds INTEGER DEFAULT 0, "
        "party_hp_remaining INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE batch_simulations (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
        "batch_name TEXT, party_level INTEGER, encounter_type TEXT, total_runs INTEGER DEFAULT 0, "
        "party_wins INTEGER DEFAULT 0, monster_wins INTEGER DEFAULT 0, average_rounds REAL DEFAULT 0.0, "
        "average_party_hp_remaining REAL DEFAULT 0.0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.commit()
    conn.close()
    DatabaseManager._initialized_paths.discard(path)
    db = DatabaseManager(path)
    details = {key: EXPECTED[key] for key in DatabaseManager.FIGHT_DETAILS}
    sim_id = db.save_simulation_result("s1", {"winner": "party", **details})
    assert {k: db.get_simulation(sim_id)[k] for k in details} == details
    batch_id = db.create_batch_simulation("s1", "b", 1, "prebuilt", details=details)
    assert {k: db.get_batch_simulation(batch_id)[k] for k in details} == details


# The page layout


def test_pages_have_a_menu_that_works_on_narrow_screens(client):
    page = client.get("/").get_data(as_text=True)
    assert 'name="viewport"' in page
    assert 'class="navbar-toggler"' in page and 'data-bs-target="#mainNav"' in page
    assert 'href="/batch/history"' in page


def test_the_menu_marks_the_current_page(client):
    page = client.get("/history").get_data(as_text=True)
    assert 'class="nav-link active" href="/history"' in page
    assert page.count("nav-link active") == 1


def test_the_error_page_has_the_menu(client):
    rv = client.get("/batch/results/999999")
    assert rv.status_code == 404
    page = rv.get_data(as_text=True)
    assert "Batch simulation 999999 not found" in page
    assert 'class="navbar-toggler"' in page


def test_the_security_policy_allows_bootstraps_icons(client):
    policy = client.get("/").headers["Content-Security-Policy"]
    assert "img-src 'self' data:" in policy
