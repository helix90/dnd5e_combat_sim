"""Tests for the Paralyzed condition (ghoul attacks)."""
from unittest.mock import patch

import pytest

from controllers.batch_simulation_controller import BatchSimulationController
from models.actions import AttackAction
from models.rolls import roll_saving_throw
from models.buffs import create_paralyzed_condition, is_paralyzed
from models.character import Character
from models.combat import Combat
from models.db import DatabaseManager
from models.monster import Monster

SCORES = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}
PARALYSIS = {'condition': 'paralyzed', 'save_type': 'con', 'save_dc': 10,
             'duration_rounds': 10, 'immune_races': ['Elf']}


def make_hero(race='Human', hp=30):
    return Character('Hero', 1, 'Fighter', race, SCORES, hp=hp, ac=10, proficiency_bonus=2)


def make_ghoul():
    claws = AttackAction(name='Claws', description='Claws', weapon_name='Claws',
                         damage_dice='2d4+1', damage_type='slashing', hit_bonus=4,
                         on_hit=PARALYSIS)
    return Monster('Ghoul', '1', 22, 12, SCORES, actions=[claws])


def paralyze(creature):
    creature.buffs.add_buff(create_paralyzed_condition('Ghoul', 'con', 10))


@pytest.mark.parametrize('save_roll, paralyzed', [(5, True), (15, False)])
def test_hit_applies_paralysis_on_failed_save(save_roll, paralyzed):
    hero, ghoul = make_hero(), make_ghoul()
    # attack d20, two damage dice, then the CON save
    with patch('random.randint', side_effect=[15, 2, 2, save_roll]):
        result = ghoul.actions[0].execute(ghoul, hero)
    assert result['hit'] and result['damage'] == 5
    assert result['effect_save']['save_roll'] == save_roll
    assert is_paralyzed(hero) is paralyzed
    assert (result.get('condition_applied') == 'Paralyzed') is paralyzed


def test_miss_does_not_paralyze():
    hero, ghoul = make_hero(), make_ghoul()
    with patch('random.randint', side_effect=[1]):
        result = ghoul.actions[0].execute(ghoul, hero)
    assert not result['hit'] and not is_paralyzed(hero)


def test_elves_are_immune_but_half_elves_are_not():
    elf, half_elf, ghoul = make_hero('Elf'), make_hero('Half-Elf'), make_ghoul()
    with patch('random.randint', side_effect=[15, 2, 2]):
        result = ghoul.actions[0].execute(ghoul, elf)
    assert result['effect_immune'] and not is_paralyzed(elf)
    with patch('random.randint', side_effect=[15, 2, 2, 1]):
        ghoul.actions[0].execute(ghoul, half_elf)
    assert is_paralyzed(half_elf)


def test_attacks_against_paralyzed_have_advantage_and_melee_hits_crit():
    hero, ghoul = make_hero(), make_ghoul()
    paralyze(hero)
    # advantage: 3 and 18, take 18; crit doubles 2d4 to 4d4
    with patch('random.randint', side_effect=[3, 18, 1, 2, 3, 4]):
        result = ghoul.actions[0].execute(ghoul, hero)
    assert result['advantage'] and result['attack_roll'] == 18
    assert result['critical'] and result['damage'] == 1 + 2 + 3 + 4 + 1


def test_ranged_hits_against_paralyzed_are_not_crits():
    hero = make_hero()
    paralyze(hero)
    bow = AttackAction(name='Shortbow', description='', weapon_name='Shortbow', damage_dice='1d6+2',
                       damage_type='piercing', hit_bonus=4, weapon_type='ranged')
    with patch('random.randint', side_effect=[3, 18, 4]):
        result = bow.execute(make_ghoul(), hero)
    assert result['advantage'] and not result['critical'] and result['damage'] == 6


def test_paralyzed_creatures_auto_fail_str_and_dex_saves():
    hero = make_hero()
    paralyze(hero)
    with patch('random.randint', return_value=20):
        assert roll_saving_throw(hero, 'dex', 10)['save_success'] is False
        assert roll_saving_throw(hero, 'str', 10)['save_success'] is False
        assert roll_saving_throw(hero, 'con', 10)['save_success'] is True


@pytest.mark.parametrize('save_roll, still_paralyzed', [(20, False), (2, True)])
def test_paralyzed_creature_loses_turn_and_repeats_save(save_roll, still_paralyzed):
    hero, ghoul = make_hero(), make_ghoul()
    paralyze(hero)
    combat = Combat([hero, ghoul])
    combat.initiative_order = [hero, ghoul]
    with patch('random.randint', return_value=save_roll):
        combat.next_turn()
    entry = combat.get_combat_log()[-1]
    assert entry['actor'] == 'Hero'
    assert entry['result']['type'] == 'condition'
    assert ghoul.hp == 22  # hero took no action
    assert is_paralyzed(hero) is still_paralyzed
    assert entry['result']['condition_ended'] is not still_paralyzed


def test_paralysis_expires_after_one_minute():
    hero = make_hero()
    paralyze(hero)
    for _ in range(9):
        hero.buffs.tick_round()
    assert is_paralyzed(hero)
    hero.buffs.tick_round()
    assert not is_paralyzed(hero)


def test_ghoul_from_json_data_gets_paralysis():
    controller = BatchSimulationController.__new__(BatchSimulationController)
    actions = controller._build_actions_from_dicts([
        {'name': 'Claws', 'type': 'attack', 'damage_dice': '2d4+1', 'damage_type': 'slashing',
         'weapon_type': 'melee', 'on_hit': PARALYSIS}
    ])
    assert actions[0].on_hit == PARALYSIS


def test_combat_log_records_paralysis(tmp_path):
    db = DatabaseManager(str(tmp_path / 'test.db'))
    logs = db._convert_combat_log_format([
        {'type': 'action', 'actor': 'Ghoul 1', 'result': {
            'action': 'Claws', 'target': 'Hero', 'hit': True, 'damage': 5, 'condition_applied': 'Paralyzed'}},
        {'type': 'action', 'actor': 'Hero', 'result': {
            'action': 'Paralyzed', 'type': 'condition',
            'description': 'is paralyzed and loses its turn; fails a CON save (7) and remains paralyzed'}},
    ])
    assert logs[0]['result'] == 'Hit for 5 damage; target is paralyzed'
    assert logs[1]['action_type'] == 'condition'
    assert logs[1]['result'].startswith('is paralyzed and loses its turn')
    assert logs[1]['damage'] == 0
