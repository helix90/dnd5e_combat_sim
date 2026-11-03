"""Spells with several darts, rays or beams: Magic Missile, Scorching Ray and Eldritch Blast."""
import json
from unittest.mock import patch

import pytest

from models.arena import Arena, Placement
from models.character import Character
from models.combat import Combat
from models.monster import Monster
from models.monster_builder import build_monsters
from models.spell_manager import SpellManager
from models.spells import SpellAction
from utils.paths import data_path

SCORES = {'str': 10, 'dex': 14, 'con': 12, 'int': 18, 'wis': 12, 'cha': 10}

spells = SpellManager()


def wizard(level=5):
    caster = Character('Galen', level, 'Wizard', 'Human', SCORES, hp=30, ac=12, proficiency_bonus=3,
                       spell_slots={1: 4, 2: 3, 3: 2})
    for name in ('Magic Missile', 'Scorching Ray', 'Eldritch Blast', 'Fire Bolt'):
        caster.add_spell(spells.get_spell(name))
    return caster


def goblin(name='Goblin', hp=30, ac=12, **kwargs):
    return Monster(name, '1/4', hp, ac, SCORES, actions=[], **kwargs)


def d20_then(d20, other):
    """random.randint that rolls d20 for attack rolls and other for every other die."""
    return lambda a, b: d20 if b == 20 else other


# How many and how much


@pytest.mark.parametrize('name, caster_level, slot, count', [
    ('Magic Missile', 1, None, 3), ('Magic Missile', 3, 2, 4), ('Magic Missile', 5, 3, 5),
    ('Scorching Ray', 3, None, 3), ('Scorching Ray', 5, 3, 4),
    ('Eldritch Blast', 1, None, 1), ('Eldritch Blast', 5, None, 2), ('Eldritch Blast', 11, None, 3),
    ('Eldritch Blast', 17, None, 4), ('Fire Bolt', 17, None, 1),
])
def test_projectile_count(name, caster_level, slot, count):
    assert spells.get_spell(name).projectile_count(caster_level, slot) == count


def test_average_damage_counts_every_projectile():
    assert spells.get_spell('Magic Missile').average_damage() == 10.5
    assert spells.get_spell('Magic Missile').average_damage(3, 2) == 14.0
    assert spells.get_spell('Scorching Ray').average_damage() == 21.0
    assert spells.get_spell('Eldritch Blast').average_damage(5) == 11.0
    assert spells.get_spell('Fire Bolt').average_damage(5) == 11.0  # cantrip dice still scale


def test_eldritch_blast_beams_roll_one_die_each():
    with patch('random.randint', return_value=8):
        assert spells.get_spell('Eldritch Blast').calculate_damage(17) == 8
        assert spells.get_spell('Fire Bolt').calculate_damage(17) == 32


# Casting


def test_magic_missile_fires_three_darts_that_always_hit():
    caster, target = wizard(), goblin()
    with patch('random.randint', return_value=4):
        result = caster.cast_spell('Magic Missile', target)
    assert result['damage'] == 15 and result['projectiles'] == 3 and result['hits'] == 3
    assert [a['damage'] for a in result['attacks']] == [5, 5, 5]
    assert 'attack_roll' not in result['attacks'][0] and 'hit' not in result  # no attack roll to report
    assert target.hp == 15 and result['target_hp_after'] == 15


def test_upcast_magic_missile_adds_a_dart():
    caster, target = wizard(), goblin()
    with patch('random.randint', return_value=1):
        result = SpellAction(spells.get_spell('Magic Missile'), spell_slot_level=2).execute(caster, target)
    assert result['projectiles'] == 4 and result['damage'] == 8
    assert caster.spell_slots_remaining[2] == 2


def test_each_dart_is_reduced_by_resistance_on_its_own():
    caster, target = wizard(), goblin(damage_resistances=['force'])
    with patch('random.randint', return_value=4):
        result = caster.cast_spell('Magic Missile', target)
    assert result['damage'] == 6  # 5 halved is 2, three times


def test_scorching_ray_rolls_an_attack_for_each_ray():
    caster, target = wizard(), goblin(ac=15)
    rolls = iter([19, 6, 6, 2, 12, 6, 6])  # ray 1 hits (2d6), ray 2 misses, ray 3 hits (2d6)
    with patch('random.randint', side_effect=lambda a, b: next(rolls)):
        result = caster.cast_spell('Scorching Ray', target)
    assert [a['hit'] for a in result['attacks']] == [True, False, True]
    assert result['hits'] == 2 and result['hit'] is True and result['damage'] == 24


def test_darts_go_to_another_enemy_once_the_target_would_drop():
    caster, weak, other = wizard(), goblin('Weak', hp=7), goblin('Other')
    with patch('random.randint', return_value=4):
        result = SpellAction(spells.get_spell('Magic Missile')).execute(caster, weak, other_targets=[(other, {})])
    # 7 HP takes two darts on average (3.5 each); the third goes to the other goblin
    assert [a['target'] for a in result['attacks']] == ['Weak', 'Weak', 'Other']
    assert result['target'] == 'Weak, Other' and 'target_hp_after' not in result
    assert weak.hp == 0 and other.hp == 25


def test_leftover_projectiles_go_back_to_the_chosen_target():
    caster, weak, other = wizard(), goblin('Weak', hp=1), goblin('Other', hp=1)
    with patch('random.randint', return_value=4):
        result = SpellAction(spells.get_spell('Magic Missile')).execute(caster, weak, other_targets=[(other, {})])
    assert [a['target'] for a in result['attacks']] == ['Weak', 'Other', 'Weak']


def test_rays_allow_for_misses_when_splitting():
    caster, first, other = wizard(), goblin('First', hp=6, ac=19), goblin('Other')
    with patch('random.randint', side_effect=d20_then(19, 3)):
        result = SpellAction(spells.get_spell('Scorching Ray')).execute(caster, first, other_targets=[(other, {})])
    # +7 to hit against AC 19 hits 45% of the time, so 6 HP is worth two rays (3.15 each)
    assert [a['target'] for a in result['attacks']] == ['First', 'First', 'Other']


def test_cover_applies_to_every_ray_at_the_target():
    caster, first = wizard(), goblin('First', hp=50)
    with patch('random.randint', side_effect=d20_then(9, 3)):  # 9 + 7 misses AC 12 + 5
        result = SpellAction(spells.get_spell('Scorching Ray')).execute(caster, first, ac_bonus=5)
    assert {a['target_ac'] for a in result['attacks']} == {17}
    assert result['hits'] == 0 and result['damage'] == 0


# In combat


def placed(combat, creature, x, y):
    combat.battlefield.placements[creature] = Placement((x, y), combat.battlefield.placements[creature].size)


def test_combat_offers_enemies_in_range_nearest_first():
    caster, near, far, beyond = wizard(), goblin('Near'), goblin('Far'), goblin('Beyond')
    combat = Combat([caster, near, far, beyond], arena=Arena(40, 10, name='Test'))
    placed(combat, caster, 0, 0)
    placed(combat, near, 4, 0)
    placed(combat, far, 20, 0)
    placed(combat, beyond, 39, 0)  # 195 ft, out of Magic Missile's 120 ft
    targets = combat._projectile_targets(caster, spells.get_spell('Magic Missile'), far)
    assert [t.name for t, _ in targets] == ['Near']
    combat_without = Combat([caster, near, far])
    assert [t.name for t, _ in combat_without._projectile_targets(caster, spells.get_spell('Magic Missile'),
                                                                  near)] == ['Far']


def test_combat_spreads_darts_and_logs_the_hits():
    caster, weak, other = wizard(), goblin('Weak', hp=7), goblin('Other')
    combat = Combat([caster, weak, other])
    plan = {'type': 'cast_spell', 'spell': SpellAction(spells.get_spell('Scorching Ray')), 'target': weak}
    with patch('random.randint', side_effect=d20_then(19, 3)):
        result = combat._execute_action(caster, plan)
    assert result['hits'] == 3 and result['target'] == 'Weak, Other'
    combat.logger.log_action(caster, result, 1)
    assert 'Galen casts Scorching Ray on Weak, Other: 18 damage (3 of 3 hit).' in combat.format_log_for_web()


def test_fire_from_one_ray_stops_a_troll_regenerating():
    caster = wizard()
    data = next(m for m in json.load(open(data_path('monsters.json')))['monsters'] if m['name'] == 'Troll')
    [troll] = build_monsters([data])
    combat = Combat([caster, troll])
    assert troll in combat._regenerators
    plan = {'type': 'cast_spell', 'spell': SpellAction(spells.get_spell('Scorching Ray')), 'target': troll}
    rolls = iter([19, 3, 3] + [2] * 4)  # only the first ray hits
    with patch('random.randint', side_effect=lambda a, b: next(rolls)):
        result = combat._take_turn(caster, plan)
    combat._note_regeneration_damage({troll: troll.max_hp}, result)
    assert combat._regen_suppressed.get(troll) == {'fire'}
