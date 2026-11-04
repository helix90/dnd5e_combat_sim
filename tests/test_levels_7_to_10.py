"""Parties at levels 7-10: the character data, casting with higher slots, the 4th- and 5th-level
spells (Ice Storm, Blight, Greater Invisibility, Cone of Cold, Flame Strike, Mass Cure Wounds,
Hold Monster) and the class features that arrive (Brutal Critical, Feral Instinct, Dueling,
Empowered Evocation)."""
import copy
import json
import random
from unittest.mock import patch

import pytest

from ai.strategy import PartyAIStrategy
from models import concentration
from models.actions import AttackAction
from models.buffs import is_paralyzed
from models.character import Character
from models.character_builder import build_character, build_party
from models.combat import Combat
from models.monster import Monster
from models.monster_builder import build_monsters
from models.spell_manager import SpellManager
from models.spells import SpellAction
from utils.party_loader import PartyLoader
from utils.paths import data_path

SPELLS = SpellManager()
CHARACTERS = {entry['level']: {c['name']: c for c in entry['party']}
              for entry in json.load(open(data_path('characters.json')))}
MONSTERS = {m['name']: m for m in json.load(open(data_path('monsters.json')))['monsters']}
SCORES = {'str': 16, 'dex': 14, 'con': 14, 'int': 18, 'wis': 16, 'cha': 16}


def weapon(name='Longsword', dice='1d8', kind='melee', damage_type='slashing', reach=5):
    return AttackAction(name, '', name, dice, damage_type, weapon_type=kind, reach=reach)


def hero(cls='Wizard', spells=(), slots=None, level=9, features=(), hp=50, actions=None):
    character = Character('Hero', level, cls, 'Human', SCORES, hp=hp, ac=12, proficiency_bonus=4,
                          spell_slots=slots or {}, actions=actions or [weapon()], class_features=list(features))
    for name in spells:
        character.add_spell(SPELLS.get_spell(name))
    return character


def foe(name='Ogre', hp=59, kind=None, wis=10, immune=(), ac=10):
    scores = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': wis, 'cha': 10}
    return Monster(name, '2', hp, ac, scores, actions=[weapon('Club', '1d6')], creature_type=kind,
                   damage_immunities=list(immune))


def most(a, b):
    return b


# The character data


def test_every_character_has_levels_1_to_10():
    assert sorted(CHARACTERS) == list(range(1, 11))
    for level in range(7, 11):
        assert set(CHARACTERS[level]) == set(CHARACTERS[6])
        for character in CHARACTERS[level].values():
            assert character['level'] == level
            assert character['hp'] > CHARACTERS[level - 1][character['name']]['hp']
            assert character['proficiency_bonus'] == (4 if level >= 9 else 3)


@pytest.mark.parametrize('party_id', range(1, 7))
def test_every_party_loads_at_levels_7_to_10(party_id):
    for level in range(7, 11):
        party = PartyLoader.get_party_with_level(party_id, level)
        assert party['level'] == level and all(c['level'] == level for c in party['characters'])


def test_spell_slots_follow_the_class_tables():
    assert CHARACTERS[7]['Calyra']['spell_slots'] == {'1': 4, '2': 3, '3': 3, '4': 1}
    assert CHARACTERS[10]['Calyra']['spell_slots'] == {'1': 4, '2': 3, '3': 3, '4': 3, '5': 2}
    assert CHARACTERS[7]['Davos']['spell_slots'] == {'4': 2}     # pact magic: all slots one level
    assert CHARACTERS[9]['Davos']['spell_slots'] == {'5': 2}
    assert CHARACTERS[9]['Sir Cedric']['spell_slots'] == {'1': 4, '2': 3, '3': 2}
    assert CHARACTERS[8]['Thorn']['spell_slots'] == {'1': 4, '2': 3}


def test_features_and_ability_scores_grow():
    assert 'Sneak Attack (4d6)' in CHARACTERS[7]['Dax']['class_features']
    assert build_character(CHARACTERS[9]['Dax']).sneak_attack_dice() == '5d6'
    assert 'Ki (10 points)' in CHARACTERS[10]['Jax']['class_features']
    assert 'Lay on Hands (45)' in CHARACTERS[9]['Rhea']['class_features']
    assert 'Brutal Critical (1 die)' in CHARACTERS[9]['Grom']['class_features']
    assert 'Destroy Undead (CR 1)' in CHARACTERS[8]['Elowen']['class_features']
    assert 'Evasion' in CHARACTERS[7]['Shade']['class_features']
    assert CHARACTERS[8]['Calyra']['ability_scores']['int'] == 20
    assert CHARACTERS[8]['Jax']['ac'] == CHARACTERS[7]['Jax']['ac'] + 1   # DEX 20 with Unarmored Defense
    # A rogue's second Ability Score Improvement at 10th raises CON: a hit point more for every level
    assert CHARACTERS[10]['Dax']['hp'] - CHARACTERS[9]['Dax']['hp'] == 6 + 10
    assert 'Hold Monster' in CHARACTERS[9]['Galen']['spell_list']


# Higher slots


def test_a_higher_slot_adds_dice():
    fireball = SPELLS.get_spell('Fireball')
    assert fireball.upcast_dice(5) == '2d6' and fireball.upcast_dice(3) is None
    with patch('random.randint', side_effect=most):
        assert fireball.calculate_damage(9, slot_level=5) == 60
    assert SPELLS.get_spell('Spiritual Weapon').upcast_dice(4) == '1d8'   # 1d8 per two levels
    assert SPELLS.get_spell('Spiritual Weapon').upcast_dice(3) is None


def test_healing_with_a_higher_slot():
    healer = hero('Cleric', ['Cure Wounds'], slots={3: 1})
    ally = hero(hp=60)
    ally.hp = 1
    with patch('random.randint', side_effect=most):
        result = SpellAction(SPELLS.get_spell('Cure Wounds'), spell_slot_level=3).execute(healer, ally)
    assert result['healing'] == 24 + 3 and healer.spell_slots_remaining[3] == 0


def test_a_warlock_with_only_higher_slots_still_casts():
    warlock = hero('Warlock', ['Fireball', 'Eldritch Blast'], slots={4: 2})
    plan = PartyAIStrategy().choose_action(warlock, {'allies': [warlock], 'enemies': [foe(), foe('Orc')], 'round': 1})
    assert plan['spell'].spell.name == 'Fireball' and plan['spell'].spell_slot_level == 4


def test_a_healer_out_of_low_slots_heals_with_a_higher_one():
    healer = hero('Cleric', ['Cure Wounds'], slots={1: 0, 2: 1})
    ally = hero(hp=60)
    ally.hp = 5
    plan = PartyAIStrategy().choose_action(healer, {'allies': [healer, ally], 'enemies': [foe()], 'round': 3})
    assert plan['spell'].spell.name == 'Cure Wounds' and plan['spell'].spell_slot_level == 2


def test_moonbeam_and_spiritual_weapon_remember_their_slot():
    druid = hero('Druid', ['Moonbeam'], slots={4: 1})
    target = foe()
    SpellAction(SPELLS.get_spell('Moonbeam'), spell_slot_level=4).execute(druid, target)
    beam = next(b for b in target.buffs.active_buffs if 'moonbeam' in b.metadata)
    assert beam.metadata['moonbeam']['dice'] == '4d10'
    cleric = hero('Cleric', ['Spiritual Weapon'], slots={4: 1})
    SpellAction(SPELLS.get_spell('Spiritual Weapon'), spell_slot_level=4).execute(cleric, foe())
    summoned = next(b for b in cleric.buffs.active_buffs if b.name == 'Spiritual Weapon')
    assert summoned.metadata['spiritual_weapon_dice'] == '2d8'


def test_call_lightnings_later_bolts_keep_the_slot():
    druid = hero('Druid', ['Call Lightning'], slots={5: 1})
    SpellAction(SPELLS.get_spell('Call Lightning'), spell_slot_level=5).execute(druid, [foe(), foe('Orc')])
    plan = PartyAIStrategy()._effect_plan(druid, SPELLS.get_spell('Call Lightning'), [foe()], free=True)
    assert plan['spell'].spell_slot_level == 5 and plan['spell'].free


# The new spells


def test_blight_does_nothing_to_undead_and_the_ai_knows_it():
    wizard = hero('Wizard', ['Blight'], slots={4: 1})
    skeleton = foe('Skeleton', kind='undead')
    result = SpellAction(SPELLS.get_spell('Blight'), spell_slot_level=4).execute(wizard, skeleton)
    assert result['damage'] == 0 and result.get('no_effect') and skeleton.hp == skeleton.max_hp
    wizard = hero('Wizard', ['Blight', 'Fire Bolt'], slots={4: 1})
    plan = PartyAIStrategy().choose_action(wizard, {'allies': [wizard], 'enemies': [foe('Wight', kind='undead')],
                                                    'round': 1})
    assert plan['spell'].spell.name == 'Fire Bolt'


def test_flame_strikes_radiant_half_still_hurts_a_fire_immune_creature():
    cleric = hero('Cleric', ['Flame Strike'], slots={5: 1})
    hound = foe('Hell Hound', hp=100, immune=['fire'])
    with patch('random.randint', side_effect=most), patch('models.spells.roll_saving_throw',
                                                          return_value={'save_success': False, 'total_save': 1}):
        result = SpellAction(SPELLS.get_spell('Flame Strike'), spell_slot_level=5).execute(cleric, [hound, foe()])
    assert result['target_results'][0]['damage'] == 24 and hound.hp == 76   # the 4d6 radiant only


def test_ice_storm_deals_both_parts():
    wizard = hero('Wizard', ['Ice Storm'], slots={4: 1})
    with patch('random.randint', side_effect=most), patch('models.spells.roll_saving_throw',
                                                          return_value={'save_success': False, 'total_save': 1}):
        result = SpellAction(SPELLS.get_spell('Ice Storm'), spell_slot_level=4).execute(wizard, [foe(), foe('Orc')])
    assert [r['damage'] for r in result['target_results']] == [16 + 24, 16 + 24]


def test_mass_cure_wounds_heals_the_hurt_allies():
    healer = hero('Cleric', ['Mass Cure Wounds', 'Cure Wounds'], slots={1: 2, 5: 1})
    allies = [hero(hp=60) for _ in range(3)]
    for ally in allies:
        ally.hp = 5
    plan = PartyAIStrategy().choose_action(healer, {'allies': [healer] + allies, 'enemies': [foe()], 'round': 3})
    assert plan['spell'].spell.name == 'Mass Cure Wounds' and len(plan['target']) == 3
    result = plan['spell'].execute(healer, plan['target'])
    assert all(ally.hp > 5 for ally in allies) and len(result['target_results']) == 3


def test_hold_monster_paralyzes_until_concentration_ends():
    wizard = hero('Wizard', ['Hold Monster'], slots={5: 1})
    ogre = foe()
    with patch('models.spell_effects.roll_saving_throw', return_value={'save_success': False, 'total_save': 1}):
        result = SpellAction(SPELLS.get_spell('Hold Monster'), spell_slot_level=5).execute(wizard, ogre)
    assert result['conditions_applied'] == ['Ogre'] and is_paralyzed(ogre)
    assert concentration.concentrating_on(wizard) == 'Hold Monster'
    concentration.end(wizard)
    assert not is_paralyzed(ogre)
    zombie = foe('Zombie', kind='undead')
    result = SpellAction(SPELLS.get_spell('Hold Monster'), spell_slot_level=5).execute(hero(slots={5: 1}), zombie)
    assert result.get('no_effect') and not is_paralyzed(zombie)


def test_the_ai_holds_a_big_monster_that_will_likely_fail():
    wizard = hero('Wizard', ['Hold Monster', 'Fire Bolt'], slots={5: 1})
    plan = PartyAIStrategy().choose_action(wizard, {'allies': [wizard], 'enemies': [foe(wis=6)], 'round': 1})
    assert plan['spell'].spell.name == 'Hold Monster'
    plan = PartyAIStrategy().choose_action(wizard, {'allies': [wizard], 'enemies': [foe('Lich', kind='undead')],
                                                    'round': 1})
    assert plan['spell'].spell.name != 'Hold Monster'


def test_greater_invisibility_gives_advantage_and_disadvantage():
    bard = hero('Bard', ['Greater Invisibility'], slots={4: 1})
    fighter = hero(hp=80)
    SpellAction(SPELLS.get_spell('Greater Invisibility'), spell_slot_level=4).execute(bard, fighter)
    assert fighter.buffs.grants('advantage', 'attack_rolls') and fighter.buffs.grants('disadvantage', 'attacks_against')


# Class features


def test_brutal_critical_adds_a_die_to_melee_crits():
    barbarian = hero('Barbarian', features=['Brutal Critical (1 die)'])
    axe = weapon('Greataxe', '1d12')
    with patch('random.randint', side_effect=most):
        assert axe.damage_roll(barbarian, critical=True) == 36 + 3
        assert weapon('Longbow', '1d8', kind='ranged', reach=None).damage_roll(barbarian, critical=True) == 16 + 2


def test_feral_instinct_rolls_initiative_twice():
    rolls = iter([3, 17])
    with patch('random.randint', side_effect=lambda a, b: next(rolls)):
        assert hero('Barbarian', features=['Feral Instinct']).roll_initiative() == 17 + 2


def test_dueling_is_for_one_handed_melee_weapons():
    fighter = hero('Fighter', features=['Fighting Style: Dueling'])
    assert fighter.weapon_damage_bonus(weapon('Longsword')) == 2
    assert fighter.weapon_damage_bonus(weapon('Greataxe', '1d12')) == 0
    assert fighter.weapon_damage_bonus(weapon('Javelin', '1d6')) == 0


def test_empowered_evocation_adds_int_to_evocation_damage():
    wizard = hero('Wizard', ['Fire Bolt'], features=['Empowered Evocation'], level=10)
    with patch('random.randint', side_effect=most):
        assert SpellAction(SPELLS.get_spell('Fire Bolt')).roll_damage(wizard) == 20 + 4
        assert SpellAction(SPELLS.get_spell('Fire Bolt')).roll_damage(hero('Wizard', level=10)) == 20


# Whole fights


@pytest.mark.parametrize('party_id', range(1, 7))
def test_level_10_parties_fight_to_the_end(party_id):
    random.seed(party_id)
    party = build_party(PartyLoader.get_party_with_level(party_id, 10)['characters'], SPELLS)
    monsters = []
    for name, count in (('Young Dragon', 1), ('Troll', 2), ('Wraith', 1)):
        for i in range(count):
            data = copy.deepcopy(MONSTERS[name])
            data['name'] = f"{name} {i + 1}"
            monsters.append(data)
    result = Combat(party + build_monsters(monsters)).run()
    assert result['winner'] in ('party', 'monsters')


def test_the_party_page_offers_levels_up_to_10():
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        page = client.get('/party').get_data(as_text=True)
        assert '<option value="10"' in page and '<option value="11"' not in page
        client.post('/party', data={'party_id': '2', 'party_level': '9'})
        with client.session_transaction() as s:
            assert s['selected_party_level'] == 9
