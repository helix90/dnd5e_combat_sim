"""
Test that wizards use offensive spells aggressively in early rounds.
"""
import pytest
from models.character import Character
from models.monster import Monster
from models.spells import Spell
from ai.strategy import PartyAIStrategy


class TestWizardAggressiveAI:
    """Test that wizards prioritize offensive spells in early combat rounds."""

    def test_wizard_uses_offensive_spells_in_early_rounds(self):
        """Test that a wizard casts offensive spells (not cantrips) in rounds 1-5."""
        # Create a level 5 wizard with offensive spells
        wizard = Character(
            name="Calyra",
            level=5,
            character_class="Wizard",
            race="Elf",
            ability_scores={'str': 8, 'dex': 14, 'con': 12, 'int': 18, 'wis': 12, 'cha': 10},
            hp=28,
            ac=13,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3, '3': 2}
        )

        # Add offensive spells
        fireball = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )

        scorching_ray = Spell(
            name="Scorching Ray",
            level=2,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="6d6",
            damage_type="fire",
            is_attack_spell=True
        )

        magic_missile = Spell(
            name="Magic Missile",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="3d4",
            damage_type="force"
        )

        fire_bolt = Spell(
            name="Fire Bolt",
            level=0,  # Cantrip
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="2d10",
            damage_type="fire",
            is_attack_spell=True
        )

        wizard.add_spell(fireball)
        wizard.add_spell(scorching_ray)
        wizard.add_spell(magic_missile)
        wizard.add_spell(fire_bolt)

        # Create an enemy
        enemy = Monster(
            name="Orc",
            challenge_rating="1",
            hp=15,
            ac=13,
            ability_scores={'str': 16, 'dex': 12, 'con': 16, 'int': 7, 'wis': 11, 'cha': 10}
        )

        # Create AI strategy
        ai = PartyAIStrategy()

        # Test rounds 1-5 (early combat)
        for round_num in range(1, 6):
            combat_state = {
                'allies': [],
                'enemies': [enemy],
                'round': round_num
            }

            action = ai.choose_action(wizard, combat_state)

            # Wizard should cast a leveled spell (not a cantrip)
            assert action['type'] == 'cast_spell', f"Round {round_num}: Expected cast_spell, got {action['type']}"

            spell_action = action['spell']
            spell = spell_action.spell

            # Should be a leveled damage spell, not a cantrip
            assert spell.level > 0, f"Round {round_num}: Wizard used cantrip {spell.name} instead of leveled spell"
            assert spell.damage_dice is not None, f"Round {round_num}: Spell {spell.name} has no damage"

            # Should prioritize highest level spells first
            # Fireball (level 3) should be used first if slots available
            if wizard.spell_slots_remaining.get('3', 0) > 0 or wizard.spell_slots_remaining.get(3, 0) > 0:
                assert spell.level == 3, f"Round {round_num}: Should use Fireball (lvl 3), used {spell.name} (lvl {spell.level})"
            elif wizard.spell_slots_remaining.get('2', 0) > 0 or wizard.spell_slots_remaining.get(2, 0) > 0:
                assert spell.level == 2, f"Round {round_num}: Should use Scorching Ray (lvl 2), used {spell.name} (lvl {spell.level})"
            elif wizard.spell_slots_remaining.get('1', 0) > 0 or wizard.spell_slots_remaining.get(1, 0) > 0:
                assert spell.level == 1, f"Round {round_num}: Should use Magic Missile (lvl 1), used {spell.name} (lvl {spell.level})"

    def test_wizard_falls_back_to_cantrips_after_early_rounds(self):
        """Test that wizards conserve spell slots after round 5."""
        wizard = Character(
            name="Calyra",
            level=5,
            character_class="Wizard",
            race="Elf",
            ability_scores={'str': 8, 'dex': 14, 'con': 12, 'int': 18, 'wis': 12, 'cha': 10},
            hp=28,
            ac=13,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3, '3': 2}
        )

        # Add spells
        fireball = Spell(
            name="Fireball",
            level=3,
            school="Evocation",
            casting_time="1 action",
            range="150 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': True},
            damage_dice="8d6",
            damage_type="fire",
            save_type="dex"
        )

        fire_bolt = Spell(
            name="Fire Bolt",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="2d10",
            damage_type="fire",
            is_attack_spell=True
        )

        wizard.add_spell(fireball)
        wizard.add_spell(fire_bolt)

        # Add Fire Bolt as an action (so it can be selected as cantrip)
        from models.actions import AttackAction
        fire_bolt_action = AttackAction(
            name="Fire Bolt",
            description="Ranged spell attack",
            weapon_name="Fire Bolt",
            damage_dice="2d10",
            damage_type="fire",
            weapon_type="ranged"
        )
        wizard.actions.append(fire_bolt_action)

        enemy = Monster(
            name="Orc",
            challenge_rating="1",
            hp=15,
            ac=13,
            ability_scores={'str': 16, 'dex': 12, 'con': 16, 'int': 7, 'wis': 11, 'cha': 10}
        )

        ai = PartyAIStrategy()

        # Test round 6 (after aggressive phase)
        combat_state = {
            'allies': [],
            'enemies': [enemy],
            'round': 6
        }

        action = ai.choose_action(wizard, combat_state)

        # Should use cantrip (Fire Bolt) to conserve spell slots
        # Either as an attack action or cast_spell with cantrip
        if action['type'] == 'attack':
            assert action['action'].name == 'Fire Bolt'
        elif action['type'] == 'cast_spell':
            # If casting a spell, it should be a cantrip
            assert action['spell'].spell.level == 0

    def test_cleric_not_affected_by_aggressive_strategy(self):
        """Test that clerics (who have healing) don't use aggressive spell strategy."""
        cleric = Character(
            name="Branwen",
            level=5,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 14, 'dex': 10, 'con': 14, 'int': 10, 'wis': 18, 'cha': 12},
            hp=38,
            ac=18,
            proficiency_bonus=3,
            spell_slots={'1': 4, '2': 3, '3': 2}
        )

        # Add both healing and offensive spells
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

        sacred_flame = Spell(
            name="Sacred Flame",
            level=0,
            school="Evocation",
            casting_time="1 action",
            range="60 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="2d8",
            damage_type="radiant",
            save_type="dex"
        )

        cleric.add_spell(cure_wounds)
        cleric.add_spell(sacred_flame)

        # Add Sacred Flame as an action
        from models.actions import AttackAction
        sacred_flame_action = AttackAction(
            name="Sacred Flame",
            description="Ranged spell attack",
            weapon_name="Sacred Flame",
            damage_dice="2d8",
            damage_type="radiant",
            weapon_type="ranged"
        )
        cleric.actions.append(sacred_flame_action)

        enemy = Monster(
            name="Orc",
            challenge_rating="1",
            hp=15,
            ac=13,
            ability_scores={'str': 16, 'dex': 12, 'con': 16, 'int': 7, 'wis': 11, 'cha': 10}
        )

        ai = PartyAIStrategy()

        # Test round 1 (early combat)
        combat_state = {
            'allies': [],
            'enemies': [enemy],
            'round': 1
        }

        action = ai.choose_action(cleric, combat_state)

        # Cleric should NOT use aggressive strategy (has healing spells)
        # Should use cantrip (Sacred Flame) instead of Cure Wounds
        assert action['type'] == 'attack'
        assert action['action'].name == 'Sacred Flame'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
