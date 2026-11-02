"""Tests for loading parties into Character objects for single and batch simulations."""
import os
import subprocess
import sys

import pytest

from app import app as flask_app, load_party_from_session
from models.character import Character
from models.character_builder import build_party
from models.spell_manager import SpellManager
from utils.party_loader import PartyLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client


def test_build_party_from_party_loader():
    party = PartyLoader.get_party_with_level(1, 5)['characters']
    characters = {c.name: c for c in build_party(party, SpellManager())}
    assert {c.level for c in characters.values()} == {5}
    assert 'Fire Bolt' in characters['Calyra'].spells
    assert [a.name for a in characters['Aldric'].actions][0] == 'Longsword'


def test_missing_level_falls_back_to_closest_lower_level():
    assert PartyLoader.resolve_level(10) == max(PartyLoader.get_available_levels())
    party = PartyLoader.get_party_with_level(1, 10)
    assert {c.level for c in build_party(party['characters'])} == {party['level']}


def test_session_party_level_is_the_level_actually_loaded(client):
    actual = PartyLoader.resolve_level(10)
    client.post('/party', data={'party_id': 1, 'party_level': 10})
    assert client.get('/api/party/current').get_json()['party_level'] == actual
    with client.session_transaction() as sess:
        session_data = dict(sess)
    with flask_app.test_request_context():
        from flask import session
        session.update(session_data)
        party, level = load_party_from_session()
    assert level == actual and {c['level'] for c in party} == {actual}


def test_member_without_actions_gets_default_attacks():
    hero = build_party([{'name': 'Bare', 'class': 'Rogue', 'level': 3}])[0]
    assert hero.character_class == 'Rogue' and hero.level == 3
    assert [a.name for a in hero.actions] == ['Sword Attack', 'Dagger Attack', 'Bow Attack']


def test_already_built_characters_pass_through():
    hero = Character('Hero', 1, 'Fighter', 'Human',
                     {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10},
                     hp=10, ac=10, proficiency_bonus=2)
    assert build_party([hero, 'junk']) == [hero]


def test_party_loads_from_any_working_directory(tmp_path):
    script = (
        "from utils.party_loader import PartyLoader\n"
        "from models.character_builder import build_party\n"
        "from models.spell_manager import SpellManager\n"
        "party = build_party(PartyLoader.get_party_with_level(1, 5)['characters'], SpellManager())\n"
        "calyra = next(c for c in party if c.name == 'Calyra')\n"
        "print(calyra.character_class, 'Fire Bolt' in calyra.spells, [a.name for a in calyra.actions])\n"
    )
    out = subprocess.run([sys.executable, '-c', script], cwd=tmp_path, capture_output=True, text=True,
                         env={**os.environ, 'PYTHONPATH': ROOT}, check=True).stdout
    assert out.strip().splitlines()[-1] == "Wizard True ['Quarterstaff']"
