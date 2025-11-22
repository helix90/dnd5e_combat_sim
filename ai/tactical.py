from typing import Any, List, Dict, Protocol, Optional
import logging

# Constants for threat calculation
HP_CONTRIBUTION_FACTOR = 0.1  # HP contribution to threat (hp / 10)
SPECIAL_ABILITY_THREAT_BONUS = 2.0  # Threat bonus for special abilities
CLASS_FEATURES_THREAT_BONUS = 1.0  # Threat bonus for class features
DEFAULT_THREAT_LEVEL = 1.0  # Default threat when calculation fails

# Constants for resource management
LOW_SPELL_SLOTS_THRESHOLD = 0  # All slots at this level or below = low slots

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


class TacticalAnalyzer:
    """
    Provides tactical analysis utilities for AI strategies.

    Offers methods for threat assessment, target prioritization,
    advantage evaluation, and resource management to support
    AI decision-making in combat scenarios.
    """

    def __init__(self):
        """Initialize the tactical analyzer."""
        logger.debug("Initialized TacticalAnalyzer")

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

    def _validate_combat_state(self, combat_state: Any) -> None:
        """
        Validate that combat_state is valid.

        Args:
            combat_state: Combat state to validate

        Raises:
            ValueError: If combat_state is invalid
        """
        if combat_state is None:
            raise ValueError("combat_state cannot be None")

        if not isinstance(combat_state, dict):
            raise ValueError("combat_state must be a dictionary")

    def _validate_targets(self, potential_targets: List[Any]) -> None:
        """
        Validate that potential_targets is a valid list.

        Args:
            potential_targets: List of targets to validate

        Raises:
            ValueError: If potential_targets is invalid
        """
        if potential_targets is None:
            raise ValueError("potential_targets cannot be None")

        if not isinstance(potential_targets, list):
            raise ValueError("potential_targets must be a list")

    def calculate_threat_level(self, combatant: Any, combat_state: Dict[str, Any]) -> float:
        """
        Calculate the threat level of a combatant based on stats and context.

        Threat level is calculated based on:
        - Base level of the combatant
        - Current HP (contributes HP / 10)
        - Special abilities (+2 threat)
        - Class features (+1 threat)

        Args:
            combatant: The combatant to assess
            combat_state: Current state of combat

        Returns:
            Threat level score (higher = more threatening)

        Raises:
            ValueError: If inputs are invalid
        """
        try:
            # Validate inputs
            self._validate_combatant(combatant)
            self._validate_combat_state(combat_state)

            logger.debug(f"Calculating threat level for {combatant.name}")

            # Base threat from level
            threat = float(getattr(combatant, 'level', 1))

            # Add HP contribution
            hp = getattr(combatant, 'hp', 1)
            threat += hp * HP_CONTRIBUTION_FACTOR

            # Bonus for special abilities
            if hasattr(combatant, 'special_abilities') and combatant.special_abilities:
                threat += SPECIAL_ABILITY_THREAT_BONUS
                logger.debug(f"{combatant.name} has special abilities (+{SPECIAL_ABILITY_THREAT_BONUS} threat)")

            # Bonus for class features
            if hasattr(combatant, 'class_features') and combatant.class_features:
                threat += CLASS_FEATURES_THREAT_BONUS
                logger.debug(f"{combatant.name} has class features (+{CLASS_FEATURES_THREAT_BONUS} threat)")

            logger.debug(f"Threat level for {combatant.name}: {threat}")
            return threat

        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.warning(f"Error calculating threat level for {getattr(combatant, 'name', 'Unknown')}: {e}")
            return DEFAULT_THREAT_LEVEL

    def find_optimal_targets(
        self,
        combatant: Any,
        potential_targets: List[Any],
        combat_state: Dict[str, Any]
    ) -> List[Any]:
        """
        Find and rank optimal targets considering threat and positioning.

        Targets are ranked by threat level in descending order (most
        threatening first). This helps AI prioritize dangerous enemies.

        Args:
            combatant: The combatant evaluating targets (can be None for general ranking)
            potential_targets: List of potential targets to evaluate
            combat_state: Current state of combat

        Returns:
            Sorted list of targets (highest threat first)

        Raises:
            ValueError: If inputs are invalid
        """
        try:
            # Validate inputs (combatant can be None since it's not used in current implementation)
            self._validate_targets(potential_targets)
            self._validate_combat_state(combat_state)

            combatant_name = getattr(combatant, 'name', 'Unknown') if combatant else 'Unknown'
            logger.debug(f"{combatant_name} evaluating {len(potential_targets)} potential targets")

            # Return empty list if no targets
            if not potential_targets:
                logger.debug(f"No targets available for {combatant_name}")
                return []

            # Sort by threat level (highest first)
            sorted_targets = sorted(
                potential_targets,
                key=lambda t: self.calculate_threat_level(t, combat_state),
                reverse=True
            )

            if sorted_targets:
                top_target = sorted_targets[0]
                top_threat = self.calculate_threat_level(top_target, combat_state)
                logger.info(
                    f"{combatant_name} identified optimal target: {top_target.name} "
                    f"(threat: {top_threat:.1f})"
                )

            return sorted_targets

        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Error finding optimal targets for {getattr(combatant, 'name', 'Unknown')}: {e}")
            # Return unsorted list as fallback
            return potential_targets if isinstance(potential_targets, list) else []

    def evaluate_advantage_opportunities(
        self,
        combatant: Any,
        combat_state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Evaluate opportunities for advantage (e.g., flanking, prone, etc.).

        Note: Advanced positioning mechanics (flanking, cover, etc.) are not
        currently implemented. This method is reserved for future enhancement.

        Args:
            combatant: The combatant to evaluate opportunities for
            combat_state: Current state of combat

        Returns:
            List of advantage opportunities (currently always empty)

        Raises:
            ValueError: If inputs are invalid
        """
        try:
            # Validate inputs
            self._validate_combatant(combatant)
            self._validate_combat_state(combat_state)

            logger.debug(f"Evaluating advantage opportunities for {combatant.name}")

            # Placeholder: Advanced positioning not yet implemented
            # Future implementation could check for:
            # - Flanking positions
            # - Prone enemies
            # - Restrained/stunned enemies
            # - Cover positions
            # - High ground advantage

            logger.debug(f"No advantage opportunities found (positioning not implemented)")
            return []

        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.warning(f"Error evaluating advantage for {getattr(combatant, 'name', 'Unknown')}: {e}")
            return []

    def resource_management(
        self,
        combatant: Any,
        combat_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Evaluate and suggest resource usage (spell slots, abilities).

        Analyzes the combatant's remaining resources and provides
        recommendations for resource conservation or usage.

        Args:
            combatant: The combatant to evaluate resources for
            combat_state: Current state of combat

        Returns:
            Dictionary with resource management recommendations:
            - 'low_slots': True if spell slots are depleted
            - 'encounters_remaining': Number of encounters left (if available)
            - 'recommend_conserve': True if should conserve resources

        Raises:
            ValueError: If inputs are invalid
        """
        try:
            # Validate inputs
            self._validate_combatant(combatant)
            self._validate_combat_state(combat_state)

            logger.debug(f"Analyzing resource management for {combatant.name}")

            resources = {}

            # Check spell slot availability
            if hasattr(combatant, 'spell_slots_remaining'):
                slots = getattr(combatant, 'spell_slots_remaining')

                if isinstance(slots, dict):
                    # Check if all slots are at or below threshold
                    low_slots = all(
                        v <= LOW_SPELL_SLOTS_THRESHOLD
                        for v in slots.values()
                    )
                    resources['low_slots'] = low_slots

                    # Count total remaining slots
                    total_slots = sum(slots.values())
                    resources['total_slots_remaining'] = total_slots

                    if low_slots:
                        logger.info(f"{combatant.name} has low/no spell slots remaining")
                    else:
                        logger.debug(f"{combatant.name} has {total_slots} spell slots remaining")
                else:
                    logger.warning(f"{combatant.name} has spell_slots_remaining but it's not a dict")
                    resources['low_slots'] = False

            # Check encounters remaining for conservation recommendations
            if 'encounters_remaining' in combat_state:
                encounters_remaining = combat_state['encounters_remaining']
                resources['encounters_remaining'] = encounters_remaining

                # Recommend conservation if multiple encounters remain
                resources['recommend_conserve'] = encounters_remaining > 2

                if resources.get('recommend_conserve'):
                    logger.info(
                        f"{combatant.name} should conserve resources "
                        f"({encounters_remaining} encounters remaining)"
                    )

            logger.debug(f"Resource analysis for {combatant.name}: {resources}")
            return resources

        except ValueError:
            # Re-raise validation errors
            raise
        except Exception as e:
            logger.error(f"Error in resource management for {getattr(combatant, 'name', 'Unknown')}: {e}")
            # Return safe defaults
            return {'low_slots': False, 'recommend_conserve': False}
