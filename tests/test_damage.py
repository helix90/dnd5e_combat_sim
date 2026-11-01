"""Tests for damage immunities, resistances and vulnerabilities."""
from unittest.mock import patch

import pytest

from models.actions import AttackAction
from models.character import Character
from models.damage import adjust_damage, apply_damage
from models.monster import Monster
from models.spells import Spell, SpellAction

SCORES = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}


def make_monster(**defenses):
    return Monster('Target', '1', 100, 5, SCORES, **defenses)


@pytest.mark.parametrize('defenses, damage_type, expected', [
    ({}, 'slashing', 11),
    ({'damage_resistances': ['slashing']}, 'slashing', 5),
    ({'damage_resistances': ['Fire']}, 'fire', 5),
    ({'damage_immunities': ['poison'], 'damage_resistances': ['poison']}, 'poison', 0),
    ({'damage_vulnerabilities': ['bludgeoning']}, 'bludgeoning', 22),
    ({'damage_resistances': ['fire'], 'damage_vulnerabilities': ['fire']}, 'fire', 11),
    ({'damage_resistances': ['fire']}, None, 11),
])
def test_adjust_damage(defenses, damage_type, expected):
    assert adjust_damage(make_monster(**defenses), 11, damage_type) == expected


def test_apply_damage_reduces_hp_by_adjusted_amount():
    monster = make_monster(damage_resistances=['slashing'])
    assert apply_damage(monster, 11, 'slashing') == 5 and monster.hp == 95


def test_weapon_attack_against_resistant_monster():
    hero = Character('Hero', 1, 'Fighter', 'Human', SCORES, hp=10, ac=10, proficiency_bonus=2)
    sword = AttackAction(name='Longsword', description='', weapon_name='Longsword', damage_dice='1d8+3',
                         damage_type='slashing')
    wraith = make_monster(damage_resistances=['slashing'])
    with patch('random.randint', side_effect=[15, 7]):
        result = sword.execute(hero, wraith)
    assert result['damage'] == 5 and wraith.hp == 95


def test_spell_against_vulnerable_monster():
    caster = Character('Caster', 5, 'Wizard', 'Human', dict(SCORES, int=16), hp=10, ac=10, proficiency_bonus=3)
    fire_bolt = Spell(name='Fire Bolt', level=0, school='Evocation', casting_time='1 action', range='120 feet',
                      duration='Instantaneous', components={'verbal': True, 'somatic': True, 'material': False},
                      damage_dice='1d10', damage_type='fire', is_attack_spell=True)
    mummy = make_monster(damage_vulnerabilities=['fire'])
    with patch('random.randint', side_effect=[15, 3, 4]):
        result = SpellAction(fire_bolt).execute(caster, mummy)
    assert result['damage'] == 14 and mummy.hp == 86
