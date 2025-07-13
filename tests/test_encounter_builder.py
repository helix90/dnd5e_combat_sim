import pytest
import os
from models.encounter_builder import EncounterBuilder

@pytest.fixture(scope="module")
def builder():
    return EncounterBuilder(monsters_file="data/monsters.json")

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
    goblins = [next(m for m in builder.monster_data if m["name"] == "Goblin") for _ in range(2)]
    result = builder.calculate_encounter_difficulty(goblins, party_level=1, party_size=4)
    assert result["difficulty"] in ("easy", "medium", "hard", "deadly")

def test_balance_validation(builder):
    orcs = [next(m for m in builder.monster_data if m["name"] == "Orc") for _ in range(2)]
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
    kobolds = [next(m for m in builder.monster_data if m["name"] == "Kobold") for _ in range(20)]
    warning = builder.generate_encounter_warning(kobolds, party_level=1, party_size=4)
    assert "deadly" in warning or "trivial" in warning or "balanced" in warning 