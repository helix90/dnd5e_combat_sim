"""
Buff and status effect system for D&D 5e Combat Simulator.

Handles temporary bonuses, conditions, and other effects that modify combat.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import random


@dataclass
class Buff:
    """
    Represents a temporary buff or status effect on a character.

    Attributes:
        name: Name of the buff (e.g., "Bless", "Bardic Inspiration")
        source: Who cast/applied the buff
        duration_rounds: How many rounds the buff lasts (-1 for unlimited)
        bonus_type: Type of bonus ('attack', 'save', 'damage', 'ac', 'ability_check')
        bonus_dice: Dice to roll for bonus (e.g., "1d4" for Bless)
        bonus_static: Static numeric bonus
        affects: What the buff affects ('attack_rolls', 'saving_throws', 'damage', etc.)
        concentration: Whether this buff requires concentration
        metadata: Additional buff-specific data
    """
    name: str
    source: str
    duration_rounds: int = -1  # -1 = until end of combat
    bonus_dice: Optional[str] = None  # e.g., "1d4", "1d6", "1d8"
    bonus_static: int = 0
    affects: List[str] = field(default_factory=list)  # ['attack_rolls', 'saving_throws', etc.]
    concentration: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    rounds_remaining: int = field(init=False)

    def __post_init__(self):
        self.rounds_remaining = self.duration_rounds

    def roll_bonus(self) -> int:
        """Calculate the bonus from this buff (roll dice if needed)."""
        total = self.bonus_static

        if self.bonus_dice:
            # Parse dice notation (e.g., "1d4", "2d6")
            dice_str = self.bonus_dice.lower()
            if 'd' in dice_str:
                num, die = dice_str.split('d')
                num = int(num)
                die = int(die)
                rolls = [random.randint(1, die) for _ in range(num)]
                total += sum(rolls)

        return total

    def tick_round(self) -> bool:
        """
        Decrease duration by 1 round.

        Returns:
            bool: True if buff is still active, False if expired
        """
        if self.duration_rounds == -1:
            return True  # Permanent/combat-long buff

        self.rounds_remaining -= 1
        return self.rounds_remaining > 0

    def applies_to(self, roll_type: str) -> bool:
        """Check if this buff applies to a specific type of roll."""
        return roll_type in self.affects

    def __repr__(self) -> str:
        bonus_str = f"{self.bonus_dice}" if self.bonus_dice else f"+{self.bonus_static}"
        return f"Buff({self.name}, {bonus_str}, affects={self.affects})"


class BuffManager:
    """
    Manages active buffs on a character or monster.
    """
    def __init__(self):
        self.active_buffs: List[Buff] = []

    def add_buff(self, buff: Buff) -> None:
        """Add a new buff to the character."""
        # Check if this is a concentration spell and remove other concentration buffs
        if buff.concentration:
            self.remove_concentration_buffs(buff.source)

        self.active_buffs.append(buff)

    def remove_buff(self, buff_name: str) -> None:
        """Remove a buff by name."""
        self.active_buffs = [b for b in self.active_buffs if b.name != buff_name]

    def remove_concentration_buffs(self, caster: str) -> None:
        """Remove all concentration buffs from a specific caster."""
        self.active_buffs = [
            b for b in self.active_buffs
            if not (b.concentration and b.source == caster)
        ]

    def get_buffs_for(self, roll_type: str) -> List[Buff]:
        """Get all buffs that apply to a specific roll type."""
        return [b for b in self.active_buffs if b.applies_to(roll_type)]

    def calculate_total_bonus(self, roll_type: str) -> int:
        """
        Calculate total bonus from all applicable buffs for a roll type.

        Args:
            roll_type: Type of roll ('attack_rolls', 'saving_throws', etc.)

        Returns:
            int: Total bonus to add to the roll
        """
        applicable_buffs = self.get_buffs_for(roll_type)
        total = 0

        for buff in applicable_buffs:
            total += buff.roll_bonus()

        return total

    def tick_round(self) -> None:
        """Advance all buffs by one round and remove expired ones."""
        self.active_buffs = [b for b in self.active_buffs if b.tick_round()]

    def clear_all(self) -> None:
        """Remove all active buffs."""
        self.active_buffs.clear()

    def has_buff(self, buff_name: str) -> bool:
        """Check if a specific buff is active."""
        return any(b.name == buff_name for b in self.active_buffs)

    def get_active_buff_names(self) -> List[str]:
        """Get names of all active buffs."""
        return [b.name for b in self.active_buffs]

    def __len__(self) -> int:
        return len(self.active_buffs)

    def __repr__(self) -> str:
        return f"BuffManager({len(self.active_buffs)} active buffs)"


# Predefined buff factory functions
def create_bless_buff(caster_name: str, duration: int = 10) -> Buff:
    """
    Create a Bless spell buff.

    Bless: +1d4 to attack rolls and saving throws for up to 1 minute (10 rounds)
    """
    return Buff(
        name="Bless",
        source=caster_name,
        duration_rounds=duration,
        bonus_dice="1d4",
        affects=["attack_rolls", "saving_throws"],
        concentration=True,
        metadata={"spell_level": 1}
    )


def create_bardic_inspiration_buff(bard_name: str, die_size: int = 6) -> Buff:
    """
    Create a Bardic Inspiration buff.

    Bardic Inspiration: Can add 1dX to one ability check, attack roll, or saving throw
    within 10 minutes. Die size scales with bard level.

    Args:
        bard_name: Name of the bard granting inspiration
        die_size: Size of inspiration die (6, 8, 10, or 12)
    """
    return Buff(
        name="Bardic Inspiration",
        source=bard_name,
        duration_rounds=100,  # 10 minutes in combat rounds
        bonus_dice=f"1d{die_size}",
        affects=["attack_rolls", "saving_throws", "ability_checks"],
        concentration=False,
        metadata={"one_use": True, "die_size": die_size}
    )


def create_guidance_buff(caster_name: str) -> Buff:
    """
    Create a Guidance cantrip buff.

    Guidance: +1d4 to one ability check within 1 minute
    """
    return Buff(
        name="Guidance",
        source=caster_name,
        duration_rounds=10,
        bonus_dice="1d4",
        affects=["ability_checks"],
        concentration=True,
        metadata={"one_use": True}
    )


def create_shield_of_faith_buff(caster_name: str) -> Buff:
    """
    Create a Shield of Faith spell buff.

    Shield of Faith: +2 to AC for up to 10 minutes
    """
    return Buff(
        name="Shield of Faith",
        source=caster_name,
        duration_rounds=100,
        bonus_static=2,
        affects=["armor_class"],
        concentration=True,
        metadata={"spell_level": 1}
    )


def create_haste_buff(caster_name: str) -> Buff:
    """
    Create a Haste spell buff.

    Haste: +2 AC, advantage on DEX saves, doubled speed, extra action
    """
    return Buff(
        name="Haste",
        source=caster_name,
        duration_rounds=10,
        bonus_static=2,
        affects=["armor_class", "extra_action"],
        concentration=True,
        metadata={"spell_level": 3, "advantage_dex_saves": True}
    )


def create_heroism_buff(caster_name: str, caster_mod: int = 3) -> Buff:
    """
    Create a Heroism spell buff.

    Heroism: Immune to frightened, gain temp HP each turn
    """
    return Buff(
        name="Heroism",
        source=caster_name,
        duration_rounds=10,
        bonus_static=caster_mod,  # Temp HP each turn
        affects=["immunity_frightened", "temp_hp"],
        concentration=True,
        metadata={"spell_level": 1, "temp_hp_per_round": caster_mod}
    )
