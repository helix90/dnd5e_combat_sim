"""Arena data: creature sizes and speeds, attack reach and range, spell ranges in feet."""
import json

import pytest

from models.actions import AttackAction
from models.arena import normalize_speed, size_in_squares
from models.character_builder import build_character
from models.monster import Monster
from models.monster_builder import build_monster, build_monster_actions
from models.spell_manager import SpellManager
from models.spells import parse_range_feet
from utils.paths import data_path

MONSTERS = json.load(open(data_path('monsters.json')))['monsters']
CHARACTERS = [c for level in json.load(open(data_path('characters.json'))) for c in level['party']]
SPELL_ACTIONS = {'Fire Bolt', 'Sacred Flame', 'Eldritch Blast'}
SCORES = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}


def _check_attack(owner, action):
    """Every attack has a reach, a range, or both, and ranged-only attacks have a range."""
    if action.get('type') != 'attack' or action['name'] in SPELL_ACTIONS:
        return
    assert 'reach' in action or 'range' in action, (owner, action['name'])
    if action.get('weapon_type') == 'ranged':
        assert 'range' in action, (owner, action['name'])
    built = AttackAction(action['name'], '', action['name'], '1d6', 'piercing',
                         weapon_type=action.get('weapon_type', 'melee'),
                         reach=action.get('reach'), range=action.get('range'))
    assert built.reach is not None or built.range is not None


@pytest.mark.parametrize('monster', MONSTERS, ids=lambda m: m['name'])
def test_every_monster_has_size_speed_and_attack_distances(monster):
    size_in_squares(monster['size'])
    assert normalize_speed(monster['speed']) == monster['speed']
    for action in monster['actions']:
        _check_attack(monster['name'], action)
    built = build_monster(monster)
    assert built.size == monster['size'] and built.speed['walk'] == monster['speed']['walk']


@pytest.mark.parametrize('character', CHARACTERS, ids=lambda c: f"{c['name']}-{c['level']}")
def test_every_character_has_size_speed_and_attack_distances(character):
    size_in_squares(character['size'])
    assert character['speed']['walk'] >= 25
    for action in character.get('actions', []):
        _check_attack(character['name'], action)


def test_srd_monster_values():
    by_name = {m['name']: build_monster(m) for m in MONSTERS}
    giant = by_name['Hill Giant']
    assert giant.size == 'huge' and size_in_squares(giant.size) == 3 and giant.speed['walk'] == 40
    actions = {a.name: a for a in giant.actions}
    assert actions['Greatclub'].reach == 10 and actions['Greatclub'].range is None
    assert actions['Rock'].range == (60, 240) and actions['Rock'].reach is None
    javelin = next(a for a in by_name['Orc'].actions if a.name == 'Javelin')
    assert javelin.reach == 5 and javelin.range == (30, 120)
    assert by_name['Wraith'].speed == {'walk': 0, 'fly': 60, 'hover': True}
    assert by_name['Zombie'].speed['walk'] == 20 and by_name['Goblin'].size == 'small'
    breath = next(a for a in by_name['Young Dragon'].actions if a.name == 'Fire Breath')
    assert breath.area_effect and breath.reach is None and breath.range is None


def test_character_speeds_follow_race_and_class():
    built = {(c['name'], c['level']): build_character(c) for c in CHARACTERS}
    assert built[('Durgan', 1)].speed['walk'] == 25        # dwarf
    assert built[('Dax', 1)].size == 'small' and built[('Dax', 1)].speed['walk'] == 25   # halfling
    assert built[('Jax', 1)].speed['walk'] == 30 and built[('Jax', 2)].speed['walk'] == 40
    assert built[('Jax', 6)].speed['walk'] == 45           # Unarmored Movement +15 at 6th level
    assert built[('Grom', 4)].speed['walk'] == 30 and built[('Grom', 5)].speed['walk'] == 40  # Fast Movement
    bow = next(a for a in built[('Aldric', 1)].actions if a.name == 'Light Crossbow')
    assert bow.range == (80, 320) and bow.reach is None


# AttackAction reach and range

def test_attack_defaults():
    melee = AttackAction('Club', '', 'Club', '1d4', 'bludgeoning')
    assert melee.reach == 5 and melee.range is None
    bow = AttackAction('Bow', '', 'Bow', '1d6', 'piercing', weapon_type='ranged')
    assert bow.reach is None and bow.range is None
    thrown = AttackAction('Spear', '', 'Spear', '1d6', 'piercing', weapon_type='thrown', range=[20, 60])
    assert thrown.reach is None and thrown.range == (20, 60)


@pytest.mark.parametrize('kwargs', [
    {'range': [60, 20]}, {'range': [0, 20]}, {'range': [20]}, {'range': 'far'},
    {'reach': 0}, {'reach': 7.5}, {'reach': True},
])
def test_invalid_reach_and_range(kwargs):
    with pytest.raises(ValueError):
        AttackAction('Bad', '', 'Bad', '1d6', 'piercing', **kwargs)


def test_monster_builder_passes_reach_and_range():
    actions = build_monster_actions([
        {'name': 'Glaive', 'type': 'attack', 'reach': 10},
        {'name': 'Sling', 'type': 'attack', 'weapon_type': 'ranged', 'range': [30, 120]},
    ])
    assert actions[0].reach == 10 and actions[1].range == (30, 120)


# Size and speed

@pytest.mark.parametrize('speed, expected', [
    (None, {'walk': 30}), (25, {'walk': 25}), ({'walk': 40, 'climb': 30}, {'walk': 40, 'climb': 30}),
    ({'fly': 60, 'hover': True}, {'fly': 60, 'hover': True, 'walk': 0}),
])
def test_normalize_speed(speed, expected):
    assert normalize_speed(speed) == expected


@pytest.mark.parametrize('speed', [{'walk': -5}, {'teleport': 30}, {'walk': '30'}, 'fast', True])
def test_invalid_speed(speed):
    with pytest.raises(ValueError):
        normalize_speed(speed)


def test_creature_defaults_and_invalid_size():
    monster = Monster('Blob', '1', 10, 10, SCORES)
    assert monster.size == 'medium' and monster.speed == {'walk': 30}
    assert Monster('Ogre', '2', 59, 11, SCORES, size='Large').size == 'large'
    with pytest.raises(ValueError):
        Monster('Blob', '1', 10, 10, SCORES, size='enormous')


# Spell ranges

@pytest.mark.parametrize('text, feet', [
    ('120 feet', 120), ('60 ft.', 60), ('1 foot', 1), ('Touch', 5), ('Self', 0),
    ('Self (15-foot cone)', 0), ('1 mile', 5280), ('2 miles', 10560),
    ('Sight', None), ('Unlimited', None), ('', None), (None, None),
])
def test_parse_range_feet(text, feet):
    assert parse_range_feet(text) == feet


def test_every_spell_has_a_range_in_feet():
    spells = SpellManager().spells
    assert all(spell.range_feet is not None for spell in spells.values())
    assert spells['Fire Bolt'].range_feet == 120 and spells['Cure Wounds'].range_feet == 5
    assert spells['Shield'].range_feet == 0
