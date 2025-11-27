"""
Test that characters can heal themselves when injured.

This test validates the fix for the bug where characters were excluded from
the allies list in combat_state, preventing them from healing themselves.
"""
import pytest
from models.character import Character
from models.monster import Monster
from models.combat import Combat
from models.spells import Spell
from ai.strategy import PartyAIStrategy


class TestSelfHealing:
    """Test that characters can heal themselves."""

    def test_character_can_heal_self_when_injured(self):
        """Test that a cleric heals themselves when below HP threshold."""
        # Create a cleric with healing spell
        cleric = Character(
            name="Branwen",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 14, 'dex': 10, 'con': 14, 'int': 10, 'wis': 18, 'cha': 12},
            hp=9,  # Low HP - 24% of max HP (triggers healing at <25%)
            ac=18,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3}
        )
        cleric.max_hp = 38  # Set max HP to make 9/38 = 24%

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

        # Create a weak enemy so combat doesn't end immediately
        goblin = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=7,
            ac=13,
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
        )

        # Create AI and combat state
        ai = PartyAIStrategy()
        combat_state = {
            'allies': [cleric],  # Cleric should be in allies list (can heal self)
            'enemies': [goblin],
            'round': 1
        }

        # Cleric should choose to heal themselves
        action = ai.choose_action(cleric, combat_state)

        # Should be a healing spell cast
        assert action['type'] == 'cast_spell', f"Expected cast_spell, got {action['type']}"
        assert action['spell'].spell.name == 'Cure Wounds', "Should cast Cure Wounds"
        assert action['target'] == cleric, "Should target self for healing"

    def test_cleric_heals_self_in_full_combat(self):
        """Test that cleric heals themselves in a full combat scenario."""
        # Create cleric with low HP
        cleric = Character(
            name="Branwen",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 14, 'dex': 10, 'con': 14, 'int': 10, 'wis': 18, 'cha': 12},
            hp=5,  # VERY low HP (13% of max - should trigger critical healing)
            ac=18,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3}
        )
        cleric.max_hp = 38

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

        # Create other party members with full HP
        fighter = Character(
            name="Aldric",
            level=5,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 18, 'dex': 14, 'con': 16, 'int': 10, 'wis': 12, 'cha': 10},
            hp=45,  # Full HP
            ac=18,
            proficiency_bonus=3
        )
        fighter.max_hp = 45

        # Weak enemy
        goblin = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=7,
            ac=13,
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
        )

        # Run a combat turn with the full _build_combat_state method
        combat = Combat([cleric, fighter, goblin])

        # Build combat state for cleric using the actual Combat method
        combat_state = combat._build_combat_state(cleric)

        # Verify cleric is IN the allies list
        assert cleric in combat_state['allies'], "Cleric should be in allies list (can heal self)"

        # Verify AI chooses to heal self
        ai = PartyAIStrategy()
        action = ai.choose_action(cleric, combat_state)

        assert action['type'] == 'cast_spell', "Should cast a spell"
        assert action['target'] == cleric, "Should heal self (cleric is most injured)"

    def test_character_heals_other_ally_when_ally_more_injured(self):
        """Test that character heals most injured ally (not always self)."""
        # Create cleric with moderate HP
        cleric = Character(
            name="Branwen",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 14, 'dex': 10, 'con': 14, 'int': 10, 'wis': 18, 'cha': 12},
            hp=30,  # 79% HP (not low)
            ac=18,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3}
        )
        cleric.max_hp = 38

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

        # Create fighter with VERY low HP (more injured than cleric)
        fighter = Character(
            name="Aldric",
            level=5,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 18, 'dex': 14, 'con': 16, 'int': 10, 'wis': 12, 'cha': 10},
            hp=5,  # 11% HP (critical)
            ac=18,
            proficiency_bonus=3
        )
        fighter.max_hp = 45

        goblin = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=7,
            ac=13,
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
        )

        # Build combat state
        combat = Combat([cleric, fighter, goblin])
        combat_state = combat._build_combat_state(cleric)

        # Verify both cleric AND fighter are in allies list
        assert cleric in combat_state['allies']
        assert fighter in combat_state['allies']

        # Cleric should heal the fighter (more injured)
        ai = PartyAIStrategy()
        action = ai.choose_action(cleric, combat_state)

        assert action['type'] == 'cast_spell'
        assert action['target'] == fighter, "Should heal most injured ally (fighter at 11% HP)"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
