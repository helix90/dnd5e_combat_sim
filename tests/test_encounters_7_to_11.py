"""Encounters for levels 7-11: the SRD monsters they use (CR 2-12), the encounter templates and
their maps, XP for the higher CRs and levels, extra damage of a second type on a hit (a dragon's
bite, a wyvern's sting) and breath weapons dealing just their dice."""
import copy
import json
import random
from unittest.mock import patch

import pytest

from app import app as flask_app
from models.actions import AttackAction
from models.character import Character
from models.character_builder import build_party
from models.combat import Combat
from models.encounter_builder import EncounterBuilder
from models.monster import Monster
from models.monster_builder import build_monster, build_monsters
from models.multiattack import parse_multiattack
from models.spell_manager import SpellManager
from utils.party_loader import PartyLoader
from utils.paths import data_path

SPELLS = SpellManager()
MONSTERS = {m['name']: m for m in json.load(open(data_path('monsters.json')))['monsters']}
TEMPLATES = json.load(open(data_path('encounter_templates.json')))['encounters']
NEW_TEMPLATES = [t for t in TEMPLATES if t['level'] >= 7]
SCORES = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}

# SRD to-hit bonus of each new monster's attacks
TO_HIT = {
    ('Ogre', 'Greatclub'): 6, ('Ogre', 'Javelin'): 6, ('Ghast', 'Claws'): 5, ('Ghast', 'Bite'): 3,
    ('Hell Hound', 'Bite'): 5, ('Winter Wolf', 'Bite'): 6, ('Ettin', 'Battleaxe'): 7, ('Ettin', 'Morningstar'): 7,
    ('Wyvern', 'Bite'): 7, ('Wyvern', 'Stinger'): 7, ('Wyvern', 'Claws'): 7,
    ('Stone Giant', 'Greatclub'): 9, ('Stone Giant', 'Rock'): 9,
    ('Young Green Dragon', 'Bite'): 7, ('Young Green Dragon', 'Claw'): 7,
    ('Frost Giant', 'Greataxe'): 9, ('Frost Giant', 'Rock'): 9,
    ('Fire Giant', 'Greatsword'): 11, ('Fire Giant', 'Rock'): 11,
    ('Young Blue Dragon', 'Bite'): 9, ('Young Blue Dragon', 'Claw'): 9,
    ('Treant', 'Slam'): 10, ('Treant', 'Rock'): 10,
    ('Young Red Dragon', 'Bite'): 10, ('Young Red Dragon', 'Claw'): 10,
    ('Behir', 'Bite'): 10, ('Behir', 'Constrict'): 10,
    ('Horned Devil', 'Fork'): 10, ('Horned Devil', 'Tail'): 10, ('Horned Devil', 'Hurl Flame'): 7,
    ('Remorhaz', 'Bite'): 11, ('Erinyes', 'Longsword'): 8, ('Erinyes', 'Longbow'): 7,
}

# The attacks each new monster's Multiattack makes
ROUTINES = {
    'Ettin': ['Battleaxe', 'Morningstar'], 'Wyvern': ['Bite', 'Stinger'],
    'Stone Giant': ['Greatclub', 'Greatclub'], 'Frost Giant': ['Greataxe', 'Greataxe'],
    'Fire Giant': ['Greatsword', 'Greatsword'], 'Treant': ['Slam', 'Slam'],
    'Young Green Dragon': ['Bite', 'Claw', 'Claw'], 'Young Blue Dragon': ['Bite', 'Claw', 'Claw'],
    'Young Red Dragon': ['Bite', 'Claw', 'Claw'], 'Behir': ['Bite', 'Constrict'],
    'Horned Devil': ['Fork', 'Fork', 'Tail'], 'Erinyes': ['Longsword', 'Longsword', 'Longsword'],
}


def target(hp=200, ac=5, immune=(), con=10):
    scores = dict(SCORES, con=con)
    return Monster('Target', '1', hp, ac, scores, damage_immunities=list(immune))


# The data


def test_encounters_for_every_level_up_to_11():
    for level in range(7, 12):
        assert len([t for t in TEMPLATES if t['level'] == level]) >= 4, level


@pytest.mark.parametrize('template', NEW_TEMPLATES, ids=lambda t: t['name'])
def test_new_encounters_are_hard_or_deadly_by_the_dmg_budget(template):
    builder = EncounterBuilder()
    monsters = builder.create_encounter_from_template(template)
    assert builder.calculate_encounter_difficulty(monsters, template['level'])['difficulty'] in ('hard', 'deadly')


def test_xp_for_the_higher_challenge_ratings_and_levels():
    builder = EncounterBuilder()
    assert builder.calculate_encounter_difficulty([MONSTERS['Erinyes']], 11)['base_xp'] == 8400
    assert builder.calculate_encounter_difficulty([MONSTERS['Stone Giant']], 7)['base_xp'] == 2900
    # Two horned devils: 2 x 7,200 x 1.5 = 21,600, deadly for level 11 (3,600 x 4 = 14,400)
    result = builder.calculate_encounter_difficulty([MONSTERS['Horned Devil']] * 2, 11)
    assert result['total_xp'] == 21600 and result['difficulty'] == 'deadly'


@pytest.mark.parametrize('name, attack', sorted(TO_HIT), ids=lambda v: str(v))
def test_new_monsters_hit_with_their_srd_bonus(name, attack):
    monster = build_monster(MONSTERS[name])
    action = next(a for a in monster.actions if a.name == attack)
    assert action.hit_bonus(monster) == TO_HIT[(name, attack)]


@pytest.mark.parametrize('name', sorted(ROUTINES))
def test_new_monsters_multiattack(name):
    monster = build_monster(MONSTERS[name])
    multi = next(a for a in monster.actions if a.name == 'Multiattack')
    attacks = [a for a in monster.actions if a.action_type == 'attack' and not a.area_effect]
    assert [a.name for a in parse_multiattack(multi.description, attacks)] == ROUTINES[name]


def test_horned_devil_and_erinyes_switch_to_ranged_attacks_out_of_reach():
    for name, ranged in (('Horned Devil', 'Hurl Flame'), ('Erinyes', 'Longbow')):
        monster = build_monster(MONSTERS[name])
        multi = next(a for a in monster.actions if a.name == 'Multiattack')
        attacks = [a for a in monster.actions if a.action_type == 'attack']
        picked = parse_multiattack(multi.description, attacks, usable=lambda a: a.name == ranged)
        assert [a.name for a in picked] == [ranged] * 3


def test_breath_weapons_are_ready_area_attacks():
    for name in ('Hell Hound', 'Winter Wolf', 'Young Green Dragon', 'Young Blue Dragon', 'Young Red Dragon', 'Behir'):
        monster = build_monster(MONSTERS[name])
        breath = [a for a in monster.actions if getattr(a, 'area_effect', False)]
        assert len(breath) == 1 and breath[0].recharge == 5 and breath[0].area is not None, name


# Extra damage of a second type


def test_a_hit_adds_extra_damage_of_its_own_type():
    dragon = build_monster(MONSTERS['Young Green Dragon'])
    bite = next(a for a in dragon.actions if a.name == 'Bite')
    victim = target()
    with patch('models.actions.random.randint', return_value=1), \
            patch('models.actions.attack_roll') as roll:
        roll.return_value.result, roll.return_value.rolls = 15, [15]
        roll.return_value.advantage = roll.return_value.disadvantage = False
        result = bite.execute(dragon, victim)
    # 2d10+4 piercing = 6, plus 2d6 poison = 2
    assert result['hit'] and result['extra_damage'] == 2 and result['extra_damage_type'] == 'poison'
    assert result['damage'] == 8 and victim.hp == 192


def test_extra_damage_respects_the_targets_immunity():
    dragon = build_monster(MONSTERS['Young Green Dragon'])
    bite = next(a for a in dragon.actions if a.name == 'Bite')
    victim = target(immune=['poison'])
    with patch('models.actions.random.randint', return_value=1):
        extra = bite.roll_extra_damage(victim)
    assert extra['extra_damage'] == 0 and victim.hp == 200


def test_extra_damage_dice_double_on_a_critical_hit():
    hound = build_monster(MONSTERS['Hell Hound'])
    bite = next(a for a in hound.actions if a.name == 'Bite')
    with patch('models.actions.random.randint', return_value=3):
        assert bite.roll_extra_damage(target(), critical=True)['extra_damage'] == 12   # 4d6 of 3s
        assert bite.roll_extra_damage(target())['extra_damage'] == 6


def test_wyvern_sting_poison_is_halved_on_a_successful_save():
    wyvern = build_monster(MONSTERS['Wyvern'])
    sting = next(a for a in wyvern.actions if a.name == 'Stinger')
    with patch('models.actions.random.randint', return_value=4), \
            patch('models.actions.roll_saving_throw', return_value={'save_success': True, 'total_save': 20}):
        assert sting.roll_extra_damage(target())['extra_damage'] == 14   # 7d6 of 4s = 28, halved
    with patch('models.actions.random.randint', return_value=4), \
            patch('models.actions.roll_saving_throw', return_value={'save_success': False, 'total_save': 2}):
        assert sting.roll_extra_damage(target())['extra_damage'] == 28


def test_behir_constrict_adds_slashing_damage():
    behir = build_monster(MONSTERS['Behir'])
    constrict = next(a for a in behir.actions if a.name == 'Constrict')
    with patch('models.actions.random.randint', return_value=1):
        assert constrict.roll_extra_damage(target())['extra_damage'] == 8   # 2d10+6


def test_breath_weapon_damage_is_just_its_dice():
    # A young red dragon has STR 23; its breath is 16d6 with no modifier
    dragon = build_monster(MONSTERS['Young Red Dragon'])
    breath = next(a for a in dragon.actions if getattr(a, 'area_effect', False))
    with patch('models.actions.random.randint', return_value=1):
        assert breath.damage_roll(dragon) == 16
    claw = next(a for a in dragon.actions if a.name == 'Claw')
    with patch('models.actions.random.randint', return_value=1):
        assert claw.damage_roll(dragon) == 8   # 2d6+6


def test_weapon_damage_without_a_modifier_still_adds_the_ability_modifier():
    attacker = Character('Hero', 5, 'Fighter', 'Human', dict(SCORES, str=18), hp=40, ac=15, proficiency_bonus=3)
    sword = AttackAction('Longsword', '', 'Longsword', '1d8', 'slashing')
    with patch('models.actions.random.randint', return_value=1):
        assert sword.damage_roll(attacker) == 5


# Fights


def encounter(template):
    party = build_party(PartyLoader.get_party_with_level(1, min(template['level'], 10))['characters'], SPELLS)
    monsters = []
    for entry in template['monsters']:
        for i in range(entry['count']):
            data = copy.deepcopy(MONSTERS[entry['name']])
            data['name'] = f"{entry['name']} {i + 1}"
            monsters.append(data)
    return party, build_monsters(monsters)


@pytest.mark.parametrize('template', NEW_TEMPLATES, ids=lambda t: t['name'])
def test_new_encounters_finish_without_a_map(template):
    random.seed(7)
    party, monsters = encounter(template)
    assert Combat(party + monsters).run()['winner'] in ('party', 'monsters')


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        yield client


def test_encounter_list_offers_levels_7_to_11(client):
    templates = client.get('/api/encounters/prebuilt').get_json()
    assert {t['level'] for t in templates} >= set(range(7, 12))


def test_level_11_encounter_with_the_level_10_party(client):
    client.post('/party', data={'party_id': '1', 'party_level': '10'})
    response = client.post('/encounter/prebuilt', json={'template_name': "Devil's Gate", 'party_level': 11, 'party_size': 4})
    assert response.status_code == 200
    with client.session_transaction() as s:
        names = [m['name'] for m in s['encounter_monsters']]
    assert names == ['Horned Devil', 'Hell Hound 1', 'Hell Hound 2', 'Hell Hound 3']
