"""The Battlefield picker: no map, each encounter's own map, or a chosen map, on the encounter and batch pages."""

import pytest

from models.arena_library import ENCOUNTER_MAP


def picked(page: str, mode: str) -> bool:
    tag = page[
        page.index(f'id="battlefield-{mode}"')
        - 80 : page.index(f'id="battlefield-{mode}"')
        + 80
    ]
    return "checked" in tag


@pytest.mark.parametrize("path", ["/encounter", "/batch"])
def test_both_pages_offer_the_three_battlefields(client, path):
    page = client.get(path).get_data(as_text=True)
    assert 'id="battlefield-picker"' in page
    for mode in ("none", "own", "map"):
        assert f'id="battlefield-{mode}"' in page
    assert (
        '<option value="Open Field"' in page
        and "js/battlefield.js" in page
        and "js/arena_map.js" in page
    )
    assert picked(page, "none")


def test_the_picker_shows_the_saved_choice(client):
    client.post("/encounter/arena", json={"arena": ENCOUNTER_MAP})
    assert picked(client.get("/encounter").get_data(as_text=True), "own")
    client.post("/encounter/arena", json={"arena": "Open Field"})
    page = client.get("/batch").get_data(as_text=True)
    assert picked(page, "map") and "selected>Open Field" in page.replace("  ", " ")
    assert (
        'id="compareWithoutArenaGroup"' in page
        and 'compareWithoutArenaGroup" class' not in page
    )


def test_the_current_battlefield_follows_the_selected_encounter(client):
    assert client.get("/encounter/arena").get_json() == {
        "arena": None,
        "map": None,
        "encounter": None,
    }
    saved = client.post("/encounter/arena", json={"arena": ENCOUNTER_MAP}).get_json()
    assert saved["map"] == "Open Field"  # no pre-built encounter yet: the default map
    with client.session_transaction() as s:
        s["selected_encounter"] = "Goblin Ambush"
    current = client.get("/encounter/arena").get_json()
    assert current["arena"] == ENCOUNTER_MAP and current["map"] not in (
        None,
        "Open Field",
    )


def test_a_maps_drawing_is_available_for_the_preview(client):
    body = client.get("/api/arenas/Open Field").get_json()
    assert body["name"] == "Open Field" and body["width"] == 28 and body["description"]
    assert body["start_zones"]["party"] and body["start_zones"]["monsters"]
    assert client.get("/api/arenas/Moon Base").status_code == 404


def test_the_scripts_are_served(client):
    for name in ("battlefield.js", "arena_map.js"):
        response = client.get(f"/static/js/{name}")
        assert response.status_code == 200 and b"function" in response.data
        response.close()


def test_the_simulation_page_says_where_the_fight_is(client):
    from unittest.mock import patch

    client.post("/party", data={"party_id": "1", "party_level": "1"})
    client.post("/encounter/arena", json={"arena": "Open Field"})
    with client.session_transaction() as s:
        s["encounter_monsters"] = [{"name": "Goblin", "hp": 7, "ac": 15}]
    with patch("app.simulation_controller.execute_simulation"):
        page = client.get("/simulate").get_data(as_text=True)
    assert "Battlefield: <strong>Open Field</strong>" in page
