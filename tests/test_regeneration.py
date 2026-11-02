"""Tests for monster Regeneration (Troll, Vampire Spawn)."""
from models.monster_builder import build_monsters
from models.character import Character
from models.combat import Combat
from models.monster import Monster

SCORES = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}
TROLL_REGEN = {'hp': 10, 'suppressed_by': ['acid', 'fire'], 'revives_at_zero': True}
VAMPIRE_REGEN = {'hp': 10, 'suppressed_by': ['radiant'], 'revives_at_zero': False}


def make_hero():
    return Character('Hero', 5, 'Fighter', 'Human', SCORES, hp=200, ac=30, proficiency_bonus=3)


def make_troll(regen=TROLL_REGEN, hp=84):
    return Monster('Troll', '5', hp, 15, SCORES, regeneration=regen)


def troll_turn(regen=TROLL_REGEN):
    """A combat where it's the troll's turn next."""
    hero, troll = make_hero(), make_troll(regen)
    combat = Combat([hero, troll])
    combat.initiative_order = [troll, hero]
    return combat, hero, troll


def hit(combat, troll, damage, damage_type):
    """Apply an action's damage to the troll the way next_turn does."""
    before = {c: c.hp for c in combat._regenerators}
    troll.hp -= damage
    combat._note_regeneration_damage(before, {'action': 'X', 'damage': damage, 'damage_type': damage_type})


def regen_entries(combat):
    return [e['result'] for e in combat.get_combat_log()
            if e['type'] == 'action' and e['result'].get('condition') == 'regeneration']


def test_regains_hp_at_start_of_turn_capped_at_max():
    combat, _, troll = troll_turn()
    troll.hp = 50
    combat.next_turn()
    assert troll.hp == 60
    assert regen_entries(combat)[0]['description'] == 'regenerates 10 HP'

    combat, _, troll = troll_turn()
    troll.hp = 80
    combat.next_turn()
    assert troll.hp == 84


def test_no_log_entry_at_full_hp():
    combat, _, troll = troll_turn()
    combat.next_turn()
    assert troll.hp == 84 and regen_entries(combat) == []


def test_fire_stops_regeneration_for_one_turn():
    combat, _, troll = troll_turn()
    hit(combat, troll, 20, 'fire')
    combat.next_turn()
    assert troll.hp == 64
    assert "took fire damage" in regen_entries(combat)[0]['description']
    # Next turn it regenerates again
    combat.initiative_order = [troll, make_hero()]
    combat.current_turn = 0
    combat.next_turn()
    assert troll.hp == 74


def test_other_damage_does_not_stop_regeneration():
    combat, _, troll = troll_turn()
    hit(combat, troll, 20, 'slashing')
    combat.next_turn()
    assert troll.hp == 74


def test_downed_troll_gets_back_up_unless_burned():
    combat, _, troll = troll_turn()
    hit(combat, troll, 84, 'slashing')
    assert troll.hp == 0 and not combat.is_combat_over()
    combat.next_turn()
    assert troll.hp == 10
    assert regen_entries(combat)[0]['description'] == 'regenerates 10 HP and gets back up'


def test_downed_troll_dies_if_fire_hit_it():
    combat, _, troll = troll_turn()
    hit(combat, troll, 30, 'fire')
    hit(combat, troll, 54, 'slashing')
    assert troll.hp == 0 and combat.is_combat_over()


def test_downed_troll_cant_be_targeted():
    combat, hero, troll = troll_turn()
    hit(combat, troll, 84, 'slashing')
    assert combat._build_combat_state(hero)['enemies'] == []


def test_vampire_spawn_does_not_revive():
    combat, _, vampire = troll_turn(VAMPIRE_REGEN)
    hit(combat, vampire, 84, 'slashing')
    assert combat.is_combat_over()


def test_damage_types_found_in_multiattack_results():
    result = {'action': 'Multiattack', 'individual_attacks': [
        {'damage_type': 'piercing'}, {'damage_type': 'Fire'}]}
    assert Combat._damage_types(result) == {'piercing', 'fire'}


def test_troll_cant_be_killed_without_fire_or_acid():
    # The hero only has a sword, so each time the (weakened) troll goes down it gets back up
    hero, troll = make_hero(), make_troll(hp=4)
    combat = Combat([hero, troll])
    result = combat.run()
    assert result['winner'] != 'party'
    assert any('gets back up' in r['description'] for r in regen_entries(combat))


def test_monster_builder_keeps_regeneration():
    data = {'name': 'Troll', 'cr': '5', 'hp': 84, 'ac': 15, 'ability_scores': SCORES,
            'regeneration': TROLL_REGEN, 'actions': []}
    assert build_monsters([data])[0].regeneration == TROLL_REGEN


def test_wizard_burns_downed_troll_with_fire_bolt():
    from unittest.mock import patch
    from tests.test_party_attacks import SPELLS, character_data
    from models.character_builder import build_character
    calyra, troll = build_character(character_data('Calyra', 5), SPELLS), make_troll()
    combat = Combat([calyra, troll])
    combat.initiative_order = [calyra, troll]
    combat.current_round = 3  # past the opening rounds where she casts buffs
    hit(combat, troll, 84, 'slashing')
    assert combat._build_combat_state(calyra)['downed_regenerators'] == [troll]
    with patch('random.randint', return_value=15):
        combat.next_turn()
    entry = combat.get_combat_log()[-1]['result']
    assert entry['spell'] == 'Fire Bolt' and entry['target'] == 'Troll' and entry['damage'] > 0
    assert combat.is_combat_over()


def test_party_without_fire_cannot_burn_troll():
    from ai.strategy import PartyAIStrategy
    hero, troll = make_hero(), make_troll()
    combat = Combat([hero, troll])
    hit(combat, troll, 84, 'slashing')
    action = PartyAIStrategy().choose_action(hero, combat._build_combat_state(hero))
    assert action['type'] == 'defend'


def test_extra_attack_burns_troll_then_hits_next_enemy():
    from unittest.mock import patch
    from models.actions import AttackAction
    flame_tongue = AttackAction(name='Flame Tongue', description='', weapon_name='Flame Tongue',
                                damage_dice='2d6', damage_type='fire')
    fighter = Character('Fighter', 5, 'Fighter', 'Human', SCORES, hp=50, ac=30, proficiency_bonus=3,
                        actions=[flame_tongue], class_features=['Extra Attack'])
    troll, orc = make_troll(), Monster('Orc', '1/2', 15, 13, SCORES)
    combat = Combat([fighter, troll, orc])
    combat.initiative_order = [fighter, troll, orc]
    combat.current_round = 3
    hit(combat, troll, 84, 'slashing')
    # Each attack: d20 of 15 (+3 hits AC 15 and 13), then 2d6 of 3 + 3
    with patch('random.randint', side_effect=[15, 3, 3, 15, 3, 3]):
        combat.next_turn()
    result = combat.get_combat_log()[-1]['result']
    assert [a['target'] for a in result['attacks']] == ['Troll', 'Orc']
    assert troll in combat._regen_suppressed and orc.hp < 15
