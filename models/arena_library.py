"""
The battle maps in data/arenas.json.

Each entry is an Arena in the JSON form Arena.from_dict reads, plus a description for the app.
"""
import json
from typing import Any, Dict, List, Optional

from models.arena import Arena
from utils.paths import data_path

ARENAS_FILE = data_path('arenas.json')


def load_arena_definitions(path: str = ARENAS_FILE) -> List[Dict[str, Any]]:
    with open(path, 'r') as f:
        return json.load(f)['arenas']


def arena_choices(path: str = ARENAS_FILE) -> List[Dict[str, str]]:
    """Name and description of every map, for the encounter page."""
    return [{'name': a['name'], 'description': a.get('description', '')} for a in load_arena_definitions(path)]


def get_arena(name: Optional[str], path: str = ARENAS_FILE) -> Optional[Arena]:
    """The named map, or None for no arena. An unknown name is an error."""
    if not name:
        return None
    for definition in load_arena_definitions(path):
        if definition['name'] == name:
            return Arena.from_dict(definition)
    raise ValueError(f"Unknown arena: {name!r}")
