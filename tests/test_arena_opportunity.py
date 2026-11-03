"""Arena phase 5: opportunity attacks, Disengage, Dash, Cunning Action and Nimble Escape."""
from unittest.mock import patch

from ai.positioning import fit_plan
from models.actions import AttackAction
from models.arena import Arena, Placement
from models.battlefield import bonus_dash, bonus_disengage, melee_reach
from models.buffs import create_paralyzed_condition
from models.character import Character
from models.combat import Combat
from models.db import DatabaseManager
from models.monster import Monster

SCORES = {'str': 14, 'dex': 14, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}


def sword(**kwargs):
    return AttackAction('Longsword', '', 'Longsword', '1d8+2', 'slashing', hit_bonus=5, **kwargs)


def bow():
    return AttackAction('Shortbow', '', 'Shortbow', '1d6+2', 'piercing', hit_bonus=4,
                        weapon_type='ranged', range=[80, 320])


def hero(name='Hero', actions=None, character_class='Fighter', hp=30, features=None):
    h = Character(name, 1, character_class, 'Human', SCORES, hp=hp, ac=12, proficiency_bonus=2,
                  actions=actions if actions is not None else [sword()])
    h.class_features = features or []
    return h


def monster(name='Orc', actions=None, hp=15, abilities=None):
    return Monster(name, '1/2', hp, 13, SCORES, actions=actions if actions is not None else [sword()],
                   special_abilities=abilities or [])


def fight(*creatures):
    return Combat(list(creatures), arena=Arena(30, 20, name='Test'))


def put(combat, creature, x, y):
    size = combat.battlefield.placements[creature].size
    combat.battlefield.placements[creature] = Placement((x, y), size)


def plan_for(combat, creature, plan):
    return fit_plan(creature, plan, combat._build_combat_state(creature))


def rolls(value):
    """Every d20 and damage die rolls `value`."""
    return patch('random.randint', return_value=value)


def line(x0, x1, y=5):
    step = 1 if x1 >= x0 else -1
    return [(x, y) for x in range(x0, x1 + step, step)]


def opportunity_entries(combat):
    return [e for e in combat.get_combat_log() if e['result'].get('reaction') == 'Opportunity Attack']


# Who gets an opportunity attack


def test_leaving_reach_provokes_at_the_last_square_in_reach():
    mover, orc = hero(), monster()
    combat = fight(mover, orc)
    put(combat, mover, 5, 5)
    put(combat, orc, 6, 5)
    assert combat.battlefield.provoked(mover, line(5, 2)) == [(0, orc)]
    # Moving around the orc without leaving its reach doesn't provoke
    assert combat.battlefield.provoked(mover, [(5, 5), (5, 6), (6, 6)]) == []
    # Neither does walking up to it
    put(combat, mover, 2, 5)
    assert combat.battlefield.provoked(mover, line(2, 5)) == []


def test_reach_weapons_provoke_further_out():
    mover = hero()
    giant = monster('Giant', actions=[sword(reach=10)])
    combat = fight(mover, giant)
    put(combat, mover, 5, 5)
    put(combat, giant, 6, 5)
    assert melee_reach(giant) == 10
    # Still within 10 ft at (4, 5); leaves reach stepping to (3, 5)
    assert combat.battlefield.provoked(mover, line(5, 2)) == [(1, giant)]


def test_enemies_that_cannot_react_do_not_provoke():
    mover, orc, archer = hero(), monster(), monster('Archer', actions=[bow()])
    paralyzed = monster('Paralyzed')
    combat = fight(mover, orc, archer, paralyzed)
    put(combat, mover, 5, 5)
    put(combat, orc, 6, 5)
    put(combat, archer, 6, 6)
    put(combat, paralyzed, 6, 4)
    paralyzed.buffs.add_buff(create_paralyzed_condition('Hero', 'con', 10))
    # The archer has no melee attack and the paralyzed orc is incapacitated
    assert combat.battlefield.provoked(mover, line(5, 2)) == [(0, orc)]
    combat.battlefield.reacted.add(orc)
    assert combat.battlefield.provoked(mover, line(5, 2)) == []


# Combat


def test_moving_away_draws_an_opportunity_attack():
    mover, orc = hero(), monster()
    combat = fight(mover, orc)
    put(combat, mover, 5, 5)
    put(combat, orc, 6, 5)
    with rolls(8):
        result = combat._take_turn(mover, {'type': 'defend', 'move_to': (2, 5)})
    assert result['movement']['feet'] == 15 and result['movement']['provoked'] == ['Orc']
    [entry] = opportunity_entries(combat)
    assert entry['actor'] == 'Orc' and entry['result']['target'] == 'Hero'
    assert entry['result']['hit'] and mover.hp == 30 - 10   # every die rolls 8: 1d8+2 = 10
    assert orc in combat.battlefield.reacted
    # One reaction a round: moving away again doesn't provoke
    put(combat, mover, 5, 5)
    combat._take_turn(mover, {'type': 'defend', 'move_to': (2, 5)})
    assert len(opportunity_entries(combat)) == 1


def test_reaction_comes_back_at_the_start_of_the_creatures_turn():
    mover, orc = hero(), monster()
    combat = fight(mover, orc)
    combat.initiative_order = [orc, mover]
    combat.current_turn = 0
    combat.battlefield.reacted.add(orc)
    assert combat.next_turn() is orc
    assert orc not in combat.battlefield.reacted


def test_an_opportunity_attack_that_drops_the_mover_ends_its_move():
    mover, orc = hero(hp=5), monster()
    combat = fight(mover, orc)
    put(combat, mover, 5, 5)
    put(combat, orc, 6, 5)
    target = monster('Far')
    with rolls(8):
        result = combat._take_turn(mover, {'type': 'attack', 'action': mover.actions[0], 'target': target,
                                           'move_to': (2, 5)})
    assert not mover.is_alive()
    assert result['reason'] == 'downed' and result['movement']['stopped']
    assert result['movement']['feet'] == 0 and combat.battlefield.position(mover) == (5, 5)


def test_disengage_avoids_opportunity_attacks():
    mover, orc = hero(), monster()
    combat = fight(mover, orc)
    put(combat, mover, 5, 5)
    put(combat, orc, 6, 5)
    result = combat._take_turn(mover, {'type': 'disengage', 'move_to': (2, 5)})
    assert result['type'] == 'disengage' and result['movement']['feet'] == 15
    assert not opportunity_entries(combat) and mover.hp == 30


def test_bonus_action_disengage_needs_the_feature():
    fighter, goblin, orc = hero(), monster('Goblin', abilities=['Nimble Escape']), monster()
    combat = fight(fighter, goblin, orc)
    put(combat, orc, 6, 5)
    put(combat, goblin, 5, 5)
    put(combat, fighter, 4, 5)
    # The goblin slips away from the fighter
    combat._take_turn(goblin, {'type': 'defend', 'move_to': (8, 5), 'bonus_action': 'Disengage'})
    assert not opportunity_entries(combat)
    # The fighter can't: the orc gets its attack
    put(combat, fighter, 7, 5)
    put(combat, goblin, 15, 15)
    result = combat._take_turn(fighter, {'type': 'defend', 'move_to': (9, 5), 'bonus_action': 'Disengage'})
    assert 'bonus_action' not in result and len(opportunity_entries(combat)) == 1


def test_bonus_action_features():
    rogue, goblin, fighter = hero(features=['Cunning Action']), monster(abilities=['Nimble Escape']), hero()
    assert bonus_disengage(rogue) == 'Cunning Action' and bonus_dash(rogue) == 'Cunning Action'
    assert bonus_disengage(goblin) == 'Nimble Escape' and bonus_dash(goblin) is None
    assert bonus_disengage(fighter) is None and bonus_dash(fighter) is None


def test_bonus_action_dash_doubles_movement_and_still_attacks():
    rogue, orc = hero('Rogue', features=['Cunning Action'], character_class='Rogue'), monster()
    combat = fight(rogue, orc)
    put(combat, rogue, 0, 5)
    put(combat, orc, 11, 5)   # 55 ft away: out of reach with a 30-ft move
    plan = plan_for(combat, rogue, {'type': 'attack', 'action': rogue.actions[0], 'target': orc})
    assert plan['type'] == 'attack' and plan['bonus_action'] == 'Dash'
    assert combat.battlefield.distance(rogue, orc, plan['move_to']) == 5
    with rolls(10):
        result = combat._take_turn(rogue, plan)
    assert result['movement']['feet'] == 50 and result['hit']
    assert result['bonus_action'] == {'action': 'Dash', 'feature': 'Cunning Action'}


# AI


def test_archer_in_melee_stays_and_shoots_rather_than_provoke():
    ranger, orc = hero('Ranger', actions=[bow()], character_class='Ranger'), monster()
    combat = fight(ranger, orc)
    put(combat, ranger, 5, 5)
    put(combat, orc, 6, 5)
    plan = plan_for(combat, ranger, {'type': 'attack', 'action': ranger.actions[0], 'target': orc})
    assert plan['action'].name == 'Shortbow' and 'move_to' not in plan


def test_nimble_goblin_disengages_and_shoots():
    fighter = hero()
    dagger = AttackAction('Dagger', '', 'Dagger', '1d2', 'piercing', hit_bonus=0)
    goblin = monster('Goblin', actions=[dagger, bow()], abilities=['Nimble Escape'])
    combat = fight(fighter, goblin)
    put(combat, fighter, 5, 5)
    put(combat, goblin, 6, 5)
    plan = plan_for(combat, goblin, {'type': 'attack', 'action': goblin.actions[1], 'target': fighter})
    assert plan['action'].name == 'Shortbow' and plan['bonus_action'] == 'Disengage'
    assert combat.battlefield.distance(goblin, fighter, plan['move_to']) > 5
    combat._take_turn(goblin, plan)
    assert not opportunity_entries(combat)


def test_melee_monster_weighs_opportunity_attacks_when_switching_targets():
    fighter, wizard = hero('Fighter'), hero('Wizard', character_class='Wizard', hp=30)
    orc = monster()
    combat = fight(fighter, wizard, orc)
    put(combat, orc, 5, 5)
    put(combat, fighter, 4, 5)
    put(combat, wizard, 10, 5)
    # Reaching the wizard means leaving the fighter's reach; the wizard isn't worth that
    plan = plan_for(combat, orc, {'type': 'attack', 'action': orc.actions[0], 'target': wizard})
    assert plan['target'] is fighter and 'move_to' not in plan
    # With the fighter's reaction spent, the orc goes for the wizard
    combat.battlefield.reacted.add(fighter)
    plan = plan_for(combat, orc, {'type': 'attack', 'action': orc.actions[0], 'target': wizard})
    assert plan['target'] is wizard and 'move_to' in plan


# Logs


def test_logs_describe_opportunity_attacks_and_bonus_actions():
    mover, orc = hero(), monster()
    goblin = monster('Goblin', abilities=['Nimble Escape'])
    combat = fight(mover, orc, goblin)
    put(combat, mover, 5, 5)
    put(combat, orc, 6, 5)
    put(combat, goblin, 4, 5)
    with rolls(8):
        combat.logger.log_action(mover, combat._take_turn(mover, {'type': 'defend', 'move_to': (5, 8)}), 1)
        put(combat, goblin, 6, 6)
        put(combat, mover, 6, 7)
        combat.battlefield.reacted.discard(mover)
        combat.logger.log_action(goblin, combat._take_turn(goblin, {'type': 'defend', 'move_to': (6, 2),
                                                                    'bonus_action': 'Disengage'}), 1)
    web = combat.format_log_for_web()
    assert any(l.startswith('Opportunity Attack: Orc uses Longsword on Hero: 10 damage') for l in web), web
    assert any('Goblin uses Nimble Escape to Disengage. Goblin moves' in l for l in web), web
    stored = DatabaseManager.__new__(DatabaseManager)._convert_combat_log_format(combat.get_combat_log())
    texts = [entry['result'] for entry in stored]
    assert any(t.startswith('Opportunity Attack: Hit for 10 damage') for t in texts), texts
    assert any(t.startswith('Nimble Escape: disengages; moves') for t in texts), texts
