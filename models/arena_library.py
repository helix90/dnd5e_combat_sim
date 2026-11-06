"""
The battle maps in data/arenas.json.

Each entry is an Arena in the JSON form Arena.from_dict reads, plus a description for the app.
Generic maps ("generic": true) suit any encounter; the others are the maps of the pre-built
encounters, which name their map in data/encounter_templates.json ("arena").
"""

import json
from typing import Any, Dict, List, Optional

from models.arena import Arena
from utils.paths import data_path

ARENAS_FILE = data_path("arenas.json")

# The arena choice meaning "the pre-built encounter's own map"; custom encounters get DEFAULT_MAP
ENCOUNTER_MAP = "@encounter"
DEFAULT_MAP = "Open Field"


def load_arena_definitions(path: str = ARENAS_FILE) -> List[Dict[str, Any]]:
    with open(path, "r") as f:
        return json.load(f)["arenas"]


def arena_choices(path: str = ARENAS_FILE) -> List[Dict[str, Any]]:
    """Name, description and whether it's a generic map, for every map (for the encounter page)."""
    return [
        {
            "name": a["name"],
            "description": a.get("description", ""),
            "generic": bool(a.get("generic")),
        }
        for a in load_arena_definitions(path)
    ]


def resolve_arena_choice(
    choice: Optional[str], template: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """
    The map to fight on for an arena choice: None for no arena, the template's own map for
    ENCOUNTER_MAP (DEFAULT_MAP for a custom encounter, which has no template), or the named map.
    """
    if not choice:
        return None
    if choice == ENCOUNTER_MAP:
        return (template or {}).get("arena") or DEFAULT_MAP
    return choice


def get_arena(name: Optional[str], path: str = ARENAS_FILE) -> Optional[Arena]:
    """The named map, or None for no arena. An unknown name is an error."""
    if not name:
        return None
    for definition in load_arena_definitions(path):
        if definition["name"] == name:
            return Arena.from_dict(definition)
    raise ValueError(f"Unknown arena: {name!r}")
