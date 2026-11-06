"""Hit point maximum drain (wight, wraith, vampire spawn), a ghast's Stench and a mummy's Mummy Rot."""
import copy
import json
import random
from unittest.mock import patch

from ai.positioning import _Weapon
from ai.strategy import PartyAIStrategy
from models.actions import AttackAction
from models.arena import Arena, Placement
from models.buffs import create_mummy_rot, create_paralyzed_condition, create_restrained_condition
from models.character import Character
from models.class_features import LayOnHandsAction, wants_second_wind
from models.combat import Combat
from models.damage import reduce_max_hp, regain_hp
from models.multiattack import for_target, parse_multiattack
from models.rolls import attack_roll
from models.spell_manager import SpellManager
from models.spells import SpellAction
from models.monster_builder import build_monster
from utils.paths import data_path

SPELLS = SpellManager()
MONSTERS = {m['name']: m for m in json.load(open(data_path('monsters.json')))['monsters']}
SCORES = {'str': 14, 'dex': 14, 'con': 14, 'int': 16, 'wis': 16, 'cha': 16}
FAIL = {'save_success': False, 'total_save': 1}
SAVE = {'save_success': True, 'total_save': 20}


def monster(name, label=None):
    creature = build_monster(copy.deepcopy(MONSTERS[name]))
    creature.name = label or name
    return creature


def hero(cls='Fighter', spells=(), features=(), hp=60, name='Hero'):
    character = Character(name, 9, cls, 'Human', SCORES, hp=hp, ac=14, proficiency_bonus=4,
                          spell_slots={'1': 4, '2': 3, '3': 3, '4': 3, '5': 1}, class_features=list(features),
                          actions=[AttackAction('Longsword', '', 'Longsword', '1d8', 'slashing')])
    for spell in spells:
        character.add_spell(SPELLS.get_spell(spell))
    return character


def action(creature, name):
    return next(a for a in creature.actions if a.name == name)


def hits(attack, attacker, target, die=15):
    """Run an attack with the d20 fixed (a hit against these targets)."""
    with patch('models.rolls.random.randint', return_value=die):
        return attack.execute(attacker, target)


def on_arena(*placed):
    """A Combat on an empty arena with each (creature, x, y) where the test puts it."""
    combat = Combat([c for c, _, _ in placed], arena=Arena(20, 20, name='Test'))
    for creature, x, y in placed:
        combat.battlefield.placements[creature] = Placement((x, y), combat.battlefield.placements[creature].size)
    return combat


# Hit point maximum drain


def test_wight_drains_the_hit_point_maximum_on_a_failed_save():
    wight, target = monster('Wight'), hero(hp=60)
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        result = hits(action(wight, 'Longsword'), wight, target)
    assert result['hit'] and result['hp_drained'] == result['damage'] > 0
    assert target.max_hp == 60 - result['damage'] == result['target_max_hp_after']


def test_no_drain_on_a_successful_save():
    wraith, target = monster('Wraith'), hero(hp=60)
    with patch('models.actions.roll_saving_throw', return_value=SAVE):
        result = hits(action(wraith, 'Life Drain'), wraith, target)
    assert result['hit'] and 'hp_drained' not in result and target.max_hp == 60


def test_drain_is_the_damage_taken_after_resistance():
    wraith, target = monster('Wraith'), hero(hp=60)
    target.damage_resistances = ['necrotic']
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        result = hits(action(wraith, 'Life Drain'), wraith, target)  # every die rolls 15
    assert result['damage'] == (15 + 15 + 3) // 2 == result['hp_drained']


def test_drain_still_applies_when_the_hit_drops_the_target():
    wraith, target = monster('Wraith'), hero(hp=60)
    target.hp = 3
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        result = hits(action(wraith, 'Life Drain'), wraith, target)
    assert target.hp <= 0 and target.max_hp == 60 - result['damage']


def test_healing_stops_at_the_reduced_maximum():
    cleric, target = hero('Cleric', ['Cure Wounds']), hero(hp=60)
    reduce_max_hp(target, 20)
    target.hp = 30
    with patch('models.spells.random.randint', return_value=8):
        SpellAction(cleric.spells['Cure Wounds'], spell_slot_level=3).execute(cleric, target)
    assert target.max_hp == 40 and target.hp == 40


def test_a_creature_drained_to_zero_cannot_be_healed():
    target = hero(hp=20)
    assert reduce_max_hp(target, 50) == 20
    assert target.max_hp == 0 and target.hp == 0
    assert regain_hp(target, 10) == 0 and target.hp == 0


def test_vampire_spawn_bite_drains_without_a_save_and_heals_the_spawn():
    spawn, target = monster('Vampire Spawn'), hero(hp=60)
    target.buffs.add_buff(create_paralyzed_condition('Ghoul', 'con', 10))
    spawn.hp = 20
    with patch('models.actions.roll_saving_throw') as save:
        result = hits(action(spawn, 'Bite'), spawn, target)
    save.assert_not_called()
    assert result['hp_drained'] == result['damage'] and target.max_hp == 60 - result['damage']
    assert result['attacker_healed'] == result['damage'] and spawn.hp == 20 + result['damage']


def test_vampire_spawn_bites_only_a_grappled_incapacitated_or_restrained_target():
    spawn = monster('Vampire Spawn')
    attacks = [a for a in spawn.actions if isinstance(a, AttackAction)]
    multiattack = action(spawn, 'Multiattack').description
    routine = parse_multiattack(multiattack, attacks)
    assert [a.name for a in routine] == ['Claws', 'Bite']

    free, held, stuck = hero(), hero(), hero()
    held.buffs.add_buff(create_paralyzed_condition('Ghoul', 'con', 10))
    stuck.buffs.add_buff(create_restrained_condition('Druid', 'Web', 12))
    assert [a.name for a in for_target(routine, free)] == ['Claws', 'Claws']
    assert [a.name for a in for_target(routine, held)] == ['Claws', 'Bite']
    assert [a.name for a in for_target(routine, stuck)] == ['Claws', 'Bite']


def test_vampire_spawn_multiattack_in_combat():
    spawn, free, held = monster('Vampire Spawn'), hero(name='Free'), hero(name='Held')
    held.buffs.add_buff(create_paralyzed_condition('Ghoul', 'con', 10))
    combat = Combat([free, held, spawn])
    multiattack = action(spawn, 'Multiattack')
    assert combat._execute_multiattack(spawn, free, multiattack)['attacks_performed'] == ['Claws', 'Claws']
    assert combat._execute_multiattack(spawn, held, multiattack)['attacks_performed'] == ['Claws', 'Bite']


def test_arena_ai_does_not_plan_a_bite_on_a_free_target():
    spawn, target = monster('Vampire Spawn'), hero()
    bite = _Weapon(spawn, action(spawn, 'Bite'))
    assert bite.evaluate(spawn, target, 5, lambda *a: False) is None


def test_the_log_shows_the_drain():
    found = False
    for seed in range(40):
        random.seed(seed)
        wights = [monster('Wight', f'Wight {i + 1}') for i in range(2)]
        party = [hero(name='Aldric', hp=80), hero(name='Branwen', hp=80)]
        combat = Combat(party + wights)
        combat.run()
        if any("hit point maximum drops by" in line for line in combat.format_log_for_web()):
            found = True
            break
    assert found


# Mummy Rot


def test_mummy_fist_curses_with_mummy_rot_on_a_failed_save():
    mummy, target = monster('Mummy'), hero(hp=100)
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        result = hits(action(mummy, 'Rotting Fist'), mummy, target)
    assert result['condition_applied'] == 'Mummy Rot' and target.buffs.has_condition('mummy_rot')


def test_mummy_rot_is_not_rolled_for_again():
    mummy, target = monster('Mummy'), hero(hp=100)
    target.buffs.add_buff(create_mummy_rot('Mummy'))
    with patch('models.actions.roll_saving_throw', return_value=FAIL):
        hits(action(mummy, 'Rotting Fist'), mummy, target)
    assert sum(b.name == 'Mummy Rot' for b in target.buffs.active_buffs) == 1


def test_a_creature_with_mummy_rot_regains_no_hit_points():
    cleric, target = hero('Cleric', ['Cure Wounds']), hero(hp=60)
    target.hp = 20
    target.buffs.add_buff(create_mummy_rot('Mummy'))
    result = SpellAction(cleric.spells['Cure Wounds'], spell_slot_level=1).execute(cleric, target)
    assert target.hp == 20 and result['healing'] == 0
    assert regain_hp(target, 10, magical=False) == 0 and target.hp == 20


def test_lay_on_hands_and_second_wind_are_not_wasted_on_mummy_rot():
    paladin, target = hero('Paladin', features=['Lay on Hands (45)']), hero(hp=60)
    target.hp = 20
    target.buffs.add_buff(create_mummy_rot('Mummy'))
    result = LayOnHandsAction().execute(paladin, target)
    assert result['healing'] == 0 and target.hp == 20

    fighter = hero('Fighter', features=['Second Wind'])
    fighter.hp = 10
    assert wants_second_wind(fighter)
    fighter.buffs.add_buff(create_mummy_rot('Mummy'))
    assert not wants_second_wind(fighter)


def test_the_party_does_not_try_to_heal_a_cursed_ally():
    cleric = hero('Cleric', ['Cure Wounds'], name='Cleric')
    cursed = hero(name='Cursed')
    cursed.hp = 5
    cursed.buffs.add_buff(create_mummy_rot('Mummy'))
    assert PartyAIStrategy()._try_heal_ally(cleric, [cursed]) is None


# Stench


def test_stench_poisons_a_creature_starting_its_turn_next_to_a_ghast():
    fighter, ghast = hero(), monster('Ghast')
    combat = on_arena((fighter, 5, 5), (ghast, 6, 5))
    with patch('models.turn_effects.roll_saving_throw', return_value=FAIL):
        combat._stench(fighter)
    assert fighter.buffs.has_condition('poisoned')
    assert attack_roll(fighter, ghast).disadvantage
    assert "Hero is poisoned by Ghast's stench." in combat.format_log_for_web()
    # until the start of its next turn
    combat._start_of_turn_effects(fighter)
    assert not fighter.buffs.has_condition('poisoned')


def test_a_successful_save_makes_the_creature_immune_to_that_ghasts_stench():
    fighter, ghast = hero(), monster('Ghast', 'Ghast 1')
    other = monster('Ghast', 'Ghast 2')
    combat = on_arena((fighter, 5, 5), (ghast, 6, 5), (other, 4, 5))
    with patch('models.turn_effects.roll_saving_throw', side_effect=[SAVE, FAIL]):
        combat._stench(fighter)
    assert fighter.buffs.has_condition('poisoned')
    with patch('models.turn_effects.roll_saving_throw', return_value=FAIL) as save:
        combat._stench(fighter)
    assert save.call_count == 1  # only Ghast 2 still gets a save


def test_no_stench_save_away_from_the_ghast():
    fighter, ghast = hero(), monster('Ghast')
    combat = on_arena((fighter, 5, 5), (ghast, 8, 5))
    with patch('models.turn_effects.roll_saving_throw', return_value=FAIL) as save:
        combat._stench(fighter)
    save.assert_not_called()


def test_creatures_immune_to_poison_ignore_the_stench():
    ghoul, ghast = monster('Ghoul'), monster('Ghast')
    combat = on_arena((ghoul, 5, 5), (ghast, 6, 5))
    with patch('models.turn_effects.roll_saving_throw', return_value=FAIL) as save:
        combat._stench(ghoul)
    save.assert_not_called()


def test_without_an_arena_stench_reaches_whoever_is_fighting_the_ghast_in_melee():
    fighter, archer, ghast = hero(name='Fighter'), hero(name='Archer'), monster('Ghast')
    combat = Combat([fighter, archer, ghast])
    combat._note_melee_target(fighter, {'type': 'attack', 'action': fighter.actions[0], 'target': ghast})
    bow = AttackAction('Longbow', '', 'Longbow', '1d8', 'piercing', weapon_type='ranged', range=[150, 600])
    combat._note_melee_target(archer, {'type': 'attack', 'action': bow, 'target': ghast})
    with patch('models.turn_effects.roll_saving_throw', return_value=FAIL):
        combat._stench(fighter)
        combat._stench(archer)
    assert fighter.buffs.has_condition('poisoned') and not archer.buffs.has_condition('poisoned')


def test_stench_happens_in_a_fight():
    found = False
    for seed in range(20):
        random.seed(seed)
        ghasts = [monster('Ghast', f'Ghast {i + 1}') for i in range(3)]
        combat = Combat([hero(name='Aldric', hp=80), hero(name='Branwen', hp=80)] + ghasts)
        combat.run()
        if any("'s stench" in line for line in combat.format_log_for_web()):
            found = True
            break
    assert found


def test_the_saved_log_shows_what_each_attack_of_a_multiattack_did(tmp_path):
    from models.db import DatabaseManager
    logs = DatabaseManager(str(tmp_path / 'test.db'))._convert_combat_log_format([
        {'type': 'action', 'actor': 'Wight 1', 'result': {
            'action': 'Multiattack', 'type': 'special', 'target': 'Aldric', 'total_damage': 14,
            'individual_attacks': [
                {'action': 'Longsword', 'target': 'Aldric', 'hit': True, 'damage': 9, 'hp_drained': 9,
                 'target_max_hp_after': 51},
                {'action': 'Longsword', 'target': 'Aldric', 'hit': True, 'damage': 5}]}},
        {'type': 'action', 'actor': 'Horned Devil 1', 'result': {
            'action': 'Multiattack', 'type': 'special', 'target': 'Aldric', 'total_damage': 20,
            'individual_attacks': [{'action': 'Tail', 'target': 'Aldric', 'hit': True, 'damage': 20,
                                    'condition_applied': 'Infernal Wound'}]}},
    ])
    assert logs[0]['result'] == "Multiattack on Aldric: 14 damage. Aldric's hit point maximum drops by 9 (to 51)."
    assert logs[1]['result'] == 'Multiattack on Aldric: 20 damage. Aldric has an infernal wound!'
