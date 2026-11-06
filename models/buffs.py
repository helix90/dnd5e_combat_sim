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
    affects: List[str] = field(
        default_factory=list
    )  # ['attack_rolls', 'saving_throws', etc.]
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
            if "d" in dice_str:
                num, die = dice_str.split("d")
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
            b for b in self.active_buffs if not (b.concentration and b.source == caster)
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

    def grants(self, kind: str, roll_key: str) -> bool:
        """
        True if any active buff grants `kind` ('advantage' or 'disadvantage') on roll_key.
        See models/rolls.py for the roll keys.
        """
        return any(roll_key in b.metadata.get(kind, ()) for b in self.active_buffs)

    def get_condition(self, condition: str) -> Optional[Buff]:
        """Return the active buff representing a condition (e.g. 'paralyzed'), if any."""
        return next(
            (b for b in self.active_buffs if b.metadata.get("condition") == condition),
            None,
        )

    def has_condition(self, condition: str) -> bool:
        """Check if a condition (e.g. 'paralyzed') is active."""
        return self.get_condition(condition) is not None

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
        metadata={"spell_level": 1},
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
        metadata={"one_use": True, "die_size": die_size},
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
        metadata={"one_use": True},
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
        metadata={"spell_level": 1},
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
        metadata={"spell_level": 3, "advantage": ["saving_throws:dex"]},
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
        metadata={"spell_level": 1, "temp_hp_per_round": caster_mod},
    )


def create_paralyzed_condition(
    source: str, save_type: str, save_dc: int, duration: int = 10
) -> Buff:
    """
    Create the Paralyzed condition (e.g. from a ghoul's attack).

    Paralyzed: incapacitated, automatically fails STR and DEX saves, attacks against
    it have advantage, and melee hits against it are critical hits. The creature
    repeats the saving throw at the end of each of its turns, ending the effect on a
    success. Lasts up to 1 minute (10 rounds).
    """
    return Buff(
        name="Paralyzed",
        source=source,
        duration_rounds=duration,
        affects=[],
        concentration=False,
        metadata={
            "condition": "paralyzed",
            "save_type": save_type,
            "save_dc": save_dc,
            "advantage": ["attacks_against"],
        },
    )


def is_paralyzed(creature: Any) -> bool:
    """True if the creature currently has the Paralyzed condition."""
    buffs = getattr(creature, "buffs", None)
    # isinstance guards against test doubles whose auto-created attributes are truthy
    return isinstance(buffs, BuffManager) and buffs.has_condition("paralyzed")


def create_stunned_condition(source: str) -> Buff:
    """
    The Stunned condition (Stunning Strike): incapacitated, automatically fails STR and DEX
    saves, and attacks against it have advantage. Stunning Strike's lasts until the end of the
    monk's next turn: Combat removes it then (see metadata 'ends_after_turn_of'). The two-round
    duration ends it anyway if the monk goes down before then.
    """
    return Buff(
        name="Stunned",
        source=source,
        duration_rounds=2,
        metadata={
            "condition": "stunned",
            "advantage": ["attacks_against"],
            "ends_after_turn_of": source,
            "turns_left": 2,  # the rest of the monk's current turn, then its next one
        },
    )


def create_turned_condition(source: str, duration: int = 10) -> Buff:
    """
    Turned (Turn Undead): for 1 minute, or until it takes damage, the creature spends its turns
    moving away from the cleric, can't take reactions, and takes no other action than Dash.
    """
    return Buff(
        name="Turned",
        source=source,
        duration_rounds=duration,
        metadata={"condition": "turned", "ends_on_damage": True},
    )


def create_unconscious_condition(source: str, duration: int = 10) -> Buff:
    """
    Unconscious from Sleep, for 1 minute or until it takes damage: incapacitated, automatically
    fails STR and DEX saves, attacks against it have advantage and hits from within 5 ft are
    critical hits.
    """
    return Buff(
        name="Asleep",
        source=source,
        duration_rounds=duration,
        metadata={
            "condition": "unconscious",
            "incapacitated": True,
            "fails_str_dex": True,
            "melee_crits": True,
            "ends_on_damage": True,
            "advantage": ["attacks_against"],
        },
    )


def create_restrained_condition(
    source: str, spell: str, escape_dc: int, duration: int = 10
) -> Buff:
    """
    Restrained by Entangle or Web while the caster concentrates: speed 0, attacks against it have
    advantage, and it has disadvantage on attacks and DEX saves. It can use its action for a STR
    check against escape_dc to break free.
    """
    return Buff(
        name="Restrained",
        source=source,
        duration_rounds=duration,
        concentration=True,
        metadata={
            "condition": "restrained",
            "spell": spell,
            "escape_dc": escape_dc,
            "speed_zero": True,
            "advantage": ["attacks_against"],
            "disadvantage": ["attack_rolls", "saving_throws:dex"],
        },
    )


def create_hypnotized_condition(source: str, duration: int = 10) -> Buff:
    """
    Hypnotic Pattern, while the caster concentrates: charmed and incapacitated with a speed of 0,
    until it takes damage.
    """
    return Buff(
        name="Hypnotized",
        source=source,
        duration_rounds=duration,
        concentration=True,
        metadata={
            "condition": "hypnotized",
            "charmed": True,
            "incapacitated": True,
            "speed_zero": True,
            "ends_on_damage": True,
        },
    )


def create_prone_condition(source: str) -> Buff:
    """
    Prone (knocked down by a wolf's bite): attacks against it have advantage from within 5 ft and
    disadvantage from farther away (see rolls.attack_roll), and its own attacks have disadvantage.
    It lasts until the creature stands up at the start of its turn, which costs half its speed.
    """
    return Buff(
        name="Prone",
        source=source,
        duration_rounds=-1,
        metadata={"condition": "prone", "disadvantage": ["attack_rolls"]},
    )


def create_stood_up_effect() -> Buff:
    """Standing up from prone used half the creature's movement this turn."""
    return Buff(
        name="Stood Up",
        source="",
        duration_rounds=1,
        metadata={"half_speed": True, "until_own_turn_end": True},
    )


def create_infernal_wound(source: str, dice: str) -> Buff:
    """
    A horned devil's infernal wound: the creature loses hit points (dice) at the start of each of
    its turns. Each further hit from the tail adds to it, and magical healing closes it.
    """
    return Buff(
        name="Infernal Wound",
        source=source,
        duration_rounds=-1,
        metadata={"condition": "infernal_wound", "wound_dice": [dice]},
    )


def create_poisoned_condition(source: str) -> Buff:
    """
    Poisoned by a ghast's Stench until the start of the creature's next turn: disadvantage on
    its attack rolls.
    """
    return Buff(
        name="Poisoned",
        source=source,
        duration_rounds=-1,
        metadata={
            "condition": "poisoned",
            "disadvantage": ["attack_rolls"],
            "until_turn_start": True,
        },
    )


def create_mummy_rot(source: str) -> Buff:
    """
    Cursed with mummy rot: the creature can't regain hit points (its maximum also withers every 24
    hours, which never matters within a fight). Only Remove Curse ends it.
    """
    return Buff(
        name="Mummy Rot",
        source=source,
        duration_rounds=-1,
        metadata={"condition": "mummy_rot", "no_healing": True},
    )


def cannot_regain_hp(creature: Any) -> bool:
    """True if the creature can't regain hit points (mummy rot)."""
    return has_flag(creature, "no_healing")


def is_prone(creature: Any) -> bool:
    """True if the creature is prone."""
    return _has(creature, "prone")


def close_wounds(creature: Any) -> List[str]:
    """Magical healing closes infernal wounds. Returns the names of the effects ended."""
    buffs = getattr(creature, "buffs", None)
    if not isinstance(buffs, BuffManager):
        return []
    closed = [
        b.name
        for b in buffs.active_buffs
        if b.metadata.get("condition") == "infernal_wound"
    ]
    if closed:
        buffs.active_buffs = [
            b
            for b in buffs.active_buffs
            if b.metadata.get("condition") != "infernal_wound"
        ]
    return closed


def has_condition(creature: Any, condition: str) -> bool:
    """True if the creature has the named condition ('restrained', 'poisoned', ...)."""
    buffs = getattr(creature, "buffs", None)
    return isinstance(buffs, BuffManager) and buffs.has_condition(condition)


_has = has_condition


def is_stunned(creature: Any) -> bool:
    """True if the creature currently has the Stunned condition."""
    return _has(creature, "stunned")


def is_turned(creature: Any) -> bool:
    """True if the creature is turned (Turn Undead)."""
    return _has(creature, "turned")


def has_flag(creature: Any, flag: str) -> bool:
    """True if any active effect on the creature sets this metadata flag."""
    buffs = getattr(creature, "buffs", None)
    return isinstance(buffs, BuffManager) and any(
        b.metadata.get(flag) for b in buffs.active_buffs
    )


def is_incapacitated(creature: Any) -> bool:
    """Paralyzed, stunned, asleep (Sleep) and hypnotized creatures are incapacitated: no actions
    or reactions."""
    return (
        is_paralyzed(creature)
        or is_stunned(creature)
        or has_flag(creature, "incapacitated")
    )


def fails_str_dex_saves(creature: Any) -> bool:
    """Paralyzed, stunned and unconscious creatures automatically fail STR and DEX saves."""
    return (
        is_paralyzed(creature)
        or is_stunned(creature)
        or has_flag(creature, "fails_str_dex")
    )


def melee_hits_crit(creature: Any) -> bool:
    """Hits from within 5 ft against a paralyzed or unconscious creature are critical hits."""
    return is_paralyzed(creature) or has_flag(creature, "melee_crits")


def is_spellbound(creature: Any) -> bool:
    """Out of the fight until it takes damage (turned, asleep, hypnotized): best left alone while
    there are other enemies."""
    return has_flag(creature, "ends_on_damage")


def cannot_move(creature: Any) -> bool:
    """Restrained or hypnotized: speed 0."""
    return has_flag(creature, "speed_zero")


def end_on_damage(creature: Any) -> List[str]:
    """Damage ends turning, magical sleep and Hypnotic Pattern. Returns the names of the effects ended."""
    buffs = getattr(creature, "buffs", None)
    if not isinstance(buffs, BuffManager):
        return []
    ended = [b.name for b in buffs.active_buffs if b.metadata.get("ends_on_damage")]
    if ended:
        buffs.active_buffs = [
            b for b in buffs.active_buffs if not b.metadata.get("ends_on_damage")
        ]
    return ended


def metadata_total(creature: Any, key: str) -> int:
    """Sum of a numeric metadata value over the creature's active effects (Magic Weapon's +1)."""
    buffs = getattr(creature, "buffs", None)
    if not isinstance(buffs, BuffManager):
        return 0
    return sum(
        b.metadata.get(key, 0)
        for b in buffs.active_buffs
        if isinstance(b.metadata.get(key, 0), int)
    )
