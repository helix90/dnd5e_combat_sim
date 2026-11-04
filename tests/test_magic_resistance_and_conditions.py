"""Magic Resistance (advantage on saves against spells and magical effects), knocking prone (a
wolf's or winter wolf's bite) and the horned devil's infernal wound."""
import copy
import json
import random
from unittest.mock import patch

import pytest

from ai.strategy import _save_fails
from models import rolls
from models.actions import AttackAction
from models.battlefield import movement_speed
from models.buffs import create_infernal_wound, create_prone_condition, create_restrained_condition, is_prone
from models.character import Character
from models.class_features import LayOnHandsAction, turn_undead
from models.combat import Combat
from models.monster import Monster
from models.monster_builder import build_monster
from models.rolls import attack_roll, roll_saving_throw
from models.spell_manager import SpellManager
from models.spells import SpellAction
from utils.paths import data_path

SPELLS = SpellManager()
MONSTERS = {m['name']: m for m in json.load(open(data_path('monsters.json')))['monsters']}
SCORES = {'str': 14, 'dex': 14, 'con': 14, 'int': 16, 'wis': 16, 'cha': 16}
FAIL = {'save_success': False, 'total_save': 1}


def monster(name):
    return build_monster(copy.deepcopy(MONSTERS[name]))


def hero(cls='Wizard', spells=(), features=(), hp=60, level=9):
    character = Character('Hero', level, cls, 'Human', SCORES, hp=hp, ac=14, proficiency_bonus=4,
                          spell_slots={'1': 4, '2': 3, '3': 3, '4': 3, '5': 1}, class_features=list(features),
                          actions=[AttackAction('Longsword', '', 'Longsword', '1d8', 'slashing')])
    for name in spells:
        character.add_spell(SPELLS.get_spell(name))
    return character


def action(creature, name):
    return next(a for a in creature.actions if a.name == name)


def hits(attack, attacker, target, die=15):
    """Run an attack with the d20 fixed (a hit against these targets)."""
    with patch('models.rolls.random.randint', return_value=die):
        return attack.execute(attacker, target)


# Magic Resistance


def test_magic_resistance_gives_advantage_on_saves_against_magic():
    devil = monster('Horned Devil')
    result = roll_saving_throw(devil, 'wis', 15, magical=True)
    assert result['advantage'] and result['magic_resistance'] and len(result['save_rolls']) == 2


def test_magic_resistance_does_not_help_against_nonmagical_effects():
    result = roll_saving_throw(monster('Erinyes'), 'con', 15)
    assert not result['advantage'] and 'magic_resistance' not in result


def test_creatures_without_magic_resistance_roll_once_against_magic():
    result = roll_saving_throw(monster('Fire Giant'), 'dex', 15, magical=True)
    assert not result['advantage'] and 'magic_resistance' not in result


@pytest.mark.parametrize('spell', ['Fireball', 'Hold Monster', 'Sacred Flame'])
def test_spell_saves_are_magical(spell):
    caster = hero('Wizard' if spell != 'Sacred Flame' else 'Cleric', [spell])
    devil = monster('Horned Devil')
    with patch('models.rolls.roll_d20', wraps=rolls.roll_d20) as roll:
        SpellAction(caster.spells[spell], spell_slot_level=SPELLS.get_spell(spell).level or None).execute(caster, devil)
    assert any(call.kwargs.get('advantage') for call in roll.call_args_list)


def test_hold_monster_repeat_saves_have_advantage_with_magic_resistance():
    caster = hero('Wizard', ['Hold Monster'])
    devil = monster('Horned Devil')
    with patch('models.spell_effects.roll_saving_throw', return_value=FAIL):
        SpellAction(caster.spells['Hold Monster'], spell_slot_level=5).execute(caster, devil)
    assert devil.buffs.get_condition('paralyzed').metadata['magical']
    combat = Combat([caster, devil])
    assert combat._paralyzed_turn(devil)['advantage']


def test_turn_undead_is_magical():
    cleric = hero('Cleric', features=['Channel Divinity (2)'])
    undead = Monster('Ghost', '4', 45, 11, SCORES, creature_type='undead', special_abilities=['Magic Resistance'])
    result = turn_undead(cleric, [undead])
    assert result['target_results'][0]['advantage'] and result['target_results'][0]['magic_resistance']


def test_party_ai_expects_magic_resistant_targets_to_fail_less_often():
    giant, devil = monster('Fire Giant'), monster('Horned Devil')
    devil.saving_throws = {}
    giant.saving_throws = {}
    giant.ability_scores['wis'] = devil.ability_scores['wis']
    plain = _save_fails(giant, 'wis', 17)
    assert _save_fails(devil, 'wis', 17) == pytest.approx(plain * plain)


# Prone


def test_wolf_bite_knocks_prone_on_a_failed_save():
    wolf, target = monster('Winter Wolf'), hero('Fighter')
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        result = hits(action(wolf, 'Bite'), wolf, target)
    assert result['hit'] and result['condition_applied'] == 'Prone' and is_prone(target)


def test_wolf_bite_does_not_knock_prone_on_a_successful_save():
    wolf, target = monster('Wolf'), hero('Fighter')
    with patch('models.actions.roll_saving_throw', return_value={'save_success': True, 'total_save': 20}):
        result = hits(action(wolf, 'Bite'), wolf, target)
    assert 'condition_applied' not in result and not is_prone(target)


def test_creatures_immune_to_prone_stay_up():
    wolf, wraith = monster('Wolf'), monster('Wraith')
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        result = hits(action(wolf, 'Bite'), wolf, wraith, die=20)
    assert result.get('effect_immune') and not is_prone(wraith)


def test_attacks_against_a_prone_creature():
    attacker, target = hero('Fighter'), hero('Rogue')
    target.buffs.add_buff(create_prone_condition('Wolf'))
    near = attack_roll(attacker, target, within_5ft=True)
    far = attack_roll(attacker, target, within_5ft=False)
    unknown = attack_roll(attacker, target)
    assert near.advantage and not near.disadvantage
    assert far.disadvantage and not far.advantage
    assert not unknown.advantage and not unknown.disadvantage


def test_melee_and_ranged_weapon_attacks_against_a_prone_creature():
    attacker, target = hero('Fighter'), hero('Rogue')
    target.buffs.add_buff(create_prone_condition('Wolf'))
    sword = AttackAction('Longsword', '', 'Longsword', '1d8', 'slashing')
    bow = AttackAction('Longbow', '', 'Longbow', '1d8', 'piercing', weapon_type='ranged', range=[150, 600])
    assert sword.execute(attacker, target)['advantage']
    assert bow.execute(attacker, target)['disadvantage']
    assert bow.execute(attacker, target, within_5ft=True)['advantage']


def test_a_prone_creature_attacks_with_disadvantage():
    attacker, target = hero('Fighter'), hero('Rogue')
    attacker.buffs.add_buff(create_prone_condition('Wolf'))
    assert attack_roll(attacker, target, within_5ft=True).disadvantage


def test_spell_attacks_against_a_prone_creature():
    caster, target = hero('Wizard', ['Fire Bolt']), monster('Ogre')
    target.buffs.add_buff(create_prone_condition('Trip'))
    fire_bolt = SpellAction(caster.spells['Fire Bolt'])
    assert fire_bolt.execute(caster, target)['disadvantage']
    assert fire_bolt.execute(caster, target, within_5ft=True)['advantage']


def test_standing_up_costs_half_the_creatures_speed():
    fighter, ogre = hero('Fighter'), monster('Ogre')
    fighter.speed = {'walk': 30}
    fighter.buffs.add_buff(create_prone_condition('Wolf'))
    combat = Combat([fighter, ogre])
    assert combat._stand_up(fighter)
    assert not is_prone(fighter) and movement_speed(fighter) == 15
    combat._end_of_turn_effects(fighter)
    assert movement_speed(fighter) == 30


def test_a_prone_creature_that_cannot_move_stays_down():
    fighter = hero('Fighter')
    fighter.buffs.add_buff(create_prone_condition('Wolf'))
    fighter.buffs.add_buff(create_restrained_condition('Druid', 'Entangle', 13))
    assert not Combat._stand_up(fighter) and is_prone(fighter)


def test_the_log_says_who_was_knocked_prone_and_who_stood_up():
    found = set()
    for seed in range(30):
        random.seed(seed)
        wolves = [monster('Winter Wolf') for _ in range(3)]
        for i, w in enumerate(wolves):
            w.name = f'Winter Wolf {i + 1}'
        party = [hero('Fighter', hp=120), hero('Cleric', hp=120)]
        party[1].name = 'Cleric'
        combat = Combat(party + wolves)
        combat.run()
        for line in combat.format_log_for_web():
            if 'is knocked prone!' in line:
                found.add('prone')
            if 'stands up.' in line:
                found.add('stood')
        if found == {'prone', 'stood'}:
            break
    assert found == {'prone', 'stood'}


# Infernal wound


def test_horned_devil_tail_wounds_on_a_failed_save():
    devil, target = monster('Horned Devil'), hero('Fighter', hp=100)
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        result = hits(action(devil, 'Tail'), devil, target)
    wound = target.buffs.get_condition('infernal_wound')
    assert result['condition_applied'] == 'Infernal Wound' and wound.metadata['wound_dice'] == ['3d6']


def test_further_tail_hits_deepen_the_wound_without_a_save():
    devil, target = monster('Horned Devil'), hero('Fighter', hp=200)
    target.buffs.add_buff(create_infernal_wound('Horned Devil', '3d6'))
    with patch('models.actions.roll_saving_throw') as save:
        result = hits(action(devil, 'Tail'), devil, target)
    save.assert_not_called()
    assert result['wound_deepened'] and target.buffs.get_condition('infernal_wound').metadata['wound_dice'] == ['3d6', '3d6']


def test_undead_and_constructs_cannot_be_wounded():
    devil = monster('Horned Devil')
    undead = Monster('Ghoul', '1', 100, 5, SCORES, creature_type='undead')
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        result = hits(action(devil, 'Tail'), devil, undead)
    assert result.get('effect_immune') and undead.buffs.get_condition('infernal_wound') is None


def test_the_wound_loses_hit_points_at_the_start_of_each_turn():
    fighter, devil = hero('Fighter', hp=60), monster('Horned Devil')
    fighter.buffs.add_buff(create_infernal_wound('Horned Devil', '3d6'))
    fighter.buffs.get_condition('infernal_wound').metadata['wound_dice'].append('3d6')
    combat = Combat([fighter, devil])
    with patch('models.combat.random.randint', return_value=2):
        assert not combat._infernal_wound(fighter)
    assert fighter.hp == 48   # 6d6 of 2s
    line = [l for l in combat.format_log_for_web() if 'infernal wound' in l]
    assert line == ['Hero loses 12 HP to an infernal wound.']


def test_the_wound_is_hit_point_loss_not_damage():
    # A creature resisting piercing loses the full amount, and a concentrating one doesn't save
    fighter, devil = hero('Fighter', hp=60), monster('Horned Devil')
    fighter.damage_resistances = ['piercing']
    fighter.buffs.add_buff(create_infernal_wound('Horned Devil', '3d6'))
    with patch('models.combat.random.randint', return_value=4), \
            patch('models.concentration.take_damage') as concentration_save:
        Combat([fighter, devil])._infernal_wound(fighter)
    assert fighter.hp == 48
    concentration_save.assert_not_called()


def test_a_wound_can_drop_a_creature():
    fighter, devil = hero('Fighter', hp=5), monster('Horned Devil')
    fighter.buffs.add_buff(create_infernal_wound('Horned Devil', '3d6'))
    with patch('models.combat.random.randint', return_value=6):
        assert Combat([fighter, devil])._infernal_wound(fighter)
    assert fighter.hp == 0


def test_healing_spells_close_the_wound():
    cleric, fighter = hero('Cleric', ['Cure Wounds']), hero('Fighter', hp=60)
    fighter.hp = 30
    fighter.buffs.add_buff(create_infernal_wound('Horned Devil', '3d6'))
    SpellAction(cleric.spells['Cure Wounds'], spell_slot_level=1).execute(cleric, fighter)
    assert fighter.buffs.get_condition('infernal_wound') is None


def test_lay_on_hands_closes_the_wound():
    paladin, fighter = hero('Paladin', features=['Lay on Hands (45)']), hero('Fighter', hp=60)
    fighter.hp = 30
    fighter.buffs.add_buff(create_infernal_wound('Horned Devil', '3d6'))
    LayOnHandsAction().execute(paladin, fighter)
    assert fighter.buffs.get_condition('infernal_wound') is None and fighter.hp == 60
