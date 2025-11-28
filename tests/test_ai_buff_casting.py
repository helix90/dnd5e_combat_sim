"""Test that AI casts buff spells in combat."""
import pytest
from models.character import Character
from models.monster import Monster
from models.combat import Combat
from models.spell_manager import SpellManager


class TestAIBuffCasting:
    """Test that AI properly casts buff spells during combat."""

    def test_cleric_casts_bless_early_in_combat(self):
        """Test that a Cleric casts Bless in the first two rounds of combat."""
        # Create a Cleric with Bless
        cleric = Character(
            name="Cleric",
            level=3,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 12, 'con': 14, 'int': 10, 'wis': 16, 'cha': 12},
            hp=20,
            ac=16,
            proficiency_bonus=2,
            spell_slots={1: 4, 2: 2}
        )

        # Load and add Bless spell
        spell_manager = SpellManager()
        bless = spell_manager.get_spell("Bless")
        cleric.add_spell(bless)

        # Create some allies
        fighter = Character(
            name="Fighter",
            level=3,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
            hp=26,
            ac=18,
            proficiency_bonus=2
        )

        # Create enemies (higher HP so combat lasts long enough for Cleric to get a turn)
        goblin = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=30,
            ac=15,
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
        )

        # Run combat
        participants = [cleric, fighter, goblin]
        combat = Combat(participants)
        combat.roll_initiative()

        # Simulate a few rounds
        max_rounds = 5
        round_count = 0
        while not combat.is_combat_over() and round_count < max_rounds:
            combat.next_turn()
            round_count = combat.current_round

        # Check combat log for Bless casting
        log = combat.get_combat_log()
        bless_cast = False
        bless_round = None

        for entry in log:
            if entry['type'] == 'action':
                result = entry['result']
                if 'spell' in result and result.get('spell') == 'Bless':
                    bless_cast = True
                    bless_round = entry['round']
                    break
                # Also check if buff_applied with buff_name = Bless
                if result.get('buff_applied') and result.get('buff_name') == 'Bless':
                    bless_cast = True
                    bless_round = entry['round']
                    break

        # Verify Bless was cast
        assert bless_cast, "Cleric should cast Bless during combat"

        # Verify it was cast early (in first 2 rounds)
        if bless_round is not None:
            assert bless_round <= 2, f"Bless should be cast in first 2 rounds, but was cast in round {bless_round}"

    def test_buff_persists_across_rounds(self):
        """Test that buffs persist and affect actions in subsequent rounds."""
        # Create a Cleric with Bless
        cleric = Character(
            name="Cleric",
            level=3,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 12, 'con': 14, 'int': 10, 'wis': 16, 'cha': 12},
            hp=20,
            ac=16,
            proficiency_bonus=2,
            spell_slots={1: 4, 2: 2}
        )

        # Load and add Bless spell
        spell_manager = SpellManager()
        bless = spell_manager.get_spell("Bless")
        cleric.add_spell(bless)

        # Create ally to receive buff
        fighter = Character(
            name="Fighter",
            level=3,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
            hp=26,
            ac=18,
            proficiency_bonus=2
        )

        # Create weak enemy so combat lasts
        goblin = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=100,  # High HP to ensure combat lasts
            ac=15,
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
        )

        # Run combat
        participants = [cleric, fighter, goblin]
        combat = Combat(participants)
        combat.roll_initiative()

        # Simulate several rounds
        max_rounds = 5
        round_count = 0
        while not combat.is_combat_over() and round_count < max_rounds:
            combat.next_turn()
            round_count = combat.current_round

        # Verify fighter or cleric has the buff
        assert fighter.buffs.has_buff("Bless") or cleric.buffs.has_buff("Bless"), \
            "At least one ally should have Bless buff"

    def test_concentration_buff_not_cast_multiple_times(self):
        """Test that concentration buffs are not recast while already active."""
        # Create a Cleric with Bless
        cleric = Character(
            name="Cleric",
            level=3,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 12, 'con': 14, 'int': 10, 'wis': 16, 'cha': 12},
            hp=20,
            ac=16,
            proficiency_bonus=2,
            spell_slots={1: 4, 2: 2}
        )

        # Load and add Bless spell
        spell_manager = SpellManager()
        bless = spell_manager.get_spell("Bless")
        cleric.add_spell(bless)

        # Create ally
        fighter = Character(
            name="Fighter",
            level=3,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
            hp=26,
            ac=18,
            proficiency_bonus=2
        )

        # Create enemy with high HP so combat lasts
        goblin = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=50,
            ac=15,
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
        )

        # Run combat
        participants = [cleric, fighter, goblin]
        combat = Combat(participants)
        combat.roll_initiative()

        # Track initial spell slots
        initial_slots = cleric.spell_slots_remaining.get(1, 0)

        # Simulate several rounds
        max_rounds = 5
        while not combat.is_combat_over() and combat.current_round < max_rounds:
            combat.next_turn()

        # Count how many times Bless was cast
        log = combat.get_combat_log()
        bless_cast_count = 0
        for entry in log:
            if entry['type'] == 'action':
                result = entry['result']
                if result.get('buff_applied') and result.get('buff_name') == 'Bless':
                    bless_cast_count += 1

        # Verify Bless was only cast once
        assert bless_cast_count == 1, f"Bless should be cast only once, but was cast {bless_cast_count} times"

        # Verify only one spell slot was used
        slots_used = initial_slots - cleric.spell_slots_remaining.get(1, 0)
        assert slots_used == 1, f"Only 1 spell slot should be used, but {slots_used} were used"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
