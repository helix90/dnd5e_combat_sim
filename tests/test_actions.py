"""
Unit tests for the Action and AttackAction system.
"""
import pytest
from models.actions import Action, AttackAction
from models.character import Character
from models.monster import Monster

class DummyTarget:
    def __init__(self, ac):
        self.ac = ac

class DummyAttacker:
    def __init__(self, str_mod=2, dex_mod=1, attack_bonus=3):
        self._str_mod = str_mod
        self._dex_mod = dex_mod
        self._attack_bonus = attack_bonus
    def ability_modifier(self, ability):
        if ability == 'str':
            return self._str_mod
        if ability == 'dex':
            return self._dex_mod
        return 0
    def attack_bonus(self, weapon_type='melee'):
        return self._attack_bonus


def test_action_base_execute_raises():
    action = Action(action_type="attack", name="Test", description="desc")
    with pytest.raises(NotImplementedError):
        action.execute(None, None)


def test_attack_action_hit_and_miss(monkeypatch):
    # Always roll 10 for d20
    monkeypatch.setattr('random.randint', lambda a, b: 10 if (a, b) == (1, 20) else 4)
    attacker = DummyAttacker(str_mod=2, attack_bonus=5)
    target = DummyTarget(ac=15)
    action = AttackAction(
        name="Sword Attack",
        description="Slash with a sword.",
        weapon_name="Longsword",
        damage_dice="1d8",
        damage_type="slashing"
    )
    # 10 (roll) + 5 (bonus) = 15 vs AC 15: hit
    result = action.execute(attacker, target)
    assert result['hit'] is True
    assert result['attack_roll'] == 10
    assert result['hit_bonus'] == 5
    assert result['total_attack'] == 15
    assert result['damage'] == 4 + 2  # 4 (fixed roll) + 2 (str mod)
    # Now test miss
    target2 = DummyTarget(ac=16)
    result2 = action.execute(attacker, target2)
    assert result2['hit'] is False
    assert result2['damage'] == 0


def test_attack_action_damage_roll(monkeypatch):
    # Always roll 3 for d8
    monkeypatch.setattr('random.randint', lambda a, b: 3)
    attacker = DummyAttacker(str_mod=2)
    action = AttackAction(
        name="Sword Attack",
        description="Slash with a sword.",
        weapon_name="Longsword",
        damage_dice="2d8",
        damage_type="slashing"
    )
    dmg = action.damage_roll(attacker)
    assert dmg == 3 + 3 + 2  # 2d8 (3,3) + 2 (str mod)


def test_attack_action_ranged_and_finesse(monkeypatch):
    monkeypatch.setattr('random.randint', lambda a, b: 2)
    attacker = DummyAttacker(str_mod=1, dex_mod=4)
    # Bow (ranged): uses dex
    bow = AttackAction(
        name="Bow Attack",
        description="Shoot with a bow.",
        weapon_name="Shortbow",
        damage_dice="1d6",
        damage_type="piercing"
    )
    dmg = bow.damage_roll(attacker)
    assert dmg == 2 + 4
    # Dagger (finesse): uses max(str, dex)
    dagger = AttackAction(
        name="Dagger Attack",
        description="Stab with a dagger.",
        weapon_name="Dagger",
        damage_dice="1d4",
        damage_type="piercing"
    )
    dmg2 = dagger.damage_roll(attacker)
    assert dmg2 == 2 + 4


def test_attack_action_applies_damage_to_target(monkeypatch):
    # Always roll 10 for d20 (hit), 4 for damage
    monkeypatch.setattr('random.randint', lambda a, b: 10 if (a, b) == (1, 20) else 4)
    attacker = DummyAttacker(str_mod=2, attack_bonus=5)
    class TargetWithHP:
        def __init__(self, ac, hp):
            self.ac = ac
            self.hp = hp
    target = TargetWithHP(ac=12, hp=15)
    action = AttackAction(
        name="Sword Attack",
        description="Slash with a sword.",
        weapon_name="Longsword",
        damage_dice="1d8",
        damage_type="slashing"
    )
    result = action.execute(attacker, target)
    assert result['hit'] is True
    assert result['damage'] == 4 + 2  # 4 (fixed roll) + 2 (str mod)
    assert target.hp == 15 - (4 + 2)
    # Miss case: HP should not change
    target2 = TargetWithHP(ac=20, hp=15)
    result2 = action.execute(attacker, target2)
    assert result2['hit'] is False
    assert result2['damage'] == 0
    assert target2.hp == 15


def test_character_actions_execute(monkeypatch):
    monkeypatch.setattr('random.randint', lambda a, b: 12 if (a, b) == (1, 20) else 5)
    char = Character(
        name="Hero",
        level=3,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 16, 'dex': 14, 'con': 12, 'int': 10, 'wis': 10, 'cha': 10},
        hp=20,
        ac=16,
        proficiency_bonus=2
    )
    monster = Monster(
        name="Goblin",
        challenge_rating="1/4",
        hp=7,
        ac=15,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )
    sword_action = next(a for a in char.actions if a.name == "Sword Attack")
    result = sword_action.execute(char, monster)
    assert result['hit'] is True
    assert result['damage'] == 5 + 3  # 5 (fixed roll) + 3 (str mod)
    # Integration: character attacks monster with high AC (miss)
    monster.ac = 20
    result2 = sword_action.execute(char, monster)
    assert result2['hit'] is False
    assert result2['damage'] == 0


def test_monster_actions_execute(monkeypatch):
    monkeypatch.setattr('random.randint', lambda a, b: 15 if (a, b) == (1, 20) else 6)
    char = Character(
        name="Hero",
        level=3,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 16, 'dex': 14, 'con': 12, 'int': 10, 'wis': 10, 'cha': 10},
        hp=20,
        ac=16,
        proficiency_bonus=2
    )
    monster = Monster(
        name="Wolf",
        challenge_rating="1/2",
        hp=11,
        ac=13,
        ability_scores={'str': 12, 'dex': 15, 'con': 12, 'int': 3, 'wis': 12, 'cha': 6}
    )
    claw_action = monster.actions[0]
    result = claw_action.execute(monster, char)
    assert result['hit'] is True
    assert result['damage'] == 6 + 1  # 6 (fixed roll) + 1 (str mod)
    # Miss case
    char.ac = 25
    result2 = claw_action.execute(monster, char)
    assert result2['hit'] is False
    assert result2['damage'] == 0


def test_parse_dice_basic():
    assert AttackAction.parse_dice('1d6') == (1, 6, 0)
    assert AttackAction.parse_dice('2d8+3') == (2, 8, 3)
    assert AttackAction.parse_dice('2d8-1') == (2, 8, -1)
    assert AttackAction.parse_dice('10d20+0') == (10, 20, 0)
    assert AttackAction.parse_dice('1d4-2') == (1, 4, -2)
    with pytest.raises(ValueError):
        AttackAction.parse_dice('bad')
    with pytest.raises(ValueError):
        AttackAction.parse_dice('2d')

def test_damage_roll_with_modifiers(monkeypatch):
    # Always roll 3 for d6
    monkeypatch.setattr('random.randint', lambda a, b: 3)
    attacker = DummyAttacker(str_mod=0)
    # Positive modifier
    action = AttackAction(
        name="Test",
        description="desc",
        weapon_name="Test",
        damage_dice="2d6+2",
        damage_type="bludgeoning"
    )
    dmg = action.damage_roll(attacker)
    assert dmg == 3 + 3 + 2  # 2d6 (3,3) + 2
    # Negative modifier, but not below zero
    action2 = AttackAction(
        name="Test",
        description="desc",
        weapon_name="Test",
        damage_dice="2d6-8",
        damage_type="bludgeoning"
    )
    dmg2 = action2.damage_roll(attacker)
    assert dmg2 == max(0, 3 + 3 - 8)  # Should be 0, not negative
    # Zero modifier
    action3 = AttackAction(
        name="Test",
        description="desc",
        weapon_name="Test",
        damage_dice="2d6+0",
        damage_type="bludgeoning"
    )
    dmg3 = action3.damage_roll(attacker)
    assert dmg3 == 3 + 3 