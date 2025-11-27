"""Test dice notation parsing with modifiers like 1d4+1."""
import pytest
from models.spells import Spell


class TestDiceModifierParsing:
    """Test that dice notation with modifiers is parsed correctly."""

    def test_dice_with_plus_modifier(self):
        """Test parsing dice notation with + modifier (e.g., 1d4+1)."""
        spell = Spell(
            name="Magic Missile",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="120 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d4+1",  # This should parse correctly
            damage_type="force"
        )

        # Calculate damage multiple times to ensure consistency
        for _ in range(10):
            damage = spell.calculate_damage(caster_level=1)
            # 1d4+1 should give values between 2 and 5
            assert 2 <= damage <= 5, f"Damage {damage} out of range for 1d4+1"

    def test_dice_with_minus_modifier(self):
        """Test parsing dice notation with - modifier (e.g., 2d6-2)."""
        spell = Spell(
            name="Test Spell",
            level=1,
            school="Evocation",
            casting_time="1 action",
            range="60 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="2d6-2",
            damage_type="cold"
        )

        for _ in range(10):
            damage = spell.calculate_damage(caster_level=1)
            # 2d6-2 should give values between 0 and 10
            assert 0 <= damage <= 10, f"Damage {damage} out of range for 2d6-2"

    def test_dice_without_modifier(self):
        """Test parsing standard dice notation without modifier (e.g., 8d6)."""
        spell = Spell(
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

        for _ in range(10):
            damage = spell.calculate_damage(caster_level=5)
            # 8d6 should give values between 8 and 48
            assert 8 <= damage <= 48, f"Damage {damage} out of range for 8d6"

    def test_cantrip_scaling_with_modifier(self):
        """Test that cantrip scaling works with modifiers."""
        spell = Spell(
            name="Test Cantrip",
            level=0,  # Cantrip
            school="Evocation",
            casting_time="1 action",
            range="60 feet",
            duration="Instantaneous",
            components={'verbal': True, 'somatic': True, 'material': False},
            damage_dice="1d10+2",
            damage_type="force",
            is_attack_spell=True
        )

        # Level 1 character: 1d10+2 (3-12 damage)
        for _ in range(10):
            damage = spell.calculate_damage(caster_level=1)
            assert 3 <= damage <= 12

        # Level 5 character: 2d10+2 (4-22 damage) - cantrips scale at level 5
        for _ in range(10):
            damage = spell.calculate_damage(caster_level=5)
            assert 4 <= damage <= 22

        # Level 11 character: 3d10+2 (5-32 damage)
        for _ in range(10):
            damage = spell.calculate_damage(caster_level=11)
            assert 5 <= damage <= 32


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
