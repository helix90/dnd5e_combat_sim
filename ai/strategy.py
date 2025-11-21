from abc import ABC, abstractmethod
from typing import Any, List, Dict, Protocol, Callable, Optional
import logging
import random
from models.spells import SpellAction

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

# Common damaging cantrips
DAMAGING_CANTRIPS = {'Fire Bolt', 'Sacred Flame', 'Eldritch Blast', 'Ray of Frost', 'Produce Flame'}

logger = logging.getLogger(__name__)


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
        except Exception as e:
            logger.warning(f"Error in threat_assessment for {getattr(combatant, 'name', 'Unknown')}: {e}")
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

            # Priority 3: Attack most dangerous enemy
            if enemies:
                attack_action = self._try_attack_enemy(combatant, enemies, combat_state)
                if attack_action:
                    return attack_action

            # Priority 4: Default to defend
            logger.debug(f"[PartyAI] {combatant.name} chooses to defend (no valid targets)")
            return {'type': 'defend'}

        except Exception as e:
            logger.error(f"Error in PartyAI choose_action for {getattr(combatant, 'name', 'Unknown')}: {e}")
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
        healing_spells = [
            s for s in getattr(combatant, 'spells', {}).values()
            if hasattr(s, 'healing') and s.healing
        ]

        if not healing_spells:
            return None

        # Pick the most injured ally
        target = min(
            injured_allies,
            key=lambda a: (a.hp / a.max_hp) if hasattr(a, 'max_hp') and a.max_hp > 0 else a.hp
        )

        # Select best healing spell based on target's missing HP
        missing_hp = target.max_hp - target.hp if hasattr(target, 'max_hp') else 0
        spell = self._select_best_healing_spell(healing_spells, missing_hp)

        spell_action = SpellAction(spell)

        priority = "CRITICAL" if is_critical else "LOW HP"
        logger.info(f"[PartyAI] {combatant.name} heals {target.name} ({priority}) with {spell.name}")

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
        # Select most dangerous enemy
        dangerous = max(enemies, key=lambda e: self.threat_assessment(e, combat_state))

        # Check if combatant is a spellcaster
        character_class = getattr(combatant, 'character_class', None)
        is_spellcaster = character_class in SPELLCASTER_CLASSES if character_class else False

        # Spellcasters prefer cantrips
        if is_spellcaster:
            spell_attacks = [
                a for a in getattr(combatant, 'actions', [])
                if hasattr(a, 'name') and a.name in DAMAGING_CANTRIPS
            ]

            if spell_attacks:
                best_spell = max(spell_attacks, key=lambda a: a.hit_bonus(combatant))
                logger.info(f"[PartyAI] {combatant.name} uses {best_spell.name} vs {dangerous.name}")
                return {'type': 'attack', 'action': best_spell, 'target': dangerous}

        # Try attack actions
        attack_actions = [
            a for a in getattr(combatant, 'actions', [])
            if hasattr(a, 'action_type') and a.action_type == 'attack'
        ]

        if attack_actions:
            best_action = max(attack_actions, key=lambda a: a.hit_bonus(combatant))
            best_bonus = best_action.hit_bonus(combatant)
            logger.info(f"[PartyAI] {combatant.name} attacks with {best_action.name} (+{best_bonus}) vs {dangerous.name}")
            return {'type': 'attack', 'action': best_action, 'target': dangerous}

        # Try damaging spells as last resort
        damaging_spells = [
            s for s in getattr(combatant, 'spells', {}).values()
            if hasattr(s, 'damage_dice') and s.damage_dice
        ]

        if damaging_spells:
            # Prefer cantrips (level 0) to conserve spell slots
            cantrips = [s for s in damaging_spells if getattr(s, 'level', 1) == 0]
            spell = cantrips[0] if cantrips else damaging_spells[0]

            spell_action = SpellAction(spell)
            logger.info(f"[PartyAI] {combatant.name} casts {spell.name} vs {dangerous.name}")
            return {'type': 'cast_spell', 'spell': spell_action, 'target': dangerous}

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

            # Priority 1: Use special abilities if available
            specials = [
                a for a in getattr(combatant, 'actions', [])
                if hasattr(a, 'action_type') and a.action_type == 'special'
            ]

            if specials and self._should_use_special_ability(combatant, enemies, combat_state):
                target = self.evaluate_targets(combatant, enemies, combat_state)[0]
                logger.info(f"[MonsterAI] {combatant.name} uses special ability: {specials[0].name} vs {target.name}")
                return {'type': 'special', 'action': specials[0], 'target': target}

            # Priority 2: Select target using varied strategy
            target = self._select_target_with_strategy(combatant, enemies, combat_state)

            # Priority 3: Execute attack
            attack_actions = [
                a for a in getattr(combatant, 'actions', [])
                if hasattr(a, 'action_type') and a.action_type == 'attack'
            ]

            if attack_actions:
                logger.info(f"[MonsterAI] {combatant.name} attacks {target.name}")
                return {'type': 'attack', 'action': attack_actions[0], 'target': target}

            # Default: wait if no attack actions
            logger.debug(f"[MonsterAI] {combatant.name} waits (no attack actions)")
            return {'type': 'wait'}

        except Exception as e:
            logger.error(f"Error in MonsterAI choose_action for {getattr(combatant, 'name', 'Unknown')}: {e}")
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
