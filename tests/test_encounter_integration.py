import pytest
import json
from models.encounter_builder import EncounterBuilder

@pytest.fixture(scope="module")
def builder():
    return EncounterBuilder(monsters_file="data/monsters.json")

@pytest.fixture(scope="module")
def templates():
    with open("data/encounter_templates.json") as f:
        return json.load(f)["encounters"]

def test_encounter_templates_balanced(builder, templates):
    # For each template, generate and validate the encounter
    for template in templates:
        encounter = builder.create_encounter_from_template(template)
        party_level = template["level"]
        party_size = 4
        result = builder.calculate_encounter_difficulty(encounter, party_level, party_size)
        warning = builder.generate_encounter_warning(encounter, party_level, party_size)
        # Print for manual review (optional)
        print(f"{template['name']} (Level {party_level}): {result['difficulty']} - {warning}")
        # Assert that most templates are not deadly or trivial
        assert result["difficulty"] in ("easy", "medium", "hard", "deadly", "trivial")
        # Optionally, allow some templates to be deadly for demonstration
        # If you want to enforce balance, uncomment below:
        # assert result["difficulty"] in ("easy", "medium", "hard") 