from unittest.mock import patch

import pytest
from models.encounter_builder import CR_XP, EncounterBuilder
from utils.paths import data_path


@pytest.fixture(scope="module")
def builder():
    return EncounterBuilder(monsters_file=data_path("monsters.json"))


def test_monster_loading(builder):
    assert len(builder.monster_data) >= 10
    names = [m["name"] for m in builder.monster_data]
    assert "Goblin" in names
    assert "Young Dragon" in names


def test_stat_calculation(builder):
    goblin = next(m for m in builder.monster_data if m["name"] == "Goblin")
    assert goblin["ac"] == 15
    assert goblin["hp"] == 7
    assert "Nimble Escape" in goblin["special_abilities"]


def test_encounter_difficulty_easy(builder):
    goblins = [
        next(m for m in builder.monster_data if m["name"] == "Goblin") for _ in range(2)
    ]
    result = builder.calculate_encounter_difficulty(
        goblins, party_level=1, party_size=4
    )
    assert result["difficulty"] in ("easy", "medium", "hard", "deadly")


def test_balance_validation(builder):
    orcs = [
        next(m for m in builder.monster_data if m["name"] == "Orc") for _ in range(2)
    ]
    assert builder.validate_encounter_balance(orcs, party_level=2, party_size=4)


def test_prebuilt_encounter_integrity(builder):
    import json

    with open("data/encounter_templates.json") as f:
        templates = json.load(f)["encounters"]
    for template in templates:
        encounter = builder.create_encounter_from_template(template)
        assert len(encounter) == sum(m["count"] for m in template["monsters"])
        for m in encounter:
            assert "name" in m and "ac" in m and "hp" in m


def test_generate_encounter_warning(builder):
    kobolds = [
        next(m for m in builder.monster_data if m["name"] == "Kobold")
        for _ in range(20)
    ]
    # 20 kobolds: 500 XP x 4 = 2,000, five times the 400 Deadly needs for four 1st-level characters
    warning = builder.generate_encounter_warning(kobolds, party_level=1, party_size=4)
    assert warning == "Warning: This encounter could kill the whole party."
    # 8 kobolds: 200 XP x 2.5 = 500, Deadly but short of twice it
    deadly = builder.generate_encounter_warning(kobolds[:8], party_level=1, party_size=4)
    assert deadly == "Warning: This encounter is deadly for the party."
    one = builder.generate_encounter_warning(kobolds[:4], party_level=1, party_size=4)
    assert one == "Encounter is balanced."


@pytest.mark.parametrize(
    "xp, rating",
    [(1099 * 4, "hard"), (1100 * 4, "deadly"), (2199 * 4, "deadly"), (2200 * 4, "tpk")],
)
def test_tpk_starts_at_twice_the_deadly_threshold(builder, xp, rating):
    # Level 5's Deadly threshold is 1,100 XP a character; one monster, so no multiplier
    with patch.dict(CR_XP, {"test": xp}):
        result = builder.calculate_encounter_difficulty([{"cr": "test"}], 5, 4)
    assert result["difficulty"] == rating
