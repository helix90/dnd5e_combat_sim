"""Every encounter template builds in full and gets a difficulty rating and a matching warning."""

import json

import pytest

from models.encounter_builder import EncounterBuilder
from utils.paths import data_path

with open(data_path("encounter_templates.json")) as f:
    TEMPLATES = json.load(f)["encounters"]

WARNINGS = {
    "deadly": "Warning: This encounter is deadly for the party.",
    "trivial": "Warning: This encounter is trivial for the party.",
}


@pytest.fixture(scope="module")
def builder():
    return EncounterBuilder(monsters_file=data_path("monsters.json"))


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda t: t["name"])
def test_encounter_templates_build_and_are_rated(builder, template):
    encounter = builder.create_encounter_from_template(template)
    assert len(encounter) == sum(m["count"] for m in template["monsters"])
    # Templates may be deliberately deadly or trivial: the project measures how far CR is off
    difficulty = builder.calculate_encounter_difficulty(
        encounter, template["level"], 4
    )["difficulty"]
    assert difficulty in ("trivial", "easy", "medium", "hard", "deadly")
    assert builder.generate_encounter_warning(
        encounter, template["level"], 4
    ) == WARNINGS.get(difficulty, "Encounter is balanced.")
