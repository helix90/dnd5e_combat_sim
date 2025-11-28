"""Test buff and status effect system."""
import pytest
from models.buffs import Buff, BuffManager, create_bless_buff
from models.character import Character
from models.spells import Spell
from models.spell_manager import SpellManager


class TestBuffSystem:
    """Test the buff system functionality."""

    def test_buff_creation(self):
        """Test creating a basic buff."""
        buff = Buff(
            name="Test Buff",
            source="Caster",
            duration_rounds=5,
            bonus_dice="1d4",
            affects=["attack_rolls"]
        )
        assert buff.name == "Test Buff"
        assert buff.source == "Caster"
        assert buff.rounds_remaining == 5

    def test_buff_roll_bonus(self):
        """Test rolling buff bonuses."""
        buff = Buff(
            name="Static Buff",
            source="Caster",
            bonus_static=2,
            affects=["attack_rolls"]
        )
        assert buff.roll_bonus() == 2

        # Test dice-based buff returns value in range
        dice_buff = Buff(
            name="Dice Buff",
            source="Caster",
            bonus_dice="1d4",
            affects=["attack_rolls"]
        )
        for _ in range(10):
            bonus = dice_buff.roll_bonus()
            assert 1 <= bonus <= 4

    def test_buff_manager_add_buff(self):
        """Test adding buffs to a buff manager."""
        manager = BuffManager()
        buff = create_bless_buff("Cleric")

        manager.add_buff(buff)
        assert len(manager) == 1
        assert manager.has_buff("Bless")

    def test_buff_manager_calculate_bonus(self):
        """Test calculating total bonus from multiple buffs."""
        manager = BuffManager()

        # Add a static bonus buff
        buff1 = Buff(
            name="Buff 1",
            source="Caster1",
            bonus_static=2,
            affects=["attack_rolls"]
        )
        manager.add_buff(buff1)

        # Should get the static bonus
        bonus = manager.calculate_total_bonus("attack_rolls")
        assert bonus == 2

    def test_buff_manager_tick_round(self):
        """Test buff expiration."""
        manager = BuffManager()

        buff = Buff(
            name="Short Buff",
            source="Caster",
            duration_rounds=2,
            bonus_static=1,
            affects=["attack_rolls"]
        )
        manager.add_buff(buff)
        assert len(manager) == 1

        # Tick once - buff should still be active
        manager.tick_round()
        assert len(manager) == 1

        # Tick again - buff should expire
        manager.tick_round()
        assert len(manager) == 0

    def test_concentration_conflict(self):
        """Test that concentration buffs remove other concentration buffs from the same caster."""
        manager = BuffManager()

        buff1 = Buff(
            name="Concentration Buff 1",
            source="Wizard",
            concentration=True,
            bonus_static=1,
            affects=["attack_rolls"]
        )
        manager.add_buff(buff1)
        assert manager.has_buff("Concentration Buff 1")

        # Add another concentration buff from the same caster
        buff2 = Buff(
            name="Concentration Buff 2",
            source="Wizard",
            concentration=True,
            bonus_static=2,
            affects=["saving_throws"]
        )
        manager.add_buff(buff2)

        # First buff should be removed
        assert not manager.has_buff("Concentration Buff 1")
        assert manager.has_buff("Concentration Buff 2")
        assert len(manager) == 1

    def test_bless_spell_integration(self):
        """Test that Bless spell is properly configured as a buff spell."""
        spell_manager = SpellManager()
        bless = spell_manager.get_spell("Bless")

        assert bless is not None
        assert bless.is_buff_spell is True
        assert bless.buff_data is not None
        assert bless.buff_data.get("bonus_dice") == "1d4"
        assert "attack_rolls" in bless.buff_data.get("affects", [])
        assert "saving_throws" in bless.buff_data.get("affects", [])

    def test_character_has_buff_manager(self):
        """Test that characters have buff managers."""
        character = Character(
            name="Test Character",
            level=1,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
            hp=12,
            ac=16,
            proficiency_bonus=2
        )

        assert hasattr(character, 'buffs')
        assert isinstance(character.buffs, BuffManager)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
