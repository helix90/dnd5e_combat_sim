"""Tests for loading parties into Character objects for single and batch simulations."""
import os
import subprocess
import sys

import pytest

from app import app as flask_app, load_party_from_session
from models.character import Character
from models.character_builder import build_party
from models.spell_manager import SpellManager
from utils.exceptions import ValidationError
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


def _selected(client):
    with client.session_transaction() as sess:
        return sess.get('selected_party_id'), sess.get('selected_party_level')


@pytest.mark.parametrize('form, message', [
    ({'party_id': 1, 'party_level': 0}, b'level must be between 1 and 20'),
    ({'party_id': 1, 'party_level': 99}, b'level must be between 1 and 20'),
    ({'party_id': 999, 'party_level': 5}, b'Party with ID 999 not found'),
    ({'party_id': 1, 'party_level': 'abc'}, b'must be whole numbers'),
    ({'party_id': 1, 'party_level': 5, 'extra': 'x'}, b'Invalid field: extra'),
    ({'party_id': 1, 'party_level': '5;'}, b'Invalid characters'),
])
def test_invalid_party_selection_is_rejected(client, form, message):
    """A bad party POST shows the party page with an error and keeps the previous selection."""
    client.post('/party', data={'party_id': 2, 'party_level': 3})
    rv = client.post('/party', data=form)
    assert rv.status_code == 400
    assert b'Invalid party selection' in rv.data and message in rv.data
    assert _selected(client) == (2, 3)


def test_valid_party_selection_is_saved(client):
    rv = client.post('/party', data={'party_id': 2, 'party_level': 3})
    assert rv.status_code == 302 and rv.location.endswith('/encounter')
    assert _selected(client) == (2, 3)


def _corrupt_session(client):
    with client.session_transaction() as sess:
        sess['selected_party_id'] = 1
        sess['selected_party_level'] = 0
        sess['encounter_monsters'] = [{'name': 'Goblin'}]


def test_load_party_from_session_raises_instead_of_returning_no_party(client):
    _corrupt_session(client)
    with client.session_transaction() as sess:
        session_data = dict(sess)
    with flask_app.test_request_context():
        from flask import session
        session.update(session_data)
        with pytest.raises(ValidationError, match='Could not load the selected party'):
            load_party_from_session()


def test_simulate_with_unloadable_party_sends_user_back_to_party_page(client):
    _corrupt_session(client)
    rv = client.get('/simulate')
    assert rv.status_code == 302 and rv.location.endswith('/party')
    page = client.get('/party').data
    assert b'Could not load the selected party' in page and b'alert-danger' in page


def test_batch_with_unloadable_party_reports_the_reason(client):
    _corrupt_session(client)
    rv = client.post('/batch/start', json={'num_runs': 2, 'batch_name': 'test'})
    assert rv.status_code == 400
    assert 'Could not load the selected party' in rv.get_json()['error']


def _fire_bolt():
    from models.spells import Spell
    return Spell(name='Fire Bolt', level=0, school='Evocation', casting_time='1 action',
                 range='120 feet', duration='Instantaneous',
                 components={'verbal': True, 'somatic': True, 'material': False},
                 damage_dice='1d10', damage_type='fire')


def _caster(**kwargs):
    return Character('Mage', 1, 'Wizard', 'Elf',
                     {'str': 10, 'dex': 10, 'con': 10, 'int': 16, 'wis': 10, 'cha': 10},
                     hp=8, ac=12, proficiency_bonus=2, **kwargs)


@pytest.mark.parametrize('as_dict', [True, False])
def test_character_spells_argument_is_used(as_dict):
    fire_bolt = _fire_bolt()
    spells = {'Fire Bolt': fire_bolt} if as_dict else [fire_bolt]
    mage = _caster(spells=spells)
    assert mage.get_spell('Fire Bolt') is fire_bolt
    assert mage.spell_list == ['Fire Bolt'] and mage.can_cast_spell('Fire Bolt')


def test_character_spells_argument_rejects_non_spells():
    with pytest.raises(ValueError, match='Spell objects'):
        _caster(spells={'Fire Bolt': {'damage_dice': '1d10'}})


def test_character_does_not_change_the_callers_spell_list():
    spell_list = ['Magic Missile']
    mage = _caster(spell_list=spell_list, spells=[_fire_bolt()])
    assert spell_list == ['Magic Missile']
    assert mage.spell_list == ['Magic Missile', 'Fire Bolt']
