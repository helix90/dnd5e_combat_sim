"""
Integration tests for D&D 5e Combat Simulator.

These tests verify full workflows including background thread completion,
database saves with real objects, and combat log conversion.
They are designed to catch object serialization bugs that unit tests might miss.
"""

import uuid
from app import db
from tests.helpers import results_page, run_simulation, session_id, shows_simulation
from models.combat import Combat
from models.character import Character
from models.monster import Monster
from models.spell_manager import SpellManager
from utils.party_loader import PartyLoader


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
    party_size = len(party["characters"])

    # Select party
    rv = client.post(
        "/party",
        data={"party_id": party["id"], "party_level": party_level},
        follow_redirects=True,
    )
    assert rv.status_code == 200
    assert b"Select Encounter" in rv.data

    # Select prebuilt encounter
    enc_name = "Kobold Mob"
    rv2 = client.post(
        "/encounter/prebuilt",
        json={
            "template_name": enc_name,
            "party_level": party_level,
            "party_size": party_size,
        },
    )
    assert rv2.status_code == 200

    status = run_simulation(client)
    page = results_page(client)
    assert shows_simulation(page, status["simulation_id"])

    simulation = db.get_simulation(status["simulation_id"])
    assert simulation["session_id"] == session_id(client)
    assert simulation["result"] in ("party", "monsters")
    assert db.get_combat_logs(status["simulation_id"])


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
        ability_scores={
            "str": 16,
            "dex": 14,
            "con": 14,
            "int": 10,
            "wis": 12,
            "cha": 10,
        },
        hp=25,
        ac=16,
        proficiency_bonus=2,
    )

    monster = Monster(
        name="Test Goblin",
        challenge_rating="1/4",
        hp=7,
        ac=13,
        ability_scores={"str": 8, "dex": 14, "con": 10, "int": 10, "wis": 8, "cha": 8},
    )

    # Run combat - this generates real Action objects in the log
    combat = Combat([character, monster])
    result = combat.run()

    # Verify result has a log
    assert "log" in result
    assert len(result["log"]) > 0

    # Verify log contains action entries
    has_actions = False
    for entry in result["log"]:
        if isinstance(entry, dict) and entry.get("type") == "action":
            has_actions = True
            break

    assert has_actions, "Combat log does not contain action entries"

    # Now try to save this to the database - this is where the bug would occur
    db.create_session(session_id)

    sim_id = db.save_simulation_result(session_id, result)
    assert sim_id > 0, "Failed to save simulation"

    # Verify we can load it back
    simulation = db.get_simulation(sim_id)
    assert simulation is not None
    assert simulation["id"] == sim_id

    # Verify combat log was saved
    combat_logs = db.get_combat_logs(sim_id)
    assert combat_logs is not None
    assert len(combat_logs) > 0


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
        ability_scores={
            "str": 10,
            "dex": 14,
            "con": 12,
            "int": 16,
            "wis": 13,
            "cha": 10,
        },
        hp=28,
        ac=12,
        proficiency_bonus=3,
        spell_slots={"1": 4, "2": 3, "3": 2},
    )

    # Add a spell to the wizard
    spell_manager = SpellManager()
    character.add_spell(spell_manager.get_spell("Fireball"))

    monster = Monster(
        name="Test Orc",
        challenge_rating="1",
        hp=15,
        ac=13,
        ability_scores={
            "str": 16,
            "dex": 12,
            "con": 16,
            "int": 7,
            "wis": 11,
            "cha": 10,
        },
    )

    # Run combat
    combat = Combat([character, monster])
    result = combat.run()

    # Verify combat ran
    assert "winner" in result
    assert "log" in result

    # Save to database - this is where Character/Monster object errors would occur
    db.create_session(session_id)

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
        if "character_name" in entry:
            assert isinstance(
                entry["character_name"], str
            ), f"Character name should be string, got {type(entry['character_name'])}"
        if "target" in entry:
            assert isinstance(
                entry["target"], str
            ), f"Target should be string, got {type(entry['target'])}"


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
        ability_scores={
            "str": 14,
            "dex": 10,
            "con": 14,
            "int": 10,
            "wis": 16,
            "cha": 12,
        },
        hp=32,
        ac=18,
        proficiency_bonus=2,
    )

    monster = Monster(
        name="Test Zombie",
        challenge_rating="1/4",
        hp=22,
        ac=8,
        ability_scores={"str": 13, "dex": 6, "con": 16, "int": 3, "wis": 6, "cha": 5},
    )

    # Create a log entry in the format that Combat.run() actually produces
    # Looking at CombatLogger.log_action(), the format is:
    # {'type': 'action', 'actor': actor.name, 'result': {...}, 'timestamp': ...}
    action = Action(
        action_type="attack", name="Mace Attack", description="Melee weapon attack"
    )

    log_entry = {
        "type": "action",
        "actor": character.name,  # Already converted to string by CombatLogger
        "result": {
            "hit": True,
            "target": monster.name,  # Already converted to string
            "action": action,  # Action object in result dict
            "damage": 8,
            "message": f"{character.name} hits {monster.name} for 8 damage",
        },
        "timestamp": 1,
    }

    # Test the conversion
    converted = db._convert_combat_log_format([log_entry])

    assert len(converted) > 0, "Conversion should produce at least one entry"
    entry = converted[0]

    # Verify the conversion worked correctly
    assert (
        entry["character_name"] == "Test Cleric"
    ), "Actor name should be extracted correctly"
    assert entry["action_type"] in [
        "attack",
        "special",
    ], "Action type should be determined"
    assert entry["target"] == "Test Zombie", "Target name should be extracted correctly"
    assert entry["damage"] == 8, "Damage should be extracted"


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
    party_size = len(party["characters"])

    def fight(template_name):
        client.post(
            "/party",
            data={"party_id": party["id"], "party_level": party_level},
            follow_redirects=True,
        )
        client.post(
            "/encounter/prebuilt",
            json={
                "template_name": template_name,
                "party_level": party_level,
                "party_size": party_size,
            },
        )
        return run_simulation(client)["simulation_id"]

    first = fight("Goblin Ambush")
    second = fight("Kobold Mob")
    assert first != second
    # The results page goes to the second fight, not the first
    page = results_page(client)
    assert shows_simulation(page, second) and not shows_simulation(page, first)
    assert "Kobold" in page and "Goblin" not in page
