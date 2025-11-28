"""Integration tests for buff spells in combat."""
import pytest
from models.character import Character
from models.monster import Monster
from models.spells import Spell, SpellAction
from models.spell_manager import SpellManager
from models.actions import AttackAction


class TestBuffSpellIntegration:
    """Test that buff spells work correctly in combat scenarios."""

    def test_bless_spell_application(self):
        """Test that casting Bless applies a buff to the target."""
        # Create a cleric who can cast Bless
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

        # Create a fighter to receive the buff
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

        # Load Bless spell
        spell_manager = SpellManager()
        bless_spell = spell_manager.get_spell("Bless")
        cleric.add_spell(bless_spell)

        # Verify Bless is a buff spell
        assert bless_spell.is_buff_spell is True

        # Cast Bless on the fighter
        result = cleric.cast_spell("Bless", fighter, spell_slot_level=1)

        # Verify the spell was cast successfully
        assert result['success'] is True
        assert result['buff_applied'] is True
        assert result['buff_name'] == "Bless"

        # Verify the fighter now has the Bless buff
        assert fighter.buffs.has_buff("Bless")
        assert len(fighter.buffs) == 1

    def test_bless_buff_affects_attack_rolls(self):
        """Test that Bless buff actually increases attack rolls."""
        # Create attacker with Bless
        attacker = Character(
            name="Attacker",
            level=1,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
            hp=12,
            ac=16,
            proficiency_bonus=2
        )

        # Create target
        target = Monster(
            name="Goblin",
            challenge_rating="1/4",
            hp=7,
            ac=15,
            ability_scores={'str': 8, 'dex': 14, 'con': 10, 'int': 10, 'wis': 8, 'cha': 8}
        )

        # Add Bless buff to attacker
        from models.buffs import create_bless_buff
        bless = create_bless_buff("Cleric", duration=10)
        attacker.buffs.add_buff(bless)

        # Create an attack action
        attack = AttackAction(
            name="Longsword Attack",
            description="Attack with longsword",
            weapon_name="Longsword",
            damage_dice="1d8",
            damage_type="slashing",
            weapon_type="melee"
        )

        # Execute multiple attacks and verify buff_bonus is present and in range
        for _ in range(10):
            result = attack.execute(attacker, target)

            # Verify buff_bonus is in the result
            assert 'buff_bonus' in result

            # Verify buff_bonus is between 1 and 4 (1d4)
            assert 1 <= result['buff_bonus'] <= 4

            # Verify total_attack includes the buff bonus
            expected_total = result['attack_roll'] + result['hit_bonus'] + result['buff_bonus']
            assert result['total_attack'] == expected_total

    def test_bless_buff_affects_saving_throws(self):
        """Test that Bless buff increases saving throws."""
        # Create a character with Bless
        character = Character(
            name="Blessed Character",
            level=1,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
            hp=12,
            ac=16,
            proficiency_bonus=2,
            saving_throw_proficiencies=['str', 'con']
        )

        # Add Bless buff
        from models.buffs import create_bless_buff
        bless = create_bless_buff("Cleric", duration=10)
        character.buffs.add_buff(bless)

        # Create a spell that requires a save
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
            save_type="dex",
            save_dc_bonus=0,
            description="A bright streak flashes from your pointing finger.",
            is_attack_spell=False,
            healing=False,
            area_effect=True,
            concentration=False
        )

        # Create a caster for the fireball
        caster = Character(
            name="Wizard",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={'str': 8, 'dex': 14, 'con': 12, 'int': 18, 'wis': 12, 'cha': 10},
            hp=22,
            ac=12,
            proficiency_bonus=3,
            spell_slots={1: 4, 2: 3, 3: 2}
        )
        caster.add_spell(fireball)

        # Cast fireball at the blessed character
        initial_hp = character.hp
        result = caster.cast_spell("Fireball", character, spell_slot_level=3)

        # Verify buff_bonus is in the saving throw result
        assert 'buff_bonus' in result
        assert 1 <= result['buff_bonus'] <= 4

        # Verify total_save includes the buff bonus
        expected_total = result['save_roll'] + result['save_bonus'] + result['buff_bonus']
        assert result['total_save'] == expected_total

    def test_buff_expiration_after_duration(self):
        """Test that buffs expire after their duration."""
        character = Character(
            name="Character",
            level=1,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
            hp=12,
            ac=16,
            proficiency_bonus=2
        )

        # Add a buff with 3 rounds duration
        from models.buffs import Buff
        buff = Buff(
            name="Short Buff",
            source="Caster",
            duration_rounds=3,
            bonus_static=2,
            affects=["attack_rolls"]
        )
        character.buffs.add_buff(buff)

        assert len(character.buffs) == 1

        # Tick 1 - buff still active
        character.buffs.tick_round()
        assert len(character.buffs) == 1

        # Tick 2 - buff still active
        character.buffs.tick_round()
        assert len(character.buffs) == 1

        # Tick 3 - buff expires
        character.buffs.tick_round()
        assert len(character.buffs) == 0

    def test_concentration_spell_replaces_previous(self):
        """Test that casting a concentration spell ends previous concentration spells."""
        caster = Character(
            name="Wizard",
            level=5,
            character_class="Wizard",
            race="Human",
            ability_scores={'str': 8, 'dex': 14, 'con': 12, 'int': 18, 'wis': 12, 'cha': 10},
            hp=22,
            ac=12,
            proficiency_bonus=3,
            spell_slots={1: 4, 2: 3}
        )

        target = Character(
            name="Fighter",
            level=3,
            character_class="Fighter",
            race="Human",
            ability_scores={'str': 16, 'dex': 14, 'con': 14, 'int': 10, 'wis': 10, 'cha': 10},
            hp=26,
            ac=18,
            proficiency_bonus=2
        )

        # Load spells
        spell_manager = SpellManager()

        # Cast Bless (concentration)
        bless = spell_manager.get_spell("Bless")
        caster.add_spell(bless)
        result1 = caster.cast_spell("Bless", target, spell_slot_level=1)

        assert result1['buff_applied'] is True
        assert target.buffs.has_buff("Bless")

        # Create and cast another concentration spell (Shield of Faith)
        shield_of_faith = Spell(
            name="Shield of Faith",
            level=1,
            school="Abjuration",
            casting_time="1 bonus action",
            range="60 feet",
            duration="10 minutes",
            components={'verbal': True, 'somatic': True, 'material': True},
            damage_dice=None,
            damage_type=None,
            save_type=None,
            description="A shimmering field appears and surrounds a creature of your choice within range.",
            is_attack_spell=False,
            healing=False,
            area_effect=False,
            concentration=True,
            is_buff_spell=True,
            buff_data={
                "name": "Shield of Faith",
                "duration_rounds": 100,
                "bonus_static": 2,
                "affects": ["armor_class"],
                "concentration": True
            }
        )
        caster.add_spell(shield_of_faith)
        result2 = caster.cast_spell("Shield of Faith", target, spell_slot_level=1)

        assert result2['buff_applied'] is True

        # Bless should be removed (same caster, both concentration)
        assert not target.buffs.has_buff("Bless")
        assert target.buffs.has_buff("Shield of Faith")

    def test_buff_without_target_having_buffs_attribute(self):
        """Test that buff spells fail gracefully on targets without buffs attribute."""
        # Create a simple object without buffs
        class SimpleTarget:
            def __init__(self):
                self.name = "Simple Target"
                self.hp = 10

        caster = Character(
            name="Cleric",
            level=3,
            character_class="Cleric",
            race="Human",
            ability_scores={'str': 10, 'dex': 12, 'con': 14, 'int': 10, 'wis': 16, 'cha': 12},
            hp=20,
            ac=16,
            proficiency_bonus=2,
            spell_slots={1: 4}
        )

        spell_manager = SpellManager()
        bless = spell_manager.get_spell("Bless")
        caster.add_spell(bless)

        target = SimpleTarget()
        result = caster.cast_spell("Bless", target, spell_slot_level=1)

        # Should handle gracefully
        assert result['buff_applied'] is False
        assert 'reason' in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
