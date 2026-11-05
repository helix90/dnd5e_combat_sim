from abc import ABC, abstractmethod
from typing import Any, List, Dict, Protocol, Callable, Optional
import logging
import random

from ai import errors
from models import class_features as feature_rules
from models import concentration, spell_effects
from models.buffs import cannot_regain_hp, is_spellbound
from models.rolls import has_magic_resistance
from models.spells import SpellAction
from models.actions import AttackAction

# Constants for AI behavior tuning
LOW_HP_THRESHOLD = 0.25  # Heal allies below 25% HP
CRITICAL_HP_THRESHOLD = 0.15  # Prioritize healing below 15% HP
SPECIAL_ABILITY_THREAT_BONUS = 2.0
CLASS_FEATURES_THREAT_BONUS = 2.0
HIGH_OPPORTUNITY_COST = 2.0
DEFAULT_OPPORTUNITY_COST = 1.0
LOW_OPPORTUNITY_COST = 0.5
MANY_ENCOUNTERS_THRESHOLD = 2  # Conserve spell slots if more than 2 encounters remain

# Monster targeting strategy probabilities
SPREAD_DAMAGE_PROBABILITY = 0.40  # 40% chance to spread damage
FOCUS_FIRE_PROBABILITY = 0.30  # 30% chance to focus fire on threats
FINISH_WEAK_PROBABILITY = 0.15  # 15% chance to finish weak targets
RANDOM_TARGET_PROBABILITY = 0.15  # 15% chance to pick random target

# Spellcaster classes that should prefer spell attacks
SPELLCASTER_CLASSES = {'Wizard', 'Cleric', 'Sorcerer', 'Warlock', 'Druid', 'Bard'}

# Pure offensive caster classes (no healing spells typically)
OFFENSIVE_CASTER_CLASSES = {'Wizard', 'Sorcerer', 'Warlock'}

# Common damaging cantrips
DAMAGING_CANTRIPS = {'Fire Bolt', 'Sacred Flame', 'Eldritch Blast', 'Ray of Frost', 'Produce Flame'}

# Early combat rounds where offensive casters should be aggressive with spell slots
AGGRESSIVE_SPELL_ROUNDS = 5

logger = logging.getLogger(__name__)

# Spells with an effect besides damage and healing (see models/spell_effects.py)
# Sleep is worth a slot if it puts this many enemies to sleep (on average)
SLEEP_MIN_ENEMIES = 2
SLEEP_AVERAGE_POOL = 22.5
# Entangle, Web and Hypnotic Pattern are worth a slot if this many enemies are expected to fail the save
CONTROL_MIN_AFFECTED = 1.5
# Mass Cure Wounds (or another spell healing several creatures) once this many allies need healing
MASS_HEAL_MIN_ALLIES = 3
# Hold Monster is worth a 5th-level slot when the target is at least this likely to fail its WIS save
HOLD_MIN_FAIL_CHANCE = 0.5
# Moonbeam and Call Lightning are worth their slot against enemies with at least this many hit points left
LASTING_SPELL_MIN_HP = 25
# Mirror Image once the caster is below this share of its hit points
MIRROR_IMAGE_HP = 0.75


def combat_spells(combatant: Any) -> List[Any]:
    """
    The combatant's spells that plainly deal damage, heal or buff, for the usual choices. Spells
    with an effect of their own (Sleep, Moonbeam, Hunter's Mark...) are chosen separately, and
    spells with no use in a fight (Prestidigitation, Revivify) never.
    """
    return [s for s in getattr(combatant, 'spells', {}).values()
            if getattr(s, 'combat', True) and not getattr(s, 'effect', None)]


def lowest_slot(combatant: Any, level: int) -> Optional[int]:
    """The lowest spell slot of at least this level the combatant has left."""
    slots = getattr(combatant, 'spell_slots_remaining', None)
    if not isinstance(slots, dict):
        return None
    return min((int(lvl) for lvl, count in slots.items() if int(lvl) >= level and count > 0), default=None)


def _save_fails(target: Any, save_type: str, dc: int) -> float:
    """Chance the target fails a save against a spell: with Magic Resistance it rolls twice."""
    bonus = target.saving_throw_bonus(save_type) if hasattr(target, 'saving_throw_bonus') else 0
    fail = 1 - min(0.95, max(0.05, (21 + bonus - dc) / 20))
    return fail * fail if has_magic_resistance(target) else fail


def _restrained(target: Any) -> bool:
    buffs = getattr(target, 'buffs', None)
    return hasattr(buffs, 'has_condition') and buffs.has_condition('restrained')


def _immune(target: Any, condition: str) -> bool:
    return condition in (getattr(target, 'condition_immunities', None) or [])


class Combatant(Protocol):
    """Protocol defining the interface for combatants in combat."""
    name: str
    hp: int
    max_hp: int
    level: int

    def is_alive(self) -> bool:
        """Check if combatant is alive."""
        ...


class CombatAction(Protocol):
    """Protocol defining the interface for combat actions."""
    name: str
    action_type: str

    def hit_bonus(self, combatant: Any) -> int:
        """Calculate hit bonus for this action."""
        ...


class AIStrategy(ABC):
    """
    Base class for AI tactical decision-making in combat.

    Provides abstract methods for action selection, target evaluation,
    threat assessment, and opportunity cost analysis.
    """

    def __init__(self):
        """Initialize the AI strategy with a random number generator."""
        self.rng = random.Random()
        logger.debug(f"Initialized {self.__class__.__name__}")

    @abstractmethod
    def choose_action(self, combatant: Any, combat_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decide which action the combatant should take given the combat state.

        Args:
            combatant: The combatant making the decision
            combat_state: Current state of combat including allies, enemies, round number

        Returns:
            Dictionary describing the chosen action with 'type' and relevant fields

        Raises:
            ValueError: If inputs are invalid
        """
        pass

    @abstractmethod
    def evaluate_targets(self, combatant: Any, potential_targets: List[Any], combat_state: Dict[str, Any]) -> List[Any]:
        """
        Evaluate and rank potential targets for the combatant.

        Args:
            combatant: The combatant evaluating targets
            potential_targets: List of potential targets
            combat_state: Current state of combat

        Returns:
            Sorted list of targets (highest priority first)

        Raises:
            ValueError: If inputs are invalid
        """
        pass

    def threat_assessment(self, combatant: Any, combat_state: Dict[str, Any]) -> float:
        """
        Assess the threat posed by or to the combatant in the current state.

        Default implementation based on level, HP, and abilities.
        Can be overridden by subclasses for specific behavior.

        Args:
            combatant: The combatant to assess
            combat_state: Current state of combat

        Returns:
            Threat score (higher = more threatening)
        """
        try:
            threat = float(getattr(combatant, 'level', 1))

            # Add HP contribution
            hp = getattr(combatant, 'hp', 1)
            threat += hp / 10.0

            # Bonus for special abilities
            if hasattr(combatant, 'special_abilities') and combatant.special_abilities:
                threat += SPECIAL_ABILITY_THREAT_BONUS

            # Bonus for class features
            if hasattr(combatant, 'class_features') and combatant.class_features:
                threat += CLASS_FEATURES_THREAT_BONUS

            return threat
        except Exception:
            if errors.RAISE_ERRORS:
                raise
            logger.exception(f"Error in threat_assessment for {getattr(combatant, 'name', 'Unknown')}")
            return 1.0  # Default low threat

    @abstractmethod
    def opportunity_cost_analysis(self, combatant: Any, action: Any, combat_state: Dict[str, Any]) -> float:
        """
        Analyze the opportunity cost of taking a given action.

        Args:
            combatant: The combatant considering the action
            action: The action being considered
            combat_state: Current state of combat

        Returns:
            Opportunity cost score (higher = higher cost)

        Raises:
            ValueError: If inputs are invalid
        """
        pass

    def _validate_combat_state(self, combat_state: Dict[str, Any]) -> None:
        """
        Validate that combat_state is valid (base implementation).

        Subclasses should override to add specific field requirements.

        Args:
            combat_state: Combat state to validate

        Raises:
            ValueError: If combat_state is invalid
        """
        if not isinstance(combat_state, dict):
            raise ValueError("combat_state must be a dictionary")

    def _validate_combatant(self, combatant: Any) -> None:
        """
        Validate that combatant has required attributes.

        Args:
            combatant: Combatant to validate

        Raises:
            ValueError: If combatant is invalid
        """
        if combatant is None:
            raise ValueError("combatant cannot be None")

        if not hasattr(combatant, 'name'):
            raise ValueError("combatant must have 'name' attribute")

        if not hasattr(combatant, 'is_alive'):
            raise ValueError("combatant must have 'is_alive' method")


class PartyAIStrategy(AIStrategy):
    """
    AI strategy for party members (heroes/PCs).

    Prioritizes protecting low-HP allies, healing, focus fire on dangerous enemies,
    and optimal spell usage based on encounter length and resources.
    """

    def _validate_combat_state(self, combat_state: Dict[str, Any]) -> None:
        """
        Validate combat_state for party AI (requires allies and enemies).

        Args:
            combat_state: Combat state to validate

        Raises:
            ValueError: If combat_state is invalid or missing required fields
        """
        super()._validate_combat_state(combat_state)

        if 'allies' not in combat_state:
            raise ValueError("combat_state must contain 'allies'")

        if 'enemies' not in combat_state:
            raise ValueError("combat_state must contain 'enemies'")

    def choose_action(self, combatant: Any, combat_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decide which action the party member should take.

        Priority order:
        1. Heal critical allies (below 15% HP)
        2. Heal low-HP allies (below 25% HP)
        3. Attack most dangerous enemy with best available action
        4. Default to defend/dodge

        Args:
            combatant: The party member making the decision
            combat_state: Current combat state with allies, enemies, round

        Returns:
            Action dictionary with type, action/spell, and target

        Raises:
            ValueError: If inputs are invalid
        """
        try:
            # Validate inputs
            self._validate_combatant(combatant)
            self._validate_combat_state(combat_state)

            logger.debug(f"[PartyAI] {combatant.name} choosing action")

            # Get alive allies and enemies
            allies = [c for c in combat_state['allies'] if c.is_alive()]
            enemies = [c for c in combat_state['enemies'] if c.is_alive()]

            # Priority 0: Cast buff spells early in combat (first 2 rounds), unless a spell with an
            # effect of its own is worth more (Hypnotic Pattern or Entangle before Bless)
            current_round = combat_state.get('round', 1)
            if current_round <= 2:
                effect_action = self._try_effect_spell(combatant, enemies, combat_state)
                if effect_action:
                    return effect_action
                buff_action = self._try_cast_buff_spell(combatant, allies, combat_state)
                if buff_action:
                    return buff_action

            # Priority 1: Heal critical allies (below 15% HP)
            critical_allies = [
                a for a in allies
                if hasattr(a, 'max_hp') and a.max_hp > 0 and (a.hp / a.max_hp) < CRITICAL_HP_THRESHOLD
            ]

            if critical_allies:
                healing_action = self._try_heal_ally(combatant, critical_allies, is_critical=True)
                if healing_action:
                    return healing_action

            # Priority 2: Heal low-HP allies (below 25% HP)
            low_hp_allies = [
                a for a in allies
                if hasattr(a, 'max_hp') and a.max_hp > 0 and (a.hp / a.max_hp) < LOW_HP_THRESHOLD
            ]

            if low_hp_allies:
                healing_action = self._try_heal_ally(combatant, low_hp_allies, is_critical=False)
                if healing_action:
                    return healing_action

            # Priority 2.5: Turn Undead (a cleric's Channel Divinity)
            turn_action = self._try_turn_undead(combatant, enemies, combat_state)
            if turn_action:
                return turn_action

            # Priority 2.6: Spells with an effect of their own (Sleep, Moonbeam, Hypnotic Pattern...)
            effect_action = self._try_effect_spell(combatant, enemies, combat_state)
            if effect_action:
                return effect_action

            # Priority 3: Finish off a downed enemy that would regenerate (burn the troll)
            finish_action = self._try_finish_regenerator(combatant, combat_state.get('downed_regenerators', []))
            if finish_action:
                return finish_action

            # Priority 4: Attack most dangerous enemy
            if enemies:
                attack_action = self._try_attack_enemy(combatant, enemies, combat_state)
                if attack_action:
                    return attack_action

            # Priority 5: Default to defend
            logger.debug(f"[PartyAI] {combatant.name} chooses to defend (no valid targets)")
            return {'type': 'defend'}

        except Exception:
            if errors.RAISE_ERRORS:
                raise
            logger.exception(f"Error in PartyAI choose_action for {getattr(combatant, 'name', 'Unknown')}")
            return {'type': 'defend'}

    def _try_heal_ally(self, combatant: Any, injured_allies: List[Any], is_critical: bool = False) -> Optional[Dict[str, Any]]:
        """
        Attempt to heal an injured ally.

        Args:
            combatant: The healer
            injured_allies: List of injured allies to consider
            is_critical: Whether this is critical healing (affects logging)

        Returns:
            Healing action dictionary, or None if no healing available
        """
        injured_allies = [a for a in injured_allies if not cannot_regain_hp(a)]  # mummy rot
        if not injured_allies:
            return None
        if feature_rules.resource(combatant, 'lay_on_hands') > 0:
            # A paladin heals with Lay on Hands first, keeping its slots for spells and smites
            target = min(injured_allies, key=lambda a: a.hp / a.max_hp if a.max_hp > 0 else a.hp)
            logger.debug(f"[PartyAI] {combatant.name} uses Lay on Hands on {target.name}")
            return {'type': 'cast_spell', 'spell': feature_rules.LayOnHandsAction(), 'target': target}

        healing_spells = [
            s for s in combat_spells(combatant)
            if hasattr(s, 'healing') and s.healing
            and (getattr(s, 'level', 0) == 0 or lowest_slot(combatant, getattr(s, 'level', 1)) is not None)
        ]

        if not healing_spells:
            return None

        # Several allies hurt: heal them all at once (Mass Cure Wounds)
        group = [s for s in healing_spells if getattr(s, 'max_targets', 1) > 1]
        if group and len(injured_allies) >= MASS_HEAL_MIN_ALLIES:
            spell = max(group, key=lambda s: s.level)
            targets = sorted(injured_allies, key=lambda a: a.hp / a.max_hp if a.max_hp > 0 else a.hp)[:spell.max_targets]
            logger.debug(f"[PartyAI] {combatant.name} heals {', '.join(t.name for t in targets)} with {spell.name}")
            return {'type': 'cast_spell', 'spell': SpellAction(spell, spell_slot_level=lowest_slot(combatant, spell.level)),
                    'target': targets}
        healing_spells = [s for s in healing_spells if getattr(s, 'max_targets', 1) == 1] or healing_spells

        # Pick the most injured ally
        target = min(
            injured_allies,
            key=lambda a: (a.hp / a.max_hp) if hasattr(a, 'max_hp') and a.max_hp > 0 else a.hp
        )

        # Select best healing spell based on target's missing HP
        missing_hp = target.max_hp - target.hp if hasattr(target, 'max_hp') else 0
        spell = self._select_best_healing_spell(healing_spells, missing_hp)

        spell_action = SpellAction(spell, spell_slot_level=lowest_slot(combatant, spell.level) if spell.level else None)

        priority = "CRITICAL" if is_critical else "LOW HP"
        logger.debug(f"[PartyAI] {combatant.name} heals {target.name} ({priority}) with {spell.name}")

        return {'type': 'cast_spell', 'spell': spell_action, 'target': target}

    def _select_best_healing_spell(self, healing_spells: List[Any], missing_hp: int) -> Any:
        """
        Select the most appropriate healing spell based on missing HP.

        Args:
            healing_spells: Available healing spells
            missing_hp: Amount of HP the target is missing

        Returns:
            Best healing spell
        """
        # If only one spell, use it
        if len(healing_spells) == 1:
            return healing_spells[0]

        # Sort by level (prefer lower level spells for efficiency)
        sorted_spells = sorted(healing_spells, key=lambda s: getattr(s, 'level', 0))

        # Use the lowest level spell that can heal most of the damage
        for spell in sorted_spells:
            # Estimate average healing (rough calculation)
            avg_healing = self._estimate_spell_healing(spell)
            if avg_healing >= missing_hp * 0.6:  # Can heal at least 60% of missing HP
                return spell

        # Default to highest level healing spell if nothing else fits
        return sorted_spells[-1]

    def _estimate_spell_healing(self, spell: Any) -> float:
        """
        Estimate average healing for a spell.

        Args:
            spell: Spell to estimate

        Returns:
            Estimated average healing amount
        """
        # Simple estimation: assume dice roll average + modifier
        healing_dice = getattr(spell, 'healing_dice', '1d8')

        try:
            # Parse dice notation (e.g., "2d8")
            if 'd' in healing_dice:
                num, die = healing_dice.split('d')
                num = int(num)
                die = int(die)
                avg = num * (die / 2 + 0.5)
                return avg
        except:
            pass

        return 8.0  # Default estimate

    def _try_cast_buff_spell(self, combatant: Any, allies: List[Any], combat_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Attempt to cast a buff spell on allies.

        Args:
            combatant: The caster
            allies: Available allies to buff
            combat_state: Current combat state

        Returns:
            Buff spell action dictionary, or None if no buff available
        """
        # Get all buff spells
        buff_spells = [
            s for s in combat_spells(combatant)
            if hasattr(s, 'is_buff_spell') and s.is_buff_spell
        ]

        if not buff_spells:
            return None

        # Filter to spells we have a slot for, of the spell's level or higher
        castable_buffs = [s for s in buff_spells if lowest_slot(combatant, getattr(s, 'level', 1)) is not None]

        if not castable_buffs:
            return None

        # For each castable buff, find allies who don't already have it
        for spell in castable_buffs:
            buff_name = spell.buff_data.get('name', spell.name) if hasattr(spell, 'buff_data') else spell.name
            is_concentration = spell.buff_data.get('concentration', False) if hasattr(spell, 'buff_data') else False

            # Don't drop another concentration spell (Moonbeam, Entangle) for a buff
            if getattr(spell, 'concentration', False) and concentration.concentrating_on(combatant):
                continue

            # If this is a concentration buff, check if caster is already concentrating on it
            if is_concentration:
                # Check if any ally (including caster) already has this concentration buff from this caster
                caster_name = getattr(combatant, 'name', str(combatant))
                already_concentrating = False

                for ally in allies:
                    if hasattr(ally, 'buffs'):
                        for active_buff in ally.buffs.active_buffs:
                            if (active_buff.name == buff_name and
                                active_buff.source == caster_name and
                                active_buff.concentration):
                                # Caster is already maintaining this concentration buff
                                logger.debug(f"[PartyAI] {combatant.name} already concentrating on {buff_name}, skipping")
                                already_concentrating = True
                                break
                    if already_concentrating:
                        break

                # Skip this spell if already concentrating on it
                if already_concentrating:
                    continue

            # Find allies without this buff
            unbuffed_allies = [
                a for a in allies
                if hasattr(a, 'buffs') and not a.buffs.has_buff(buff_name)
            ]

            if unbuffed_allies:
                # Get max_targets from spell (default to 1 for single-target buffs)
                max_targets = getattr(spell, 'max_targets', 1)

                # Select up to max_targets allies to buff, prioritizing highest HP
                targets_to_buff = sorted(
                    unbuffed_allies,
                    key=lambda a: getattr(a, 'max_hp', a.hp),
                    reverse=True
                )[:max_targets]

                # Use list of targets if multi-target, single target otherwise
                target = targets_to_buff if len(targets_to_buff) > 1 else targets_to_buff[0]

                spell_action = SpellAction(spell, spell_slot_level=lowest_slot(combatant, spell.level))

                # Log differently for multi-target spells
                if len(targets_to_buff) > 1:
                    target_names = ", ".join([t.name for t in targets_to_buff])
                    logger.debug(f"[PartyAI] {combatant.name} casts buff {spell.name} on {target_names}")
                else:
                    logger.debug(f"[PartyAI] {combatant.name} casts buff {spell.name} on {targets_to_buff[0].name}")

                return {'type': 'cast_spell', 'spell': spell_action, 'target': target}

        # No allies need buffs
        return None

    def _estimate_spell_damage(self, spell: Any) -> float:
        """
        Estimate average damage for a spell.

        Args:
            spell: Spell to estimate

        Returns:
            Estimated average damage amount
        """
        if callable(getattr(spell, 'average_damage', None)):
            average = spell.average_damage()  # every dart, ray or beam (see Spell.projectile_count)
            if average:
                return average
        damage_dice = getattr(spell, 'damage_dice', '1d6')

        try:
            # Parse dice notation (e.g., "8d6", "3d10")
            if 'd' in str(damage_dice):
                num, die = str(damage_dice).split('d')
                num = int(num)
                die = int(die)
                avg = num * (die / 2 + 0.5)
                return avg
        except:
            pass

        return 7.0  # Default estimate

    def _try_turn_undead(self, combatant: Any, enemies: List[Any], combat_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Turn Undead when it takes more than one enemy out of the fight: two or more undead within
        30 ft, or one while other enemies are left to fight, or any that Destroy Undead could
        destroy. A lone undead isn't worth it: turned, it flees, and someone has to hit it again.
        """
        if not feature_rules.can_turn_undead(combatant):
            return None
        undead = feature_rules.turnable(enemies)
        battlefield = combat_state.get('battlefield')
        if battlefield is not None:
            undead = [u for u in undead if battlefield.distance(combatant, u) <= feature_rules.TURN_UNDEAD_RANGE_FEET]
        if not undead:
            return None
        others = [e for e in enemies if e not in undead and not is_spellbound(e)]
        destroy_cr = feature_rules.destroy_undead_cr(combatant)
        destroyable = destroy_cr is not None and any(feature_rules.challenge_rating(u) <= destroy_cr for u in undead)
        if len(undead) >= 2 or others or destroyable:
            logger.debug(f"[PartyAI] {combatant.name} uses Turn Undead on {', '.join(u.name for u in undead)}")
            return {'type': 'turn_undead', 'target': undead}
        return None

    def _try_effect_spell(self, combatant: Any, enemies: List[Any], combat_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Use a spell with an effect of its own when it's worth the action and the slot:

        - keep a spell going: another Call Lightning bolt (no slot), or move a Moonbeam whose
          creature dropped onto another one
        - Hypnotic Pattern, Sleep, Entangle or Web when enough enemies would be affected
        - Moonbeam or Call Lightning against enemies with plenty of hit points left
        - Protection from Evil and Good when most enemies are undead, fiends and the like
        - Mirror Image once the caster has been hurt

        A caster already concentrating doesn't start another concentration spell. Bonus-action
        spells (Hunter's Mark, Spiritual Weapon) are Combat's choice (see _spell_bonus_action).
        """
        spells = {s.name: s for s in getattr(combatant, 'spells', {}).values()
                  if getattr(s, 'combat', True) and getattr(s, 'effect', None) and not getattr(s, 'bonus_action', False)}
        if not spells or not enemies:
            return None
        active = [e for e in enemies if not is_spellbound(e)]
        holding = concentration.concentrating_on(combatant)

        if holding == 'Call Lightning' and 'Call Lightning' in spells and active:
            return self._effect_plan(combatant, spells['Call Lightning'], active, free=True)
        if holding == 'Moonbeam' and 'Moonbeam' in spells and active:
            in_beam = [c for c in concentration.held_by(combatant) if c.is_alive()
                       and any('moonbeam' in b.metadata for b in getattr(getattr(c, 'buffs', None), 'active_buffs', []))]
            if not in_beam:
                return self._effect_plan(combatant, spells['Moonbeam'], max(active, key=lambda e: e.hp), free=True)

        def castable(name: str) -> bool:
            spell = spells.get(name)
            return spell is not None and lowest_slot(combatant, spell.level) is not None and \
                not (spell.concentration and holding)

        dc = combatant.spell_save_dc() if hasattr(combatant, 'spell_save_dc') else 10
        if castable('Hypnotic Pattern'):
            affected = sum(_save_fails(e, 'wis', dc) for e in active if not _immune(e, 'charmed'))
            if affected >= CONTROL_MIN_AFFECTED + 0.5:
                return self._effect_plan(combatant, spells['Hypnotic Pattern'], active)
        if castable('Sleep'):
            pool, slept = SLEEP_AVERAGE_POOL, 0
            for enemy in sorted(active, key=lambda e: e.hp):
                if getattr(enemy, 'creature_type', None) == 'undead' or _immune(enemy, 'charmed'):
                    continue
                if enemy.hp > pool:
                    break
                pool -= enemy.hp
                slept += 1
            if slept >= min(SLEEP_MIN_ENEMIES, len(active)) and slept:
                return self._effect_plan(combatant, spells['Sleep'], active)
        # A caster who can Fireball the crowd does that instead of webbing it
        blaster = any(s.area_effect and s.damage_dice and s.level > 0 and lowest_slot(combatant, s.level) is not None
                      for s in combat_spells(combatant))
        for name in ('Web', 'Entangle'):
            if castable(name) and len(active) >= 2 and not blaster:
                spell = spells[name]
                ranked = sorted((e for e in active if not _immune(e, 'restrained') and not _restrained(e)),
                                key=lambda e: -e.hp)
                affected = sum(_save_fails(e, spell.save_type, dc) for e in ranked[:getattr(spell, 'max_targets', 4)])
                if affected >= CONTROL_MIN_AFFECTED:
                    return self._effect_plan(combatant, spell, ranked)
        biggest = max(active, key=lambda e: e.hp, default=None)
        hold = spells.get('Hold Monster')
        if castable('Hold Monster') and biggest is not None and biggest.hp >= LASTING_SPELL_MIN_HP and \
                hold.affects(biggest) and not _immune(biggest, 'paralyzed') and \
                _save_fails(biggest, 'wis', dc) >= HOLD_MIN_FAIL_CHANCE:
            return self._effect_plan(combatant, hold, biggest)
        if castable('Moonbeam') and biggest is not None and biggest.hp >= LASTING_SPELL_MIN_HP:
            return self._effect_plan(combatant, spells['Moonbeam'], biggest)
        if castable('Call Lightning') and sum(e.hp for e in active) >= 2 * LASTING_SPELL_MIN_HP:
            return self._effect_plan(combatant, spells['Call Lightning'], active)
        warded = spells.get('Protection from Evil and Good')
        if castable('Protection from Evil and Good') and not combatant.buffs.has_buff(warded.buff_data.get('name', warded.name)):
            kinds = set(warded.buff_data.get('metadata', {}).get('protection_from', []))
            if sum(getattr(e, 'creature_type', None) in kinds for e in active) * 2 > len(active):
                return self._effect_plan(combatant, warded, combatant)
        if castable('Mirror Image') and not combatant.buffs.has_buff('Mirror Image') and \
                combatant.hp < combatant.max_hp * MIRROR_IMAGE_HP:
            return self._effect_plan(combatant, spells['Mirror Image'], combatant)
        return None

    @staticmethod
    def _effect_plan(combatant: Any, spell: Any, target: Any, free: bool = False) -> Dict[str, Any]:
        """
        Cast it (free: keep using it). Without an arena an area spell catches the first
        max_targets enemies offered, or all of them if it doesn't say (an arena aims it instead).
        """
        if not spell.area_effect:
            target = target[0] if isinstance(target, list) else target
        elif spell.max_targets > 1:
            target = target[:spell.max_targets]
        slot = spell_effects.held_slot(combatant, spell.name) if free else lowest_slot(combatant, spell.level)
        action = SpellAction(spell, spell_slot_level=slot, free=free)
        names = target.name if not isinstance(target, list) else ', '.join(t.name for t in target)
        logger.debug(f"[PartyAI] {combatant.name} {'uses' if free else 'casts'} {spell.name} on {names}")
        return {'type': 'cast_spell', 'spell': action, 'target': target}

    def _try_finish_regenerator(self, combatant: Any, downed: List[Any]) -> Optional[Dict[str, Any]]:
        """
        Hit a downed regenerating enemy with a damage type that stops its regeneration (fire or
        acid for a troll), so it dies instead of getting back up. Uses cantrips and weapons only,
        never spell slots.
        """
        for creature in downed:
            stops = {t.lower() for t in creature.regeneration.get('suppressed_by', [])}
            cantrips = [
                s for s in combat_spells(combatant)
                if getattr(s, 'level', None) == 0 and getattr(s, 'damage_dice', None)
                and not getattr(s, 'healing', False) and (getattr(s, 'damage_type', None) or '').lower() in stops
            ]
            if cantrips:
                cantrip = max(cantrips, key=self._estimate_spell_damage)
                logger.debug(f"[PartyAI] {combatant.name} casts {cantrip.name} to finish the downed {creature.name}")
                return {'type': 'cast_spell', 'spell': SpellAction(cantrip), 'target': creature}
            weapons = [
                a for a in getattr(combatant, 'actions', [])
                if getattr(a, 'action_type', None) == 'attack' and not getattr(a, 'area_effect', False)
                and (getattr(a, 'damage_type', None) or '').lower() in stops
            ]
            if weapons:
                weapon = max(weapons, key=lambda a: (a.hit_bonus(combatant), self._average_damage(a)))
                logger.debug(f"[PartyAI] {combatant.name} attacks the downed {creature.name} with {weapon.name}")
                return {'type': 'attack', 'action': weapon, 'target': creature}
        return None

    @staticmethod
    def _average_damage(action: Any) -> float:
        """Average damage of a weapon action's dice, used to break ties between equally accurate weapons."""
        try:
            num, die, mod = AttackAction.parse_dice(action.damage_dice)
            return num * (die + 1) / 2 + mod
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def _try_attack_enemy(self, combatant: Any, enemies: List[Any], combat_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Attempt to attack an enemy.

        Args:
            combatant: The attacker
            enemies: Available enemies
            combat_state: Current combat state

        Returns:
            Attack action dictionary, or None if no attack available
        """
        # Select most dangerous enemy, leaving turned, sleeping and hypnotized enemies alone while
        # there are others (damage would wake them)
        enemies = [e for e in enemies if not is_spellbound(e)] or enemies
        dangerous = max(enemies, key=lambda e: self.threat_assessment(e, combat_state))

        # Check if combatant is a spellcaster
        character_class = getattr(combatant, 'character_class', None)
        is_spellcaster = character_class in SPELLCASTER_CLASSES if character_class else False
        is_offensive_caster = character_class in OFFENSIVE_CASTER_CLASSES if character_class else False
        current_round = combat_state.get('round', 1)

        # Check if this is a pure offensive caster (has no healing spells)
        has_healing_spells = False
        if is_offensive_caster:
            all_spells = combat_spells(combatant)
            has_healing_spells = any(hasattr(s, 'healing') and s.healing for s in all_spells)

        # OFFENSIVE CASTER AGGRESSIVE STRATEGY
        # Pure offensive casters (wizards without healing) should prioritize damage spells in early rounds
        if is_offensive_caster and not has_healing_spells and current_round <= AGGRESSIVE_SPELL_ROUNDS:
            damaging_spells = [
                s for s in combat_spells(combatant)
                if hasattr(s, 'damage_dice') and s.damage_dice and getattr(s, 'level', 0) > 0
            ]

            # Filter to spells we have a slot for (the spell's level or higher), leaving out single-target
            # spells that would do nothing to the target (Blight on undead)
            castable_spells = [s for s in damaging_spells
                               if lowest_slot(combatant, getattr(s, 'level', 1)) is not None
                               and (getattr(s, 'area_effect', False) or not callable(getattr(s, 'affects', None))
                                    or s.affects(dangerous))]

            if castable_spells:
                # Prioritize higher level spells for maximum damage
                # Sort by level (descending), then by estimated damage
                best_spell = max(castable_spells, key=lambda s: (
                    getattr(s, 'level', 0),
                    self._estimate_spell_damage(s)
                ))

                spell_action = SpellAction(best_spell, spell_slot_level=lowest_slot(combatant, best_spell.level))

                # Check if this is an area effect spell
                if getattr(best_spell, 'area_effect', False):
                    # Target all enemies with area effect spells
                    target = enemies
                    target_names = ", ".join([e.name for e in enemies])
                    logger.debug(f"[PartyAI] {combatant.name} aggressively casts AoE {best_spell.name} (lvl {best_spell.level}) targeting {target_names}")
                else:
                    # Single target spell
                    target = dangerous
                    logger.debug(f"[PartyAI] {combatant.name} aggressively casts {best_spell.name} (lvl {best_spell.level}) vs {dangerous.name}")

                return {'type': 'cast_spell', 'spell': spell_action, 'target': target}

        # STANDARD SPELLCASTER STRATEGY
        # Spellcasters prefer cantrips (resource conservation)
        if is_spellcaster:
            cantrips = [
                s for s in combat_spells(combatant)
                if getattr(s, 'level', None) == 0 and getattr(s, 'damage_dice', None)
                and not getattr(s, 'healing', False)
            ]
            if cantrips:
                cantrip = max(cantrips, key=self._estimate_spell_damage)
                logger.debug(f"[PartyAI] {combatant.name} casts {cantrip.name} vs {dangerous.name}")
                return {'type': 'cast_spell', 'spell': SpellAction(cantrip), 'target': dangerous}

            spell_attacks = [
                a for a in getattr(combatant, 'actions', [])
                if hasattr(a, 'name') and a.name in DAMAGING_CANTRIPS
            ]

            if spell_attacks:
                best_spell = max(spell_attacks, key=lambda a: a.hit_bonus(combatant))
                logger.debug(f"[PartyAI] {combatant.name} uses {best_spell.name} vs {dangerous.name}")
                return {'type': 'attack', 'action': best_spell, 'target': dangerous}

        # Try attack actions
        attack_actions = [
            a for a in getattr(combatant, 'actions', [])
            if hasattr(a, 'action_type') and a.action_type == 'attack'
        ]

        if attack_actions:
            best_action = max(attack_actions, key=lambda a: (a.hit_bonus(combatant), self._average_damage(a)))
            best_bonus = best_action.hit_bonus(combatant)
            logger.debug(f"[PartyAI] {combatant.name} attacks with {best_action.name} (+{best_bonus}) vs {dangerous.name}")
            return {'type': 'attack', 'action': best_action, 'target': dangerous}

        # Try damaging spells as last resort
        damaging_spells = [
            s for s in combat_spells(combatant)
            if hasattr(s, 'damage_dice') and s.damage_dice
        ]

        if damaging_spells:
            # Prefer cantrips (level 0) to conserve spell slots
            cantrips = [s for s in damaging_spells if getattr(s, 'level', 1) == 0]
            spell = cantrips[0] if cantrips else damaging_spells[0]

            spell_action = SpellAction(spell, spell_slot_level=lowest_slot(combatant, spell.level) if spell.level else None)

            # Check if this is an area effect spell
            if getattr(spell, 'area_effect', False):
                # Target all enemies with area effect spells
                target = enemies
                target_names = ", ".join([e.name for e in enemies])
                logger.debug(f"[PartyAI] {combatant.name} casts AoE {spell.name} targeting {target_names}")
            else:
                # Single target spell
                target = dangerous
                logger.debug(f"[PartyAI] {combatant.name} casts {spell.name} vs {dangerous.name}")

            return {'type': 'cast_spell', 'spell': spell_action, 'target': target}

        return None

    def evaluate_targets(self, combatant: Any, potential_targets: List[Any], combat_state: Dict[str, Any]) -> List[Any]:
        """
        Rank targets by threat and vulnerability.

        Args:
            combatant: The combatant evaluating targets
            potential_targets: List of potential targets
            combat_state: Current combat state

        Returns:
            Sorted list of targets (most threatening first)

        Raises:
            ValueError: If inputs are invalid
        """
        self._validate_combatant(combatant)
        self._validate_combat_state(combat_state)

        if not potential_targets:
            return []

        return sorted(
            potential_targets,
            key=lambda t: self.threat_assessment(t, combat_state),
            reverse=True
        )

    def opportunity_cost_analysis(self, combatant: Any, action: Any, combat_state: Dict[str, Any]) -> float:
        """
        Estimate opportunity cost for spell slot usage vs. encounter length.

        Args:
            combatant: The combatant considering the action
            action: The action being considered
            combat_state: Current combat state

        Returns:
            Opportunity cost (higher = should avoid using this action)

        Raises:
            ValueError: If inputs are invalid
        """
        self._validate_combatant(combatant)
        # Note: combat_state validation not needed - only uses 'encounters_remaining'

        # High cost for leveled spells when many encounters remain
        if hasattr(action, 'level') and action.level > 0:
            encounters_remaining = combat_state.get('encounters_remaining', 1)
            if encounters_remaining > MANY_ENCOUNTERS_THRESHOLD:
                return HIGH_OPPORTUNITY_COST

        return DEFAULT_OPPORTUNITY_COST


class MonsterAIStrategy(AIStrategy):
    """
    AI strategy for monsters.

    Uses varied targeting strategies to create interesting combat:
    - Spreads damage across party members
    - Focuses fire on high-threat targets
    - Finishes off weakened enemies
    - Occasional random targeting for unpredictability
    """

    def _validate_combat_state(self, combat_state: Dict[str, Any]) -> None:
        """
        Validate combat_state for monster AI (only requires enemies).

        Args:
            combat_state: Combat state to validate

        Raises:
            ValueError: If combat_state is invalid or missing required fields
        """
        super()._validate_combat_state(combat_state)

        if 'enemies' not in combat_state:
            raise ValueError("combat_state must contain 'enemies'")

    def choose_action(self, combatant: Any, combat_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decide which action the monster should take.

        Uses deterministic pseudo-randomness based on monster name and round
        to vary targeting strategy while maintaining reproducibility.

        Args:
            combatant: The monster making the decision
            combat_state: Current combat state

        Returns:
            Action dictionary with type, action, and target

        Raises:
            ValueError: If inputs are invalid
        """
        try:
            # Validate inputs
            self._validate_combatant(combatant)
            self._validate_combat_state(combat_state)

            logger.debug(f"[MonsterAI] {combatant.name} choosing action")

            enemies = [c for c in combat_state['enemies'] if c.is_alive()]

            if not enemies:
                logger.debug(f"[MonsterAI] {combatant.name} waits (no valid targets)")
                return {'type': 'wait'}

            # Priority 1: an area attack that's ready (a breath weapon that has recharged). It hits
            # every enemy without an arena; on one, fit_plan aims it, or keeps it for later if an
            # ordinary attack would do more
            area_attacks = [
                a for a in getattr(combatant, 'actions', [])
                if getattr(a, 'action_type', None) == 'attack' and getattr(a, 'area_effect', False)
                and getattr(a, 'ready', True)
            ]
            if area_attacks:
                logger.debug(f"[MonsterAI] {combatant.name} uses {area_attacks[0].name}")
                return {'type': 'attack', 'action': area_attacks[0], 'target': enemies}

            # Use special abilities if available
            specials = [
                a for a in getattr(combatant, 'actions', [])
                if hasattr(a, 'action_type') and a.action_type == 'special'
            ]

            if specials and self._should_use_special_ability(combatant, enemies, combat_state):
                special_action = specials[0]
                # Check if this is an area effect ability
                if getattr(special_action, 'area_effect', False):
                    target = enemies
                    target_names = ", ".join([e.name for e in enemies])
                    logger.debug(f"[MonsterAI] {combatant.name} uses AoE special ability: {special_action.name} targeting {target_names}")
                else:
                    target = self.evaluate_targets(combatant, enemies, combat_state)[0]
                    logger.debug(f"[MonsterAI] {combatant.name} uses special ability: {special_action.name} vs {target.name}")
                return {'type': 'special', 'action': special_action, 'target': target}

            # Priority 2: Select target using varied strategy
            target = self._select_target_with_strategy(combatant, enemies, combat_state)

            # Priority 3: Execute attack
            attack_actions = [
                a for a in getattr(combatant, 'actions', [])
                if hasattr(a, 'action_type') and a.action_type == 'attack'
            ]

            if attack_actions:
                attack_action = attack_actions[0]
                # Check if this is an area effect attack
                if getattr(attack_action, 'area_effect', False):
                    target = enemies
                    target_names = ", ".join([e.name for e in enemies])
                    logger.debug(f"[MonsterAI] {combatant.name} uses AoE attack: {attack_action.name} targeting {target_names}")
                else:
                    logger.debug(f"[MonsterAI] {combatant.name} attacks {target.name}")
                return {'type': 'attack', 'action': attack_action, 'target': target}

            # Default: wait if no attack actions
            logger.debug(f"[MonsterAI] {combatant.name} waits (no attack actions)")
            return {'type': 'wait'}

        except Exception:
            if errors.RAISE_ERRORS:
                raise
            logger.exception(f"Error in MonsterAI choose_action for {getattr(combatant, 'name', 'Unknown')}")
            return {'type': 'wait'}

    def _should_use_special_ability(self, combatant: Any, enemies: List[Any], combat_state: Dict[str, Any]) -> bool:
        """
        Determine if monster should use special ability.

        Monsters prefer to use special abilities when available as they
        typically deal more damage or have additional effects.

        Args:
            combatant: The monster
            enemies: Available enemies
            combat_state: Current combat state

        Returns:
            True if should use special ability
        """
        # Monsters use special abilities when available
        # This creates more interesting and challenging combat
        return True

    def _select_target_with_strategy(self, combatant: Any, enemies: List[Any], combat_state: Dict[str, Any]) -> Any:
        """
        Select target using varied strategy.

        Uses deterministic pseudo-randomness based on monster name and round
        to create varied but reproducible targeting behavior.

        Args:
            combatant: The monster selecting a target
            enemies: Available enemies
            combat_state: Current combat state

        Returns:
            Selected target
        """
        if len(enemies) == 1:
            return enemies[0]

        # Create deterministic seed from monster name and round
        monster_name = getattr(combatant, 'name', 'Unknown')
        round_num = combat_state.get('round', 1)
        seed = sum(ord(c) for c in monster_name) + round_num * 13

        # Use instance RNG with deterministic seed
        self.rng.seed(seed)
        strategy_roll = self.rng.random()

        # Select targeting strategy based on roll
        if strategy_roll < SPREAD_DAMAGE_PROBABILITY:
            # Spread damage: target least damaged enemy
            target = min(
                enemies,
                key=lambda e: (e.hp / e.max_hp) if hasattr(e, 'max_hp') and e.max_hp > 0 else e.hp
            )
            logger.debug(f"[MonsterAI] {combatant.name} spreads damage to {target.name}")

        elif strategy_roll < SPREAD_DAMAGE_PROBABILITY + FOCUS_FIRE_PROBABILITY:
            # Focus fire: target most threatening enemy
            target = max(enemies, key=lambda e: self.threat_assessment(e, combat_state))
            logger.debug(f"[MonsterAI] {combatant.name} focuses fire on {target.name}")

        elif strategy_roll < SPREAD_DAMAGE_PROBABILITY + FOCUS_FIRE_PROBABILITY + FINISH_WEAK_PROBABILITY:
            # Finish weak targets: target lowest HP enemy
            target = min(enemies, key=lambda e: e.hp)
            logger.debug(f"[MonsterAI] {combatant.name} finishes weak target {target.name}")

        else:
            # Random targeting for unpredictability
            target = self.rng.choice(enemies)
            logger.debug(f"[MonsterAI] {combatant.name} randomly targets {target.name}")

        # Reset seed to avoid affecting other random operations
        self.rng.seed()

        return target

    def evaluate_targets(self, combatant: Any, potential_targets: List[Any], combat_state: Dict[str, Any]) -> List[Any]:
        """
        Rank targets by threat level (descending).

        Args:
            combatant: The monster evaluating targets
            potential_targets: List of potential targets
            combat_state: Current combat state

        Returns:
            Sorted list of targets (most threatening first)

        Raises:
            ValueError: If inputs are invalid
        """
        self._validate_combatant(combatant)
        self._validate_combat_state(combat_state)

        if not potential_targets:
            return []

        return sorted(
            potential_targets,
            key=lambda t: self.threat_assessment(t, combat_state),
            reverse=True
        )

    def opportunity_cost_analysis(self, combatant: Any, action: Any, combat_state: Dict[str, Any]) -> float:
        """
        Estimate opportunity cost for monsters (e.g., recharge abilities).

        Args:
            combatant: The monster considering the action
            action: The action being considered
            combat_state: Current combat state

        Returns:
            Opportunity cost (lower = prefer this action)

        Raises:
            ValueError: If inputs are invalid
        """
        self._validate_combatant(combatant)
        # Note: combat_state validation not needed - doesn't use combat_state fields

        # Lower cost for special abilities when available
        if getattr(action, 'action_type', '') == 'special':
            return LOW_OPPORTUNITY_COST

        return DEFAULT_OPPORTUNITY_COST
