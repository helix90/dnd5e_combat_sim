import pytest
from controllers.results_controller import ResultsController

class MockDB:
    def __init__(self, logs, sim=None):
        self._logs = logs
        self._sim = sim or {}
    def get_combat_logs(self, sim_id):
        return self._logs
    def get_simulation(self, sim_id):
        return self._sim

def test_generate_combat_statistics_basic(monkeypatch):
    logs = [
        {'character_name': 'Hero', 'target': 'Goblin', 'action_type': 'attack', 'result': 'hit', 'damage': 5, 'round_number': 1},
        {'character_name': 'Goblin', 'target': 'Hero', 'action_type': 'attack', 'result': 'miss', 'damage': 0, 'round_number': 1},
        {'character_name': 'Hero', 'target': 'Goblin', 'action_type': 'attack', 'result': 'crit', 'damage': 10, 'round_number': 2},
        {'character_name': 'Cleric', 'target': 'Hero', 'action_type': 'spell', 'result': 'heal', 'damage': -7, 'round_number': 2},
        {'character_name': 'Goblin', 'target': 'Hero', 'action_type': 'attack', 'result': 'hit', 'damage': 3, 'round_number': 2},
        {'character_name': 'Cleric', 'target': 'Goblin', 'action_type': 'spell', 'result': 'miss', 'damage': 0, 'round_number': 3},
    ]
    rc = ResultsController()
    rc.db = MockDB(logs)
    stats = rc.generate_combat_statistics(sim_id=1)
    hero = next(s for s in stats if s['name'] == 'Hero')
    goblin = next(s for s in stats if s['name'] == 'Goblin')
    cleric = next(s for s in stats if s['name'] == 'Cleric')
    # Hero: 15 damage dealt, 3 taken, 0 spells, 1 crit, 0 miss, 0 healing
    assert hero['damage_dealt'] == 15
    assert hero['damage_taken'] == 3
    assert hero['spells_cast'] == 0
    assert hero['crits'] == 1
    assert hero['misses'] == 0
    assert hero['healing'] == 0
    # Goblin: 3 damage dealt, 15 taken, 0 spells, 0 crit, 1 miss, 0 healing
    assert goblin['damage_dealt'] == 3
    assert goblin['damage_taken'] == 15
    assert goblin['spells_cast'] == 0
    assert goblin['crits'] == 0
    assert goblin['misses'] == 1
    assert goblin['healing'] == 0
    # Cleric: 0 damage dealt, 0 taken, 2 spells, 0 crit, 1 miss, 7 healing
    assert cleric['damage_dealt'] == 0
    assert cleric['damage_taken'] == 0
    assert cleric['spells_cast'] == 2
    assert cleric['crits'] == 0
    assert cleric['misses'] == 1
    assert cleric['healing'] == 7
    # Round breakdowns
    assert hero['rounds'][1]['damage_dealt'] == 5
    assert hero['rounds'][2]['damage_dealt'] == 10
    assert goblin['rounds'][2]['damage_dealt'] == 3
    assert cleric['rounds'][2]['healing'] == 7

def test_generate_combat_statistics_empty(monkeypatch):
    rc = ResultsController()
    rc.db = MockDB([])
    stats = rc.generate_combat_statistics(sim_id=1)
    assert stats == [] 