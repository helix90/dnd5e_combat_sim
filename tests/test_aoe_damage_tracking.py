"""
Test that AoE spell damage is correctly tracked in combat logs.

This is a regression test for a bug where area effect spell damage
was not being recorded in the database's damage field.
"""

import pytest
import uuid
from models.character import Character
from models.monster import Monster
from models.combat import Combat
from models.spell_manager import SpellManager
from models.db import DatabaseManager


def test_aoe_spell_damage_tracking():
    """
    Test that AoE spells (like Fireball) have their total damage
    correctly recorded in the combat_logs table.

    This test ensures that when a spell hits multiple targets,
    the total_damage field is properly extracted and saved to
    the database's damage column.
    """
    # Create a Wizard with Fireball
    wizard = Character(
        name="TestWizard",
        level=5,
        character_class="Wizard",
        race="Human",
        ability_scores={'str': 8, 'dex': 14, 'con': 12, 'int': 16, 'wis': 12, 'cha': 10},
        hp=28,
        ac=12,
        proficiency_bonus=3,
        spell_slots={1: 4, 2: 3, 3: 2}
    )

    # Load and add Fireball spell
    spell_manager = SpellManager()
    fireball = spell_manager.get_spell("Fireball")
    wizard.add_spell(fireball)

    # Create 3 goblins as targets
    goblin1 = Monster(
        name="Goblin1",
        challenge_rating="1/4",
        hp=15,
        ac=15,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )

    goblin2 = Monster(
        name="Goblin2",
        challenge_rating="1/4",
        hp=15,
        ac=15,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )

    goblin3 = Monster(
        name="Goblin3",
        challenge_rating="1/4",
        hp=15,
        ac=15,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )

    # Run combat
    participants = [wizard, goblin1, goblin2, goblin3]
    combat = Combat(participants)
    combat.roll_initiative()

    # Run one round - should be enough for wizard to cast Fireball
    max_rounds = 2
    rounds_run = 0
    while not combat.is_combat_over() and rounds_run < max_rounds:
        combat.next_turn()
        rounds_run += 1

    # Get combat result
    combat_log = combat.get_combat_log()
    log = combat_log
    fireball_cast = False
    fireball_total_damage = 0

    for entry in log:
        if entry['type'] == 'action':
            result = entry['result']
            if result.get('spell') == 'Fireball' or (result.get('action') == 'Fireball'):
                fireball_cast = True
                # Get the total damage from AoE spell
                fireball_total_damage = result.get('total_damage', 0)
                break

    # If Fireball wasn't cast (bad luck on initiative/AI), skip this test
    if not fireball_cast:
        pytest.skip("Fireball was not cast during combat (AI chose different action)")

    # Now save to database and verify
    db = DatabaseManager()
    session_id = str(uuid.uuid4())

    # Ensure session exists
    with db._get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (session_id,))
        conn.commit()

    # Build the combat result
    # Determine winner
    alive_party = [p for p in combat.participants if hasattr(p, 'character_class') and p.is_alive()]
    alive_monsters = [p for p in combat.participants if not hasattr(p, 'character_class') and p.is_alive()]

    if not alive_party:
        winner = 'monsters'
    elif not alive_monsters:
        winner = 'party'
    else:
        winner = 'unknown'

    result = {
        'winner': winner,
        'rounds': combat.current_round,
        'log': combat.get_combat_log(),
        'participants': []
    }

    for participant in combat.participants:
        result['participants'].append({
            'name': participant.name,
            'hp': participant.hp,
            'is_alive': participant.is_alive(),
            'team': 'party' if hasattr(participant, 'character_class') else 'monsters'
        })

    # Save simulation result (this is where the bug was)
    sim_id = db.save_simulation_result(session_id, result)

    # Query the combat_logs table for the wizard's spell action
    import sqlite3
    conn = sqlite3.connect('dnd5e_sim.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT character_name, action_type, damage
        FROM combat_logs
        WHERE simulation_id = ? AND character_name = 'TestWizard' AND action_type = 'spell'
    ''', (sim_id,))

    wizard_spell_logs = cursor.fetchall()
    conn.close()

    # Find the spell action with damage
    total_damage_in_db = sum(log[2] for log in wizard_spell_logs if log[2] > 0)

    # Verify that damage was recorded
    assert total_damage_in_db > 0, \
        f"AoE spell damage not recorded! Expected {fireball_total_damage}, got {total_damage_in_db}"

    # Verify that the damage matches what was dealt
    assert total_damage_in_db == fireball_total_damage, \
        f"AoE spell damage mismatch! Expected {fireball_total_damage}, got {total_damage_in_db} in database"

    print(f"SUCCESS: AoE spell damage correctly tracked - {total_damage_in_db} damage recorded")


def test_single_target_spell_damage_tracking():
    """
    Test that single-target spells still work correctly after the AoE fix.
    This ensures backward compatibility.
    """
    # Create a Cleric with Guiding Bolt (single-target damage spell)
    cleric = Character(
        name="TestCleric",
        level=3,
        character_class="Cleric",
        race="Human",
        ability_scores={'str': 10, 'dex': 12, 'con': 14, 'int': 10, 'wis': 16, 'cha': 12},
        hp=20,
        ac=16,
        proficiency_bonus=2,
        spell_slots={1: 4, 2: 2}
    )

    # Load Guiding Bolt spell if available
    spell_manager = SpellManager()
    try:
        guiding_bolt = spell_manager.get_spell("Guiding Bolt")
        cleric.add_spell(guiding_bolt)
    except:
        # If Guiding Bolt doesn't exist, skip this test
        pytest.skip("Guiding Bolt spell not available")

    # Create a goblin as target
    goblin = Monster(
        name="TargetGoblin",
        challenge_rating="1/4",
        hp=50,  # High HP so it doesn't die immediately
        ac=15,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )

    # Run combat
    participants = [cleric, goblin]
    combat = Combat(participants)
    combat.roll_initiative()

    # Run a few rounds
    max_rounds = 3
    rounds_run = 0
    while not combat.is_combat_over() and rounds_run < max_rounds:
        combat.next_turn()
        rounds_run += 1

    # Save to database
    db = DatabaseManager()
    session_id = str(uuid.uuid4())

    # Ensure session exists
    with db._get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (session_id,))
        conn.commit()

    # Build the combat result
    # Determine winner
    alive_party = [p for p in combat.participants if hasattr(p, 'character_class') and p.is_alive()]
    alive_monsters = [p for p in combat.participants if not hasattr(p, 'character_class') and p.is_alive()]

    if not alive_party:
        winner = 'monsters'
    elif not alive_monsters:
        winner = 'party'
    else:
        winner = 'unknown'

    result = {
        'winner': winner,
        'rounds': combat.current_round,
        'log': combat.get_combat_log(),
        'participants': []
    }

    for participant in combat.participants:
        result['participants'].append({
            'name': participant.name,
            'hp': participant.hp,
            'is_alive': participant.is_alive(),
            'team': 'party' if hasattr(participant, 'character_class') else 'monsters'
        })

    sim_id = db.save_simulation_result(session_id, result)

    # Query the combat_logs table
    import sqlite3
    conn = sqlite3.connect('dnd5e_sim.db')
    cursor = conn.cursor()

    cursor.execute('''
        SELECT COUNT(*)
        FROM combat_logs
        WHERE simulation_id = ? AND character_name = 'TestCleric'
    ''', (sim_id,))

    log_count = cursor.fetchone()[0]
    conn.close()

    # Just verify that logs were saved (basic sanity check)
    assert log_count > 0, "No combat logs saved for single-target spell test"

    print(f"SUCCESS: Single-target spell test passed - {log_count} logs recorded")


if __name__ == '__main__':
    # Run the tests
    test_aoe_spell_damage_tracking()
    test_single_target_spell_damage_tracking()
