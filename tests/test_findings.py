"""The batch results page's headline, charts and run pages, and the Findings page: the DMG's
ratings against how the fights went."""

import csv
import io
import json
import re
import time
from unittest.mock import patch

import pytest

from controllers.batch_simulation_controller import (
    csv_cell,
    damage_rows,
    histogram,
    win_rate,
)
from models.db import DatabaseManager
from tests.helpers import session_id
from utils.stats import wilson_interval


def test_wilson_interval():
    low, high = wilson_interval(24, 30)
    assert round(low, 1) == 62.7 and round(high, 1) == 90.5
    assert (
        wilson_interval(0, 10)[0] == 0 and round(wilson_interval(0, 10)[1], 1) == 27.8
    )
    assert round(wilson_interval(10, 10)[1]) == 100
    assert wilson_interval(0, 0) == (0.0, 100.0)


def test_win_rate():
    assert win_rate(3, 4)["rate"] == 75
    assert win_rate(0, 0)["rate"] == 0


def test_histogram_has_a_bar_per_number_when_they_fit():
    assert histogram([3, 4, 4, 7], start=3) == [
        {"label": "3", "value": 1},
        {"label": "4", "value": 2},
        {"label": "5", "value": 0},
        {"label": "6", "value": 0},
        {"label": "7", "value": 1},
    ]


def test_histogram_bins_wide_ranges_in_round_widths():
    bins = histogram(list(range(1, 90)), start=1, max_bins=12)
    assert [b["label"] for b in bins[:2]] == ["1–10", "11–20"]
    assert len(bins) == 9 and sum(b["value"] for b in bins) == 89
    assert histogram([], start=1) == []


def test_damage_rows_put_the_party_first_and_group_monsters_by_kind():
    totals = {"Aldric": 30, "Branwen": 60, "Goblin 1": 10, "Goblin 2": 5, "Ogre": 9}
    assert damage_rows(totals, runs=3) == [
        {"label": "Branwen", "value": 20, "side": "party"},
        {"label": "Aldric", "value": 10, "side": "party"},
        {"label": "Goblin (2)", "value": 5, "side": "monsters"},
        {"label": "Ogre", "value": 3, "side": "monsters"},
    ]
    assert damage_rows(totals, runs=0) == []


# Batch results


@pytest.fixture
def goblin_batch(client):
    """A finished 5-run batch of Goblin Ambush, which the DMG rates Deadly for the level 1 party."""
    client.post("/party", data={"party_id": "1", "party_level": "1"})
    client.post(
        "/encounter/prebuilt",
        json={"template_name": "Goblin Ambush", "party_level": 1, "party_size": 4},
    )
    batch_id = client.post("/batch/start", json={"num_runs": 5}).get_json()["batch_id"]
    deadline = time.time() + 60
    while not client.get(f"/batch/progress/{batch_id}").get_json().get("done"):
        assert time.time() < deadline, "batch did not finish"
        time.sleep(0.05)
    return client, batch_id


def chart_data(page, element_id):
    match = re.search(
        rf'<script type="application/json" id="{element_id}">(.*?)</script>',
        page,
        re.S,
    )
    return json.loads(match.group(1))


def test_batch_results_lead_with_the_win_rate_and_the_dmg_rating(goblin_batch):
    client, batch_id = goblin_batch
    batch = DatabaseManager().get_batch_simulation(batch_id)
    wins = batch["party_wins"]
    page = client.get(f"/batch/results/{batch_id}").get_data(as_text=True)
    low, high = wilson_interval(wins, 5)
    assert f'<div class="hero-figure">{wins * 20}%</div>' in page
    assert f"{wins} of 5 fights" in page
    assert f"95% confidence interval: {low:.0f}–{high:.0f}%" in page
    assert ">Deadly</span>" in page
    assert "Could be lethal for one or more characters." in page


def test_batch_results_chart_the_runs(goblin_batch):
    client, batch_id = goblin_batch
    runs = DatabaseManager().get_batch_runs(batch_id)
    page = client.get(f"/batch/results/{batch_id}").get_data(as_text=True)
    charts = chart_data(page, "chartData")
    assert sum(b["value"] for b in charts["rounds"]) == 5
    assert sum(b["value"] for b in charts["hp_left"]) == 5
    assert charts["hp_left"][0] == {
        "label": "0",
        "value": sum(r["party_hp_remaining"] == 0 for r in runs),
    }
    sides = {row["label"]: row["side"] for row in charts["damage"]}
    assert sides.get("Goblin (6)", "monsters") == "monsters"
    assert {"Aldric", "Branwen", "Calyra", "Dax"} & set(sides)
    assert all(sides[name] == "party" for name in {"Aldric", "Dax"} & set(sides))
    # Each chart's table view is on the page
    for chart in ("roundsChart", "hpChart", "damageChart"):
        assert f'id="{chart}"' in page
    assert page.count('class="viz-table table-responsive d-none"') == 3


def test_batch_runs_are_shown_a_page_at_a_time(goblin_batch):
    client, batch_id = goblin_batch
    with patch("app.BATCH_RUNS_PER_PAGE", 2):
        first = client.get(f"/batch/results/{batch_id}").get_data(as_text=True)
        third = client.get(f"/batch/results/{batch_id}?page=3").get_data(as_text=True)
        past_the_end = client.get(f"/batch/results/{batch_id}?page=99").get_data(
            as_text=True
        )
    assert "Page 1 of 3" in first and first.count("View Details") == 2
    assert "Page 3 of 3" in third and third.count("View Details") == 1
    assert "Page 3 of 3" in past_the_end


def test_short_batches_have_no_page_links(goblin_batch):
    client, batch_id = goblin_batch
    page = client.get(f"/batch/results/{batch_id}").get_data(as_text=True)
    assert "pagination" not in page and page.count("View Details") == 5


def test_batch_runs_download_as_csv(goblin_batch):
    client, batch_id = goblin_batch
    db = DatabaseManager()
    page = client.get(f"/batch/results/{batch_id}").get_data(as_text=True)
    assert f'href="/batch/results/{batch_id}/csv"' in page

    response = client.get(f"/batch/results/{batch_id}/csv")
    assert response.status_code == 200 and response.mimetype == "text/csv"
    assert response.headers["Content-Disposition"] == (
        f'attachment; filename="batch-{batch_id}-goblin-ambush.csv"'
    )
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
    header = list(rows[0])
    assert header[:11] == [
        "Batch",
        "Encounter",
        "Party",
        "Party Level",
        "Battlefield",
        "DMG Rating",
        "Encounter XP",
        "Run",
        "Winner",
        "Rounds",
        "Party HP Left",
    ]
    # The party in its own order, then the monsters, Goblin 2 before Goblin 10 would be
    assert header[11:15] == [f"{n} Damage" for n in ("Aldric", "Branwen", "Calyra", "Dax")]
    assert header[15:] == sorted(header[15:], key=lambda h: int(h.split()[1]))

    runs = db.get_batch_runs(batch_id)
    assert len(rows) == len(runs) == 5
    for row, run in zip(rows, runs):
        assert row["Batch"] == "Goblin Ambush" and row["DMG Rating"] == "Deadly"
        assert row["Party"] == "Classic Adventurers" and row["Party Level"] == "1"
        assert row["Battlefield"] == "No map"
        assert int(row["Run"]) == run["run_number"]
        assert row["Winner"] == {"party": "Party", "monsters": "Monsters"}[run["result"]]
        assert int(row["Rounds"]) == run["rounds"]
        assert int(row["Party HP Left"]) == run["party_hp_remaining"]
    # Each creature's damage over the runs adds up to the batch's, as the damage chart counts it
    totals = {h[: -len(" Damage")]: sum(int(r[h]) for r in rows) for h in header[11:]}
    assert {k: v for k, v in totals.items() if v} == db.get_batch_damage(batch_id)


def test_only_the_batchs_own_session_can_download_it(goblin_batch):
    from app import app

    _, batch_id = goblin_batch
    assert app.test_client().get(f"/batch/results/{batch_id}/csv").status_code == 404


def test_csv_cells_cant_be_read_as_formulas():
    assert csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert [csv_cell(v) for v in ("+1", "-1", "@SUM", "\tx")] == [
        "'+1",
        "'-1",
        "'@SUM",
        "'\tx",
    ]
    assert (csv_cell("Goblin Ambush"), csv_cell(-3), csv_cell(None)) == (
        "Goblin Ambush",
        -3,
        None,
    )


# Findings


def rated_batch(
    db, owner, rating, wins, runs, level=1, arena=None, rounds=4.0, xp=100
):
    batch_id = db.create_batch_simulation(
        owner,
        f"{rating} {wins}/{runs}",
        level,
        "prebuilt",
        arena=arena,
        details={
            "encounter_name": "Test",
            "party_name": "Classic Adventurers",
            "predicted_difficulty": rating,
            "encounter_xp": xp,
        },
    )
    db.update_batch_statistics(batch_id, runs, wins, runs - wins, rounds, 10.0)
    return batch_id


def test_saved_deadly_batches_at_twice_the_threshold_are_re_rated_tpk(client):
    client.get("/")
    owner, db = session_id(client), DatabaseManager()
    # Level 1: Deadly is 100 XP a character, 400 for the party; TPK from 800
    tpk = rated_batch(db, owner, "deadly", 1, 4, xp=800)
    deadly = rated_batch(db, owner, "deadly", 3, 4, xp=799)
    level_5 = rated_batch(db, owner, "deadly", 3, 4, level=5, xp=800)
    db._init_database()  # what starting the app does
    rating = lambda b: db.get_batch_simulation(b)["predicted_difficulty"]
    assert (rating(tpk), rating(deadly), rating(level_5)) == ("tpk", "deadly", "deadly")

    page = client.get("/findings").get_data(as_text=True)
    assert '<span class="badge badge-tpk">TPK</span>' in page
    assert "the whole party could die" in page
    history = client.get("/batch/history").get_data(as_text=True)
    assert '<option value="tpk">TPK</option>' in history


def test_findings_pool_each_ratings_fights(client):
    client.get("/")
    owner, db = session_id(client), DatabaseManager()
    rated_batch(db, owner, "deadly", 15, 20, rounds=5.0)
    rated_batch(db, owner, "deadly", 5, 10, rounds=2.0)
    rated_batch(db, owner, "easy", 10, 10)
    rated_batch(db, "someone else", "easy", 0, 10)
    unfinished = rated_batch(db, owner, "hard", 0, 0)

    page = client.get("/findings").get_data(as_text=True)
    chart = chart_data(page, "findingsData")
    assert [r["key"] for r in chart["ratings"]] == [
        "trivial",
        "easy",
        "medium",
        "hard",
        "deadly",
        "tpk",
    ]
    assert chart["ratings"][-1]["label"] == "TPK"
    assert len(chart["batches"]) == 3  # not the other session's, nor the unfinished
    pooled = {p["rating"]: p for p in chart["pooled"]}
    assert (pooled["deadly"]["wins"], pooled["deadly"]["runs"]) == (20, 30)
    assert (pooled["easy"]["wins"], pooled["easy"]["runs"]) == (10, 10)
    assert pooled["hard"]["runs"] == 0
    low, high = wilson_interval(20, 30)
    assert f"{low:.0f}–{high:.0f}%" in page
    # The deadly batches' rounds, weighted by their runs: (5 * 20 + 2 * 10) / 30
    assert '<td class="text-end">4.0</td>' in page
    assert f"/batch/results/{unfinished}" not in page


def test_findings_filter_by_level_and_battlefield(client):
    client.get("/")
    owner, db = session_id(client), DatabaseManager()
    rated_batch(db, owner, "deadly", 1, 2, level=1)
    rated_batch(db, owner, "deadly", 1, 4, level=5, arena="Forest Road")
    rated_batch(db, owner, "hard", 1, 8, level=5)

    def runs(query):
        page = client.get(f"/findings{query}").get_data(as_text=True)
        if "No batches match these filters." in page:
            return []
        return sorted(b["runs"] for b in chart_data(page, "findingsData")["batches"])

    assert runs("") == [2, 4, 8]
    assert runs("?level=5") == [4, 8]
    assert runs("?battlefield=map") == [4]
    assert runs("?battlefield=none") == [2, 8]
    assert runs("?level=1&battlefield=map") == []
    assert runs("?battlefield=nonsense") == [2, 4, 8]


def test_findings_without_batches_say_how_to_get_some(client):
    page = client.get("/findings").get_data(as_text=True)
    assert "No rated batches yet." in page and "findingsData" not in page
    assert 'class="nav-link active" href="/findings"' in page


def test_findings_with_filters_matching_nothing_say_so(client):
    client.get("/")
    rated_batch(DatabaseManager(), session_id(client), "deadly", 1, 2, level=1)
    page = client.get("/findings?level=7").get_data(as_text=True)
    assert "No batches match these filters." in page
