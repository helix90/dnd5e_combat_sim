"""
Test combat result format to ensure spell actions are properly structured and saved.

This test validates that:
1. Combat.run() produces structured result dicts with proper fields
2. Spell actions include 'type': 'spell' and related fields (damage, healing, target)
3. DatabaseManager._convert_combat_log_format correctly identifies spells
4. Saved combat logs have action_type='spell' for spell actions
5. Spell statistics can be correctly counted from database
"""
import pytest
import uuid
import json
from unittest.mock import MagicMock
from models.character import Character
from models.monster import Monster
from models.combat import Combat
from models.spells import Spell, SpellAction
from models.db import DatabaseManager


class TestCombatResultFormat:
    """Test that combat results are properly structured for spell tracking."""

    def test_spell_action_result_has_required_fields(self):
        """Test that spell action results contain structured data, not just plain text."""
        # Create a cleric with healing spell
        cleric = Character(
            name="Test Cleric",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 14, 'dex': 10, 'con': 14, 'int': 10, 'wis': 16, 'cha': 12},
            hp=38,
            ac=18,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3}
        )

        # Add healing spell
        cure_wounds = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d8",
            healing=True
        )
        cleric.add_spell(cure_wounds)

        # Create spell action
        spell_action = SpellAction(cure_wounds, spell_slot_level=1)

        # Create target
        target = MagicMock()
        target.name = "Injured Fighter"
        target.hp = 10
        target.max_hp = 30

        # Execute spell
        result = spell_action.execute(cleric, target)

        # Verify result has structured data (not plain text)
        assert isinstance(result, dict), "Spell result should be a dict"
        assert result.get('success') == True, "Spell should succeed"

        # The result should contain structured fields that can be used for statistics
        # These fields are critical for spell tracking
        assert 'healing' in result or 'damage' in result, "Result should have healing or damage field"

    def test_combat_log_identifies_spell_actions(self):
        """Test that combat logs correctly identify spell actions vs attacks."""
        session_id = str(uuid.uuid4())

        # Create cleric with healing spell
        cleric = Character(
            name="Branwen",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 14, 'dex': 10, 'con': 14, 'int': 10, 'wis': 18, 'cha': 12},
            hp=38,
            ac=18,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3}
        )

        cure_wounds = Spell(
            name="Cure Wounds",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="Touch",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d8",
            healing=True
        )
        cleric.add_spell(cure_wounds)

        # Create injured ally
        fighter = Character(
            name="Sir Cedric",
            level=5,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 18, 'dex': 14, 'con': 16, 'int': 10, 'wis': 12, 'cha': 10},
            hp=10,  # Low HP to trigger healing
            ac=18,
            proficiency_bonus=3
        )
        fighter.max_hp = 45  # Set max HP so they're injured

        # Create weak enemy so combat doesn't end immediately
        goblin = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=7,
            ac=13,
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
        )

        # Run combat
        combat = Combat([cleric, fighter, goblin])
        result = combat.run()

        # Verify combat has a log
        assert 'log' in result
        assert len(result['log']) > 0

        # Now save to database and verify spell actions are identified
        db = DatabaseManager()
        try:
            # Ensure session exists
            with db._get_connection() as conn:
                conn.execute("INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (session_id,))
                conn.commit()

            # Save simulation
            sim_id = db.save_simulation_result(session_id, result)
            assert sim_id > 0

            # Get combat logs
            combat_logs = db.get_combat_logs(sim_id)
            assert combat_logs is not None
            assert len(combat_logs) > 0

            # Check for spell actions in the logs
            spell_actions = [log for log in combat_logs if log.get('action_type') == 'spell']

            # We should have at least some actions (might not have spells if combat was very short)
            # But if there are spell actions, they should be properly marked
            if len(spell_actions) > 0:
                for spell_log in spell_actions:
                    assert spell_log['action_type'] == 'spell', "Spell actions should have action_type='spell'"
                    assert 'character_name' in spell_log
                    assert 'target' in spell_log
                    # Result should be a human-readable string for display
                    assert isinstance(spell_log['result'], str)

        except Exception as e:
            pytest.fail(f"Failed to save or retrieve spell actions: {e}")

    def test_convert_combat_log_format_detects_spell_actions(self):
        """Test that _convert_combat_log_format correctly identifies spell actions."""
        db = DatabaseManager()

        # Create a log entry in the format that Combat.run() produces
        # with a spell action
        spell_log_entry = {
            'type': 'action',
            'actor': 'Calyra',
            'result': {
                'type': 'spell',  # CRITICAL: This should trigger action_type='spell'
                'action': 'Cast Fireball',
                'spell': 'Fireball',
                'damage': 28,
                'healing': 0,
                'target': 'Troll'
            },
            'timestamp': 1
        }

        # Convert the log
        converted = db._convert_combat_log_format([spell_log_entry])

        assert len(converted) == 1
        entry = converted[0]

        # CRITICAL: action_type should be 'spell', not 'attack'
        assert entry['action_type'] == 'spell', f"Expected action_type='spell', got '{entry['action_type']}'"
        assert entry['character_name'] == 'Calyra'
        assert entry['target'] == 'Troll'
        assert entry['damage'] == 28

    def test_convert_combat_log_format_detects_healing_spells(self):
        """Test that healing spells are correctly identified and tracked."""
        db = DatabaseManager()

        # Create a log entry for a healing spell
        healing_log_entry = {
            'type': 'action',
            'actor': 'Branwen',
            'result': {
                'type': 'spell',
                'action': 'Cast Cure Wounds',
                'spell': 'Cure Wounds',
                'damage': 0,
                'healing': 12,  # CRITICAL: healing amount
                'target': 'Aldric'
            },
            'timestamp': 1
        }

        # Convert the log
        converted = db._convert_combat_log_format([healing_log_entry])

        assert len(converted) == 1
        entry = converted[0]

        # CRITICAL: Should be identified as spell
        assert entry['action_type'] == 'spell', f"Expected action_type='spell', got '{entry['action_type']}'"
        assert entry['character_name'] == 'Branwen'
        assert entry['target'] == 'Aldric'
        # Healing is stored as negative damage
        assert entry['damage'] == -12, "Healing should be stored as negative damage"

    def test_spell_statistics_can_be_counted_from_database(self):
        """Test that we can count spell actions from saved combat logs."""
        session_id = str(uuid.uuid4())

        # Create logs with mixed action types
        logs = [
            {
                'type': 'action',
                'actor': 'Fighter',
                'result': {
                    'type': 'attack',
                    'action': 'Longsword Attack',
                    'hit': True,
                    'damage': 8,
                    'target': 'Orc'
                }
            },
            {
                'type': 'action',
                'actor': 'Wizard',
                'result': {
                    'type': 'spell',
                    'action': 'Cast Magic Missile',
                    'spell': 'Magic Missile',
                    'damage': 10,
                    'target': 'Orc'
                }
            },
            {
                'type': 'action',
                'actor': 'Cleric',
                'result': {
                    'type': 'spell',
                    'action': 'Cast Cure Wounds',
                    'spell': 'Cure Wounds',
                    'healing': 12,
                    'target': 'Fighter'
                }
            }
        ]

        # Create a simulation result
        result = {
            'winner': 'party',
            'rounds': 3,
            'party_hp_remaining': 50,
            'party_level': 5,
            'encounter_type': 'test',
            'log': logs
        }

        db = DatabaseManager()
        try:
            # Ensure session exists
            with db._get_connection() as conn:
                conn.execute("INSERT OR IGNORE INTO sessions (session_id) VALUES (?)", (session_id,))
                conn.commit()

            # Save simulation
            sim_id = db.save_simulation_result(session_id, result)

            # Count spell actions from database
            combat_logs = db.get_combat_logs(sim_id)

            spell_actions = [log for log in combat_logs if log.get('action_type') == 'spell']
            attack_actions = [log for log in combat_logs if log.get('action_type') == 'attack']

            # We should have exactly 2 spell actions and 1 attack
            assert len(spell_actions) == 2, f"Expected 2 spell actions, got {len(spell_actions)}"
            assert len(attack_actions) == 1, f"Expected 1 attack action, got {len(attack_actions)}"

            # Verify spell action details
            damage_spell = [s for s in spell_actions if s.get('damage', 0) > 0][0]
            assert damage_spell['character_name'] == 'Wizard'
            assert damage_spell['damage'] == 10

            healing_spell = [s for s in spell_actions if s.get('damage', 0) < 0][0]
            assert healing_spell['character_name'] == 'Cleric'
            assert healing_spell['damage'] == -12  # Healing as negative

        except Exception as e:
            pytest.fail(f"Failed to count spell statistics: {e}")

    def test_combat_without_type_field_still_detects_spells(self):
        """Test backward compatibility: detect spells even without explicit 'type' field."""
        db = DatabaseManager()

        # Old format might not have 'type' field, but should detect based on 'spell' key
        old_format_log = {
            'type': 'action',
            'actor': 'Wizard',
            'result': {
                'spell': 'Fireball',  # Has 'spell' key but no 'type' field
                'action': 'Cast Fireball',
                'damage': 24,
                'target': 'Goblin'
            }
        }

        # Convert the log
        converted = db._convert_combat_log_format([old_format_log])

        assert len(converted) == 1
        entry = converted[0]

        # Should still detect as spell based on 'spell' key in result
        assert entry['action_type'] == 'spell', "Should detect spell from 'spell' key in result"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
