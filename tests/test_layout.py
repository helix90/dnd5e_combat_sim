"""The page layout: Bootstrap served by the app, the setup bar, the home dashboard, the party
cards, and the history page with its two tabs."""

import json
import re

import pytest

from models.db import DatabaseManager
from tests.helpers import run_simulation, session_id
from utils.party_loader import PartyLoader


def test_bootstrap_is_served_by_the_app(client):
    page = client.get("/").get_data(as_text=True)
    assert "cdn.jsdelivr.net" not in page
    assert "cdn.jsdelivr.net" not in client.get("/").headers["Content-Security-Policy"]
    for path in re.findall(r'(?:href|src)="(/static/vendor/[^"]+)"', page):
        assert client.get(path).status_code == 200
    assert "/static/vendor/bootstrap-5.3.2/bootstrap.min.css" in page
    assert "/static/vendor/bootstrap-5.3.2/bootstrap.bundle.min.js" in page


def test_pages_have_the_dark_mode_switch(client):
    page = client.get("/").get_data(as_text=True)
    assert 'id="themeToggle"' in page and "data-bs-theme" in page


# The setup bar


def test_the_setup_bar_says_what_is_still_to_choose(client):
    page = client.get("/").get_data(as_text=True)
    assert "Classic Adventurers, level 5</span>" in page
    assert '<span class="step-missing">(default)</span>' in page
    assert "choose an encounter first" in page
    assert 'href="/simulate" class="btn btn-sm btn-primary py-0"' not in page


def test_the_setup_bar_shows_the_chosen_party_encounter_and_map(client):
    client.post("/party", data={"party_id": "2", "party_level": "3"})
    client.post(
        "/encounter/prebuilt",
        json={"template_name": "Goblin Ambush", "party_level": 3, "party_size": 4},
    )
    client.post("/encounter/arena", json={"arena": "Forest Road"})
    page = client.get("/history").get_data(as_text=True)
    party_name = PartyLoader.get_party_by_id(2)["name"]
    assert f"{party_name}, level 3</span>" in page
    assert "(default)" not in page
    assert '<span class="step-value">Goblin Ambush</span>' in page
    assert "· Forest Road" in page
    assert 'href="/simulate" class="btn btn-sm btn-primary py-0">One fight' in page


def test_the_setup_bar_marks_the_current_step(client):
    page = client.get("/party").get_data(as_text=True)
    assert re.search(r'class="setup-step[^"]* current"\s+href="/party"', page)


def test_a_broken_session_does_not_break_pages(client):
    client.get("/")
    with client.session_transaction() as s:
        s["selected_party_id"] = 999
        s["arena"] = 12345
    assert client.get("/").status_code == 200
    assert client.get("/history").status_code == 200


# Home


def test_home_explains_the_steps_before_the_first_fight(client):
    page = client.get("/").get_data(as_text=True)
    assert "How it works" in page and "Recent fights" not in page
    assert "Start a New Simulation" in page


def test_home_lists_the_latest_fights_and_batches(client):
    client.post("/party", data={"party_id": "1", "party_level": "1"})
    client.post(
        "/encounter/prebuilt",
        json={"template_name": "Goblin Ambush", "party_level": 1, "party_size": 4},
    )
    sim_id = run_simulation(client)["simulation_id"]
    db = DatabaseManager()
    batch_id = db.create_batch_simulation(
        session_id(client),
        "My batch",
        1,
        "prebuilt",
        details={"predicted_difficulty": "hard"},
    )
    db.update_batch_statistics(batch_id, 4, 3, 1, 3.0, 5.0)

    page = client.get("/").get_data(as_text=True)
    assert "How it works" not in page
    assert f'href="/results?sim_id={sim_id}"' in page and "Goblin Ambush" in page
    assert f'href="/batch/results/{batch_id}"' in page
    assert "My batch" in page and "Party won 75%" in page
    assert "Run one fight" in page


# Party page


def test_the_party_page_shows_each_party_at_the_chosen_level(client):
    client.post("/party", data={"party_id": "2", "party_level": "7"})
    page = client.get("/party").get_data(as_text=True)
    assert re.search(r'id="party-2" value="2"\s+autocomplete="off" checked', page)
    assert re.search(r'id="level-7" value="7"\s+autocomplete="off" checked', page)
    for character in PartyLoader.get_party_with_level(2, 7)["characters"]:
        row = (
            f'<td class="text-end">{character["ac"]}</td>'
            f'<td class="text-end">{character["hp"]}</td>'
        )
        assert row in page


def test_the_party_page_has_every_level_for_the_level_buttons(client):
    page = client.get("/party").get_data(as_text=True)
    rosters = re.search(
        r'<script type="application/json" id="rosters">(.*?)</script>', page, re.S
    ).group(1)
    rosters = json.loads(rosters)
    levels = [str(level) for level in PartyLoader.get_available_levels()]
    assert sorted(rosters["1"], key=int) == levels
    assert rosters["1"]["1"][0]["hp"] < rosters["1"]["10"][0]["hp"]


def test_a_bad_party_choice_shows_the_page_again(client):
    rv = client.post("/party", data={"party_id": "999", "party_level": "3"})
    assert rv.status_code == 400
    assert "Invalid party selection" in rv.get_data(as_text=True)


# History


@pytest.fixture
def some_history(client):
    client.get("/")
    db = DatabaseManager()
    sim_id = db.save_simulation_result(
        session_id(client),
        {
            "winner": "party",
            "rounds": 3,
            "encounter_name": "Goblin Ambush",
            "party_name": "Classic Adventurers",
            "predicted_difficulty": "deadly",
        },
    )
    batch_id = db.create_batch_simulation(session_id(client), "Wolves", 1, "prebuilt")
    return client, sim_id, batch_id


def test_history_has_fights_and_batches_on_tabs(some_history):
    client, sim_id, batch_id = some_history
    fights = client.get("/history").get_data(as_text=True)
    assert f'href="/results?sim_id={sim_id}"' in fights
    assert f'href="/batch/results/{batch_id}"' in fights
    assert re.search(r'class="nav-link active" id="fights-tab"', fights)
    batches = client.get("/batch/history").get_data(as_text=True)
    assert re.search(r'class="nav-link active" id="batches-tab"', batches)
    assert 'class="tab-pane fade show active" id="batches"' in batches


def test_history_rows_carry_what_the_filters_need(some_history):
    client, _, _ = some_history
    page = client.get("/history").get_data(as_text=True)
    assert 'data-rating="deadly" data-result="party"' in page
    assert 'data-search="goblin ambush classic adventurers"' in page
    assert 'data-rating="none"' in page and 'data-search="wolves"' in page


def test_dates_are_marked_up_for_the_readers_time_zone(some_history):
    client, sim_id, _ = some_history
    created = DatabaseManager().get_simulation(sim_id)["created_at"]
    page = client.get("/history").get_data(as_text=True)
    assert (
        f'<time class="local-time text-nowrap" datetime="{created.replace(" ", "T")}Z">'
        f"{created[:16]} UTC</time>"
    ) in page
