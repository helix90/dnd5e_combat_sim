"""Each batch run starts with fresh combatants, even when the party or monsters are already-built objects."""
from unittest.mock import patch

from controllers.batch_simulation_controller import BatchSimulationController
from models.actions import AttackAction
from models.character import Character
from models.db import DatabaseManager
from models.monster import Monster
from utils.party_loader import PartyLoader

SCORES = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}


class WoundingCombat:
    """Stands in for Combat: records each run's starting HP and slots, then wounds everyone."""
    starts = []

    def __init__(self, participants):
        self.participants = participants

    def run(self):
        WoundingCombat.starts.append({
            p.name: (p.hp, dict(getattr(p, 'spell_slots_remaining', {}))) for p in self.participants
        })
        for p in self.participants:
            p.hp = 1
            for level in getattr(p, 'spell_slots_remaining', {}):
                p.spell_slots_remaining[level] = 0
        return {'winner': 'party', 'rounds': 1, 'party_hp_remaining': 1, 'log': []}


def _run_batch(tmp_path, party, monsters, runs=3):
    controller = BatchSimulationController()
    controller.db = DatabaseManager(str(tmp_path / 'batch.db'))
    controller.db.create_session('s1')
    WoundingCombat.starts = []
    with patch('controllers.batch_simulation_controller.Combat', WoundingCombat):
        batch_id = controller.execute_batch_simulation(party, monsters, runs, 'test', 's1')
        controller.batch_threads[batch_id].join(timeout=30)
    state = controller.batch_states[batch_id]
    assert state['done'] and state['completed_runs'] == runs and not state.get('error')
    return WoundingCombat.starts


def test_already_built_combatants_are_fresh_each_run(tmp_path):
    hero = Character('Hero', 3, 'Wizard', 'Elf', SCORES, hp=20, ac=12, proficiency_bonus=2,
                     spell_slots={1: 4, 2: 2})
    bite = AttackAction(name='Bite', description='Bite', weapon_name='Bite', damage_dice='1d6',
                        damage_type='piercing')
    wolf = Monster('Wolf', '1/4', 11, 13, SCORES, actions=[bite])

    starts = _run_batch(tmp_path, [hero], [wolf])
    assert all(s['Hero'] == (20, {1: 4, 2: 2}) for s in starts)
    assert all(s['Wolf'][0] == 11 for s in starts)
    assert hero.hp == 20 and wolf.hp == 11  # the caller's objects are never used in combat


def test_party_dicts_are_fresh_each_run(tmp_path):
    party = PartyLoader.get_party_with_level(1, 5)['characters']
    monster = {'name': 'Goblin', 'cr': '1/4', 'hp': 7, 'ac': 15, 'ability_scores': SCORES}

    starts = _run_batch(tmp_path, party, [monster])
    assert all(s == starts[0] for s in starts)  # every run starts the same
    calyra = next(c for c in party if c['name'] == 'Calyra')
    assert starts[-1]['Calyra'] == (calyra['hp'], {1: 4, 2: 3, 3: 2})
