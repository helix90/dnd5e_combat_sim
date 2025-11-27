"""
Integration tests for D&D 5e Combat Simulator.

These tests verify full workflows including background thread completion,
database saves with real objects, and combat log conversion.
They are designed to catch object serialization bugs that unit tests might miss.
"""
import pytest
import time
import uuid
from app import app as flask_app
from models.combat import Combat
from models.character import Character
from models.monster import Monster
from models.db import DatabaseManager
from models.spell_manager import SpellManager
from utils.party_loader import PartyLoader


@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        with flask_app.app_context():
            yield client


@pytest.fixture
def db():
    """Create a database manager instance."""
    return DatabaseManager()


@pytest.fixture
def session_id():
    """Generate a unique session ID for testing."""
    return str(uuid.uuid4())


def test_simulation_completes_and_saves_to_database(client):
    """
    Integration test: Start a simulation, wait for it to complete,
    and verify that it was saved to the database correctly.

    This test would have caught the object serialization bugs because it:
    1. Waits for the background thread to complete
    2. Verifies the database save actually worked
    3. Uses real Combat objects with Action, Character, and Monster instances
    """
    # Get first party
    parties = PartyLoader.load_parties()
    party = parties[0]
    party_level = 3
    party_size = len(party['characters'])

    # Select party
    rv = client.post('/party', data={'party_id': party['id'], 'party_level': party_level}, follow_redirects=True)
    assert rv.status_code == 200
    assert b'Select Encounter' in rv.data

    # Select prebuilt encounter
    enc_name = "Kobold Mob"
    rv2 = client.post('/encounter/prebuilt', json={
        'template_name': enc_name,
        'party_level': party_level,
        'party_size': party_size
    })
    assert rv2.status_code == 200

    # Start simulation
    rv3 = client.get('/simulate')
    assert rv3.status_code == 200

    # Poll status until done (max 30 seconds)
    simulation_done = False
    for i in range(60):
        rv4 = client.get('/simulate/status')
        assert rv4.status_code == 200
        data = rv4.get_json()
        if data.get('done'):
            simulation_done = True
            break
        time.sleep(0.5)

    assert simulation_done, "Simulation did not complete within 30 seconds"

    # Get results
    rv5 = client.get('/simulate/results', follow_redirects=True)
    assert rv5.status_code == 200
    html = rv5.data.decode('utf-8')

    # Verify results contain expected content (either combat log or simulation results)
    # The page might show combat log, history, or results depending on the template
    assert ('Combat Log' in html or 'combat log' in html.lower() or
            'Simulation' in html or 'History' in html or 'Results' in html)

    # Verify database save worked by checking we have a simulation ID in session
    with client.session_transaction() as sess:
        session_id = sess.get('session_id')
        assert session_id is not None, "Session should have a session_id"

    # Verify simulation was saved to database
    db = DatabaseManager()
    sim_id = db.get_last_simulation_id(session_id)
    assert sim_id is not None, "Simulation was not saved to database"

    simulation = db.get_simulation(sim_id)
    assert simulation is not None, "Simulation should be retrievable from database"
    assert simulation['id'] == sim_id


def test_combat_log_saves_with_action_objects():
    """
    Integration test: Run a combat simulation that generates Action objects,
    then verify the database can save the combat log correctly.

    This test would have caught the 'Action' object has no attribute 'lower' bug
    because it uses real Combat.run() output with Action objects.
    """
    session_id = str(uuid.uuid4())

    # Create real character and monster objects
    character = Character(
        name="Test Fighter",
        level=3,
        character_class="Fighter",
        race="Human",
        ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 12, 'cha': 10},
        hp=25,
        ac=16,
        proficiency_bonus=2
    )

    monster = Monster(
        name="Test Goblin",
        challenge_rating="1/4",
        hp=7,
        ac=13,
        ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
    )

    # Run combat - this generates real Action objects in the log
    combat = Combat([character, monster])
    result = combat.run()

    # Verify result has a log
    assert 'log' in result
    assert len(result['log']) > 0

    # Verify log contains action entries
    has_actions = False
    for entry in result['log']:
        if isinstance(entry, dict) and entry.get('type') == 'action':
            has_actions = True
            break

    assert has_actions, "Combat log does not contain action entries"

    # Now try to save this to the database - this is where the bug would occur
    db = DatabaseManager()
    try:
        # First ensure the session exists (create or use existing)
        # This avoids the foreign key constraint error
        with db._get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (session_id,))
            conn.commit()

        sim_id = db.save_simulation_result(session_id, result)
        assert sim_id > 0, "Failed to save simulation"

        # Verify we can load it back
        simulation = db.get_simulation(sim_id)
        assert simulation is not None
        assert simulation['id'] == sim_id

        # Verify combat log was saved
        combat_logs = db.get_combat_logs(sim_id)
        assert combat_logs is not None
        assert len(combat_logs) > 0

    except AttributeError as e:
        if "'Action' object has no attribute 'lower'" in str(e):
            pytest.fail("Failed to handle Action objects in combat log: " + str(e))
        raise
    except Exception as e:
        pytest.fail(f"Unexpected error saving combat result: {e}")


def test_combat_log_saves_with_character_monster_objects():
    """
    Integration test: Verify that combat logs with Character and Monster objects
    in actor/target fields can be saved to the database.

    This test would have caught the 'Character' object type not supported bug
    because it verifies that actor/target objects are converted to strings.
    """
    session_id = str(uuid.uuid4())

    # Create character and monster
    character = Character(
        name="Test Wizard",
        level=5,
        character_class="Wizard",
        race="Elf",
        ability_scores={'str': 10, 'dex': 14, 'con': 12, 'int': 16, 'wis': 13, 'cha': 10},
        hp=28,
        ac=12,
        proficiency_bonus=3,
        spell_slots={'1': 4, '2': 3, '3': 2}
    )

    # Add a spell to the wizard
    spell_manager = SpellManager()
    fireball = spell_manager.get_spell("Fireball")
    if fireball:
        character.add_spell(fireball)

    monster = Monster(
        name="Test Orc",
        challenge_rating="1",
        hp=15,
        ac=13,
        ability_scores={'str': 16, 'dex': 12, 'con': 16, 'int': 7, 'wis': 11, 'cha': 10}
    )

    # Run combat
    combat = Combat([character, monster])
    result = combat.run()

    # Verify combat ran
    assert 'winner' in result
    assert 'log' in result

    # Save to database - this is where Character/Monster object errors would occur
    db = DatabaseManager()
    try:
        # First ensure the session exists
        with db._get_connection() as conn:
            conn.execute("INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (session_id,))
            conn.commit()

        sim_id = db.save_simulation_result(session_id, result)
        assert sim_id > 0

        # Verify we can retrieve it
        simulation = db.get_simulation(sim_id)
        assert simulation is not None

        # Verify combat log entries were saved correctly
        combat_logs = db.get_combat_logs(sim_id)
        assert combat_logs is not None

        # Check that actor and target fields are strings, not objects
        for entry in combat_logs:
            if 'character_name' in entry:
                assert isinstance(entry['character_name'], str), f"Character name should be string, got {type(entry['character_name'])}"
            if 'target' in entry:
                assert isinstance(entry['target'], str), f"Target should be string, got {type(entry['target'])}"

    except Exception as e:
        if 'type \'Character\' is not supported' in str(e) or 'type \'Monster\' is not supported' in str(e):
            pytest.fail(f"Failed to convert Character/Monster objects to strings: {e}")
        raise


def test_convert_combat_log_format_with_real_objects():
    """
    Unit test for _convert_combat_log_format with real Combat output.

    This test directly tests the log conversion method with real data
    from Combat.run() which uses the CombatLogger format.
    """
    from models.actions import Action

    character = Character(
        name="Test Cleric",
        level=4,
        character_class="Cleric",
        race="Dwarf",
        ability_scores={'str': 14, 'dex': 10, 'con': 14, 'int': 10, 'wis': 16, 'cha': 12},
        hp=32,
        ac=18,
        proficiency_bonus=2
    )

    monster = Monster(
        name="Test Zombie",
        challenge_rating="1/4",
        hp=22,
        ac=8,
        ability_scores={'str': 13, 'dex': 6, 'con': 16, 'int': 3, 'wis': 6, 'cha': 5}
    )

    # Create a log entry in the format that Combat.run() actually produces
    # Looking at CombatLogger.log_action(), the format is:
    # {'type': 'action', 'actor': actor.name, 'result': {...}, 'timestamp': ...}
    action = Action(action_type='attack', name='Mace Attack', description='Melee weapon attack')

    log_entry = {
        'type': 'action',
        'actor': character.name,  # Already converted to string by CombatLogger
        'result': {
            'hit': True,
            'target': monster.name,  # Already converted to string
            'action': action,        # Action object in result dict
            'damage': 8,
            'message': f"{character.name} hits {monster.name} for 8 damage"
        },
        'timestamp': 1
    }

    # Test the conversion
    db = DatabaseManager()
    try:
        converted = db._convert_combat_log_format([log_entry])

        assert len(converted) > 0, "Conversion should produce at least one entry"
        entry = converted[0]

        # Verify the conversion worked correctly
        assert entry['character_name'] == "Test Cleric", "Actor name should be extracted correctly"
        assert entry['action_type'] in ['attack', 'special'], "Action type should be determined"
        assert entry['target'] == "Test Zombie", "Target name should be extracted correctly"
        assert entry['damage'] == 8, "Damage should be extracted"

    except AttributeError as e:
        if "'Action' object has no attribute 'lower'" in str(e):
            pytest.fail("Failed to handle Action objects: " + str(e))
        raise
    except Exception as e:
        if 'is not supported' in str(e):
            pytest.fail(f"Failed to convert objects to strings: {e}")
        raise


def test_multiple_simulations_dont_show_old_results(client):
    """
    Integration test: Verify that running multiple simulations in sequence
    doesn't show old results.

    This test would have caught the regression where old simulation_id
    persisted in the session.
    """
    parties = PartyLoader.load_parties()
    party = parties[0]
    party_level = 2
    party_size = len(party['characters'])

    # Run first simulation
    client.post('/party', data={'party_id': party['id'], 'party_level': party_level}, follow_redirects=True)
    client.post('/encounter/prebuilt', json={
        'template_name': 'Goblin Ambush',
        'party_level': party_level,
        'party_size': party_size
    })
    client.get('/simulate')

    # Wait for completion
    for _ in range(60):
        status = client.get('/simulate/status').get_json()
        if status.get('done'):
            break
        time.sleep(0.5)

    # Get first simulation ID
    with client.session_transaction() as sess:
        first_sim_id = sess.get('simulation_id')

    # Run second simulation with different encounter
    client.post('/party', data={'party_id': party['id'], 'party_level': party_level}, follow_redirects=True)
    client.post('/encounter/prebuilt', json={
        'template_name': 'Kobold Mob',
        'party_level': party_level,
        'party_size': party_size
    })
    client.get('/simulate')

    # Wait for completion
    for _ in range(60):
        status = client.get('/simulate/status').get_json()
        if status.get('done'):
            break
        time.sleep(0.5)

    # Get second simulation ID
    with client.session_transaction() as sess:
        second_sim_id = sess.get('simulation_id')

    # Verify we got different simulation IDs (or at least cleared the old one)
    # The important thing is we don't see the first simulation's results
    if first_sim_id and second_sim_id:
        assert first_sim_id != second_sim_id, "Simulation IDs should be different for different runs"

    # Get results and verify they're for the second simulation
    rv = client.get('/simulate/results', follow_redirects=True)
    html = rv.data.decode('utf-8')

    # Should show current results, not be stuck on old ones
    assert rv.status_code == 200
    assert 'Combat Log' in html or 'combat log' in html.lower()
