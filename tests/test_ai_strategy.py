import pytest
from ai.strategy import PartyAIStrategy, MonsterAIStrategy

class DummyCombatant:
    def __init__(self, name, hp, max_hp, level=1, is_alive=True, special_abilities=None, class_features=None, actions=None, spells=None):
        self.name = name
        self.hp = hp
        self.max_hp = max_hp
        self.level = level
        self.is_alive = lambda: is_alive
        self.special_abilities = special_abilities or []
        self.class_features = class_features or []
        self.actions = actions or []
        self.spells = spells or {}

class DummyAction:
    def __init__(self, action_type):
        self.action_type = action_type
        self.level = 0
        self.name = action_type
    def hit_bonus(self, combatant=None):
        return 0

class DummySpell:
    def __init__(self, name, healing=False, damage_dice=None, level=0, description="A spell"):
        self.name = name
        self.healing = healing
        self.damage_dice = damage_dice
        self.level = level
        self.description = description

@pytest.fixture
def party_ai():
    return PartyAIStrategy()

@pytest.fixture
def monster_ai():
    return MonsterAIStrategy()

def test_party_ai_heals_low_hp_ally(party_ai):
    healer = DummyCombatant('Cleric', 20, 40, spells={'Heal': DummySpell('Heal', healing=True)})
    ally1 = DummyCombatant('Fighter', 5, 40)
    ally2 = DummyCombatant('Rogue', 30, 40)
    combat_state = {'allies': [healer, ally1, ally2], 'enemies': []}
    action = party_ai.choose_action(healer, combat_state)
    assert action['type'] == 'cast_spell'
    assert action['target'] == ally1

def test_party_ai_focuses_on_dangerous_enemy(party_ai):
    attacker = DummyCombatant('Wizard', 30, 30, actions=[DummyAction('attack')])
    enemy1 = DummyCombatant('Orc', 20, 20, level=2)
    enemy2 = DummyCombatant('Dragon', 100, 100, level=10, special_abilities=['Fire Breath'])
    combat_state = {'allies': [attacker], 'enemies': [enemy1, enemy2]}
    action = party_ai.choose_action(attacker, combat_state)
    assert action['type'] == 'attack'
    assert action['target'] == enemy2

def test_party_ai_default_defend(party_ai):
    pc = DummyCombatant('Bard', 10, 30)
    combat_state = {'allies': [pc], 'enemies': []}
    action = party_ai.choose_action(pc, combat_state)
    assert action['type'] == 'defend'

def test_monster_ai_uses_special(monster_ai):
    monster = DummyCombatant('Troll', 50, 50, actions=[DummyAction('special'), DummyAction('attack')])
    enemy = DummyCombatant('Hero', 40, 40)
    combat_state = {'enemies': [enemy]}
    action = monster_ai.choose_action(monster, combat_state)
    assert action['type'] == 'special'

def test_monster_ai_spreads_damage(monster_ai):
    monster = DummyCombatant('Goblin', 10, 10, actions=[DummyAction('attack')])
    enemy1 = DummyCombatant('Hero1', 40, 40)
    enemy2 = DummyCombatant('Hero2', 5, 40)
    combat_state = {'enemies': [enemy1, enemy2]}
    action = monster_ai.choose_action(monster, combat_state)
    assert action['target'] == enemy2

def test_threat_assessment_party(monster_ai, party_ai):
    c = DummyCombatant('Boss', 100, 100, level=10, special_abilities=['Stomp'])
    state = {}
    assert party_ai.threat_assessment(c, state) > 10
    assert monster_ai.threat_assessment(c, state) > 10

def test_opportunity_cost_analysis(monster_ai, party_ai):
    c = DummyCombatant('Mage', 20, 20)
    spell = DummySpell('Fireball', damage_dice='8d6', level=3)
    state = {'encounters_remaining': 5}
    assert party_ai.opportunity_cost_analysis(c, spell, state) > 1
    attack = DummyAction('attack')
    assert monster_ai.opportunity_cost_analysis(c, attack, state) == 1.0
    special = DummyAction('special')
    assert monster_ai.opportunity_cost_analysis(c, special, state) == 0.5

def test_no_valid_targets(monster_ai):
    monster = DummyCombatant('Zombie', 10, 10, actions=[DummyAction('attack')])
    combat_state = {'enemies': []}
    action = monster_ai.choose_action(monster, combat_state)
    assert action['type'] == 'wait' 