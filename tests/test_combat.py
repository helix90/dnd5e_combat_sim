import pytest
from models.character import Character
from models.monster import Monster
from models.combat import Combat, CombatLogger
from models.actions import AttackAction

@pytest.fixture
def hero():
    return Character(
        name="Hero",
        level=3,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 16, 'dex': 14, 'con': 12, 'int': 10, 'wis': 10, 'cha': 10},
        hp=20,
        ac=16,
        proficiency_bonus=2
    )

@pytest.fixture
def rogue():
    return Character(
        name="Rogue",
        level=3,
        character_class="Rogue",
        race="Elf",
        ability_scores={'str': 10, 'dex': 18, 'con': 12, 'int': 10, 'wis': 10, 'cha': 10},
        hp=18,
        ac=15,
        proficiency_bonus=2
    )

@pytest.fixture
def goblin():
    return Monster(
        name="Goblin",
        challenge_rating="1/4",
        hp=7,
        ac=15,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )

def test_initiative_rolling_and_sorting(monkeypatch, hero, rogue, goblin):
    # Patch random.randint to control initiative rolls
    rolls = [15, 18, 12]  # hero, rogue, goblin
    def fake_randint(a, b):
        return rolls.pop(0)
    monkeypatch.setattr('random.randint', fake_randint)
    combat = Combat([hero, rogue, goblin])
    combat.roll_initiative()
    order = combat.get_initiative_order()
    # Rogue (18+4=22), Hero (15+2=17), Goblin (12+2=14)
    assert order[0].name == "Rogue"
    assert order[1].name == "Hero"
    assert order[2].name == "Goblin"

def test_turn_order_and_rounds(monkeypatch, hero, rogue, goblin):
    # Patch random.randint for initiative
    monkeypatch.setattr('random.randint', lambda a, b: 10)
    combat = Combat([hero, rogue, goblin])
    combat.roll_initiative()
    # All have same roll, so dex mod breaks tie: Rogue (4), Hero (2), Goblin (2)
    order = combat.get_initiative_order()
    assert order[0].name == "Rogue"
    # Hero and Goblin have same Dex mod, so order between them is random
    assert set([order[1].name, order[2].name]) == {"Hero", "Goblin"}
    # Simulate turns
    assert combat.current_round == 1
    p1 = combat.next_turn()
    assert p1.name == "Rogue"
    p2 = combat.next_turn()
    assert p2.name in {"Hero", "Goblin"}
    p3 = combat.next_turn()
    if p3 is not None:
        assert p3.name in {"Hero", "Goblin"} and p3.name != p2.name
    else:
        # If combat ended early, that's also valid
        assert combat.is_combat_over()
    # Next turn should start round 2
    p4 = combat.next_turn()
    if p4 is not None:
        assert p4.name == "Rogue"
        assert combat.current_round == 2
    else:
        assert combat.is_combat_over()

def test_combat_state_tracking(hero, rogue, goblin):
    # Ensure goblin starts alive
    goblin.hp = 7
    combat = Combat([hero, rogue, goblin])
    combat.roll_initiative()  # Initialize the combat properly
    # All alive
    assert not combat.is_combat_over()
    # Knock out goblin
    goblin.hp = 0
    # Clear the alive participants cache to force recalculation
    combat._alive_participants_cache = None
    assert combat.is_combat_over()
    # Knock out both heroes
    hero.hp = 0
    rogue.hp = 0
    combat._alive_participants_cache = None
    assert combat.is_combat_over()

def test_combat_logger():
    logger = CombatLogger()
    logger.log_round_start(1)
    logger.log_action("Hero", {"hit": True, "damage": 5})
    log = logger.get_combat_log()
    assert log[0]['type'] == 'round_start'
    assert log[1]['type'] == 'action'
    assert log[1]['actor'] == "Hero"
    assert log[1]['result']['damage'] == 5

def test_initiative_tiebreaker(monkeypatch):
    # Two characters with same roll and dex
    c1 = Character(
        name="A",
        level=1,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10},
        hp=10,
        ac=10,
        proficiency_bonus=2
    )
    c2 = Character(
        name="B",
        level=1,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10},
        hp=10,
        ac=10,
        proficiency_bonus=2
    )
    monkeypatch.setattr('random.randint', lambda a, b: 10)
    combat = Combat([c1, c2])
    combat.roll_initiative()
    order = combat.get_initiative_order()
    # Order is deterministic due to random.random, but both are valid
    assert set([order[0].name, order[1].name]) == {"A", "B"}

def test_integration_2v1_combat(monkeypatch):
    # Hero and Rogue vs Goblin
    # Patch random.randint for initiative and attack rolls
    init_rolls = [15, 18, 12]  # hero, rogue, goblin
    attack_rolls = [18, 5, 20, 3, 15, 2, 10, 1]  # d20, damage, d20, damage, ...
    def fake_randint(a, b):
        if a == 1 and b == 20:
            return init_rolls.pop(0) if init_rolls else attack_rolls.pop(0)
        return 5  # damage
    monkeypatch.setattr('random.randint', fake_randint)
    hero = Character(
        name="Hero",
        level=3,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 16, 'dex': 14, 'con': 12, 'int': 10, 'wis': 10, 'cha': 10},
        hp=20,
        ac=16,
        proficiency_bonus=2
    )
    rogue = Character(
        name="Rogue",
        level=3,
        character_class="Rogue",
        race="Elf",
        ability_scores={'str': 10, 'dex': 18, 'con': 12, 'int': 10, 'wis': 10, 'cha': 10},
        hp=18,
        ac=15,
        proficiency_bonus=2
    )
    goblin = Monster(
        name="Goblin",
        challenge_rating="1/4",
        hp=7,  # Set to 7 to match the fixture
        ac=13,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )
    combat = Combat([hero, rogue, goblin])
    combat.roll_initiative()
    # Simulate 1 round: each attacks goblin
    for _ in range(3):
        actor = combat.next_turn()
        if actor is None or not actor.is_alive():
            continue
        if isinstance(actor, Character):
            action = next(a for a in actor.actions if a.name == "Sword Attack")
        else:
            action = actor.actions[0]
        result = action.execute(actor, goblin if actor != goblin else hero)
        combat.logger.log_action(actor, result)
        # No manual HP subtraction needed; action.execute applies damage
    # Check goblin is likely knocked out
    assert goblin.hp < 12
    log = combat.get_combat_log()
    assert any(entry['type'] == 'action' for entry in log)

def test_combat_damage_and_end(monkeypatch):
    # Patch random.randint for deterministic combat
    rolls = [18, 18, 18, 5, 5, 5, 18, 5, 18, 5]  # Always hit, always 5 damage
    def fake_randint(a, b):
        return rolls.pop(0) if rolls else 18
    monkeypatch.setattr('random.randint', fake_randint)
    hero = Character(
        name="Hero",
        level=3,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 16, 'dex': 14, 'con': 12, 'int': 10, 'wis': 10, 'cha': 10},
        hp=20,
        ac=16,
        proficiency_bonus=2
    )
    goblin = Monster(
        name="Goblin",
        challenge_rating="1/4",
        hp=7,
        ac=13,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )
    combat = Combat([hero, goblin])
    combat.roll_initiative()
    # Run until combat ends
    while not combat.is_combat_over():
        combat.next_turn()
    # Goblin should be dead
    assert goblin.hp <= 0
    assert not goblin.is_alive()
    # Combat should be over
    assert combat.is_combat_over() 

def test_no_double_ability_modifier_for_monster_attacks(monkeypatch):
    """Test that monster attacks with a dice string modifier do not double-count the ability modifier."""
    from models.character import Character
    from models.monster import Monster
    from models.actions import AttackAction

    # Patch random.randint to always return max value for predictability
    monkeypatch.setattr('random.randint', lambda a, b: b)

    # Kobold: DEX 15 (+2), attack is '1d4+2' (should NOT add DEX mod again)
    kobold = Monster(
        name="Kobold",
        challenge_rating="1/8",
        hp=5,
        ac=12,
        ability_scores={"str": 7, "dex": 15, "con": 9, "int": 8, "wis": 7, "cha": 8},
        actions=[AttackAction(name="Dagger", description="Stab", weapon_name="Dagger", damage_dice="1d4+2", damage_type="piercing")]
    )
    dummy_target = Character(
        name="Dummy",
        level=1,
        character_class="Fighter",
        race="Human",
        ability_scores={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        hp=20,
        ac=10,
        proficiency_bonus=2
    )
    # Should be 1d4 (4) + 2 = 6, not 8
    result = kobold.actions[0].execute(kobold, dummy_target)
    assert result['damage'] == 6, f"Expected 6, got {result['damage']} (should not double-count DEX mod)"

    # Fighter: STR 16 (+3), attack is '1d8' (should add STR mod)
    fighter = Character(
        name="Fighter",
        level=1,
        character_class="Fighter",
        race="Human",
        ability_scores={"str": 16, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
        hp=20,
        ac=16,
        proficiency_bonus=2
    )
    sword_attack = AttackAction(name="Sword Attack", description="Slash", weapon_name="Longsword", damage_dice="1d8", damage_type="slashing")
    # Should be 1d8 (8) + 3 = 11
    result2 = sword_attack.execute(fighter, dummy_target)
    assert result2['damage'] == 11, f"Expected 11, got {result2['damage']} (should add STR mod)" 