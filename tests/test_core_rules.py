"""Natural 20s, critical hits and saving throw bonuses."""
import json
from unittest.mock import patch

from models.actions import AttackAction
from models.character import Character
from models.monster import Monster
from models.monster_builder import build_monsters
from models.rolls import attack_hits, roll_saving_throw
from models.spell_manager import SpellManager
from utils.paths import data_path

SCORES = {'str': 16, 'dex': 14, 'con': 12, 'int': 18, 'wis': 8, 'cha': 10}


def hero(**kwargs):
    return Character('Hero', 5, 'Wizard', 'Human', SCORES, hp=30, ac=12, proficiency_bonus=3,
                     spell_slots={1: 2, 2: 2}, **kwargs)


def ogre(ac=12, **kwargs):
    return Monster('Ogre', '2', 100, ac, {'str': 19, 'dex': 8, 'con': 16, 'int': 5, 'wis': 7, 'cha': 7},
                   actions=[], **kwargs)


def sword():
    return AttackAction('Longsword', '', 'Longsword', '1d8', 'slashing')


def test_a_natural_20_always_hits_and_a_natural_1_always_misses():
    assert attack_hits(20, 5, 30)
    assert not attack_hits(1, 40, 5)
    assert attack_hits(19, 30, 30) and not attack_hits(19, 29, 30)


def test_a_natural_20_is_a_critical_hit_that_doubles_the_dice():
    with patch('random.randint', side_effect=lambda a, b: 20 if b == 20 else 5):
        result = sword().execute(hero(), ogre(ac=30))
    assert result['hit'] and result['critical']
    assert result['damage'] == 5 + 5 + 3  # two d8s, STR modifier once


def test_a_natural_19_is_not_a_critical_hit():
    with patch('random.randint', side_effect=lambda a, b: 19 if b == 20 else 5):
        result = sword().execute(hero(), ogre())
    assert result['hit'] and not result['critical'] and result['damage'] == 8


def test_monster_attacks_crit_too():
    claw = AttackAction('Claw', '', 'Claw', '2d6+4', 'slashing')
    with patch('random.randint', side_effect=lambda a, b: 20 if b == 20 else 3):
        result = claw.execute(ogre(), hero())
    assert result['critical'] and result['damage'] == 4 * 3 + 4


def test_spell_attacks_crit_on_a_natural_20():
    spells = SpellManager()
    caster = hero()
    caster.add_spell(spells.get_spell('Fire Bolt'))
    caster.add_spell(spells.get_spell('Scorching Ray'))
    with patch('random.randint', side_effect=lambda a, b: 20 if b == 20 else 4):
        bolt = caster.cast_spell('Fire Bolt', ogre(ac=30))
        rays = caster.cast_spell('Scorching Ray', ogre(ac=30))
    assert bolt['critical'] and bolt['damage'] == 4 * 4  # 2d10 at level 5, doubled
    assert all(a['critical'] for a in rays['attacks']) and rays['damage'] == 3 * 4 * 4


def test_magic_missile_never_crits():
    caster = hero()
    caster.add_spell(SpellManager().get_spell('Magic Missile'))
    with patch('random.randint', return_value=4):
        result = caster.cast_spell('Magic Missile', ogre())
    assert result['damage'] == 15 and not any(a.get('critical') for a in result['attacks'])


# Saving throws


def test_characters_add_proficiency_to_their_proficient_saves():
    wizard = hero(saving_throw_proficiencies=['int', 'wis'])
    assert wizard.saving_throw_bonus('int') == 4 + 3
    assert wizard.saving_throw_bonus('wis') == -1 + 3
    assert wizard.saving_throw_bonus('dex') == 2
    assert wizard.saving_throw_bonus('dex', proficient=True) == 5  # an explicit answer still wins


def test_monsters_save_with_their_ability_modifier_or_listed_bonus():
    plain = ogre()
    assert plain.saving_throw_bonus('str') == 4 and plain.saving_throw_bonus('wis') == -2
    spawn = ogre(saving_throws={'dex': 6, 'wis': 3})
    assert spawn.saving_throw_bonus('dex') == 6 and spawn.saving_throw_bonus('wis') == 3
    assert spawn.saving_throw_bonus('con') == 3
    with patch('random.randint', return_value=10):
        save = roll_saving_throw(plain, 'str', 14)
    assert save['save_bonus'] == 4 and save['total_save'] == 14 and save['save_success']


def test_monsters_keep_their_creature_type():
    data = {m['name']: m for m in json.load(open(data_path('monsters.json')))['monsters']}
    wraith, troll = build_monsters([data['Wraith'], data['Troll']])
    assert wraith.creature_type == 'undead' and troll.creature_type == 'giant'
    assert ogre().creature_type is None
