from models.encounter_builder import EncounterBuilder
from flask import session
import json
import copy
import logging
from typing import Dict, List, Any, Optional
from utils.exceptions import ValidationError, APIError
from utils.logging import log_exception

# Constants
BALANCED_ENCOUNTER_MESSAGE = "Encounter is balanced."
MAX_MONSTERS_PER_ENCOUNTER = 50
MIN_PARTY_LEVEL = 1
MAX_PARTY_LEVEL = 20
MIN_PARTY_SIZE = 1
MAX_PARTY_SIZE = 10

logger = logging.getLogger(__name__)


class EncounterController:
    """
    Controller for managing encounter creation and validation.
    Handles both custom and prebuilt encounters with session management.
    """

    def __init__(self, monsters_file: str = "data/monsters.json", templates_file: str = "data/encounter_templates.json"):
        """
        Initialize the encounter controller.

        Args:
            monsters_file: Path to the monsters data file
            templates_file: Path to the encounter templates file
        """
        self.builder = EncounterBuilder(monsters_file=monsters_file)
        self.templates_file = templates_file
        self.templates = []
        self._load_templates()

    def _load_templates(self) -> None:
        """
        Load and cache encounter templates from file.
        Called during initialization to avoid repeated file I/O.
        """
        try:
            with open(self.templates_file) as f:
                data = json.load(f)
                self.templates = data.get("encounters", [])
            logger.info(f"Loaded {len(self.templates)} encounter templates from {self.templates_file}")
        except FileNotFoundError as e:
            log_exception(e)
            logger.warning(f"Encounter templates file not found: {self.templates_file}")
            self.templates = []
        except json.JSONDecodeError as e:
            log_exception(e)
            logger.error(f"Invalid JSON in encounter templates file: {self.templates_file}")
            self.templates = []
        except Exception as e:
            log_exception(e)
            logger.error(f"Failed to load templates: {e}")
            self.templates = []

    def _clear_encounter_session_data(self) -> None:
        """
        Clear all encounter and simulation related session data.
        Ensures clean state before creating new encounters.
        """
        session.pop('encounter_monsters', None)
        session.pop('selected_encounter', None)
        session.pop('simulation_id', None)
        session.pop('last_simulation_id', None)

    def _validate_encounter_inputs(self, party_level: int, party_size: int, monster_list: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Validate common encounter inputs.

        Args:
            party_level: Level of the party
            party_size: Number of party members
            monster_list: Optional list of monsters to validate

        Raises:
            ValidationError: If any validation fails
        """
        # Validate party level
        if not isinstance(party_level, int):
            raise ValidationError("party_level must be an integer")
        if party_level < MIN_PARTY_LEVEL or party_level > MAX_PARTY_LEVEL:
            raise ValidationError(f"party_level must be between {MIN_PARTY_LEVEL} and {MAX_PARTY_LEVEL}")

        # Validate party size
        if not isinstance(party_size, int):
            raise ValidationError("party_size must be an integer")
        if party_size < MIN_PARTY_SIZE or party_size > MAX_PARTY_SIZE:
            raise ValidationError(f"party_size must be between {MIN_PARTY_SIZE} and {MAX_PARTY_SIZE}")

        # Validate monster list if provided
        if monster_list is not None:
            if not isinstance(monster_list, list):
                raise ValidationError("monster_list must be a list")
            if len(monster_list) == 0:
                raise ValidationError("monster_list cannot be empty")
            if len(monster_list) > MAX_MONSTERS_PER_ENCOUNTER:
                raise ValidationError(f"Too many monsters (max {MAX_MONSTERS_PER_ENCOUNTER})")

    def handle_custom_encounter(self, monster_list: List[Dict[str, Any]], party_level: int, party_size: int) -> Dict[str, Any]:
        """
        Handle creation of a custom encounter from a list of monsters.

        Args:
            monster_list: List of monster dictionaries with stats
            party_level: Level of the adventuring party
            party_size: Number of party members

        Returns:
            Dictionary containing balance, warnings, and monster list

        Raises:
            ValidationError: If validation or encounter creation fails
        """
        # Input validation
        self._validate_encounter_inputs(party_level, party_size, monster_list)

        logger.info(f"Creating custom encounter: {len(monster_list)} monsters, party level {party_level}, size {party_size}")

        # Clear session data
        self._clear_encounter_session_data()

        # Validate and generate warnings (these already raise ValidationError if needed)
        balance = self.validate_encounter_balance(monster_list, party_level, party_size)
        warnings = self.generate_encounter_warnings(monster_list, party_level, party_size)

        # Store in session with deep copy to prevent mutation issues
        session['encounter_monsters'] = copy.deepcopy(monster_list)

        logger.info(f"Custom encounter created successfully with balance: {balance}")

        return {"balance": balance, "warnings": warnings, "monsters": monster_list}

    def handle_prebuilt_encounter(self, template_name: str, party_level: int, party_size: int) -> Dict[str, Any]:
        """
        Handle creation of a prebuilt encounter from a template.

        Args:
            template_name: Name of the encounter template
            party_level: Level of the adventuring party
            party_size: Number of party members

        Returns:
            Dictionary containing balance, warnings, monsters, and template data

        Raises:
            ValidationError: If validation or encounter creation fails
            APIError: If template file cannot be accessed
        """
        # Input validation
        self._validate_encounter_inputs(party_level, party_size)

        if not template_name or not isinstance(template_name, str):
            raise ValidationError("template_name must be a non-empty string")

        # Sanitize template name to prevent potential issues
        template_name = template_name.strip()
        if len(template_name) > 200:
            raise ValidationError("template_name is too long")

        logger.info(f"Creating prebuilt encounter: '{template_name}', party level {party_level}, size {party_size}")

        # Clear session data
        self._clear_encounter_session_data()

        # Find template in cached templates
        template = next((t for t in self.templates if t.get("name") == template_name), None)
        if not template:
            logger.warning(f"Template '{template_name}' not found")
            raise ValidationError(f"Template '{template_name}' not found")

        # Create encounter from template
        try:
            monsters = self.builder.create_encounter_from_template(template)
        except ValueError as e:
            log_exception(e)
            raise ValidationError(f"Encounter creation failed: {e}")

        # Validate and generate warnings
        balance = self.validate_encounter_balance(monsters, party_level, party_size)
        warnings = self.generate_encounter_warnings(monsters, party_level, party_size)

        # Store in session with deep copy
        session['encounter_monsters'] = copy.deepcopy(monsters)
        session['selected_encounter'] = template_name

        logger.info(f"Prebuilt encounter '{template_name}' created successfully with {len(monsters)} monsters, balance: {balance}")

        return {"balance": balance, "warnings": warnings, "monsters": monsters, "template": template}

    def get_current_encounter_monsters(self) -> List[Dict[str, Any]]:
        """
        Get the current encounter monsters from the session.

        Returns:
            List of monster dictionaries, or empty list if none stored
        """
        return session.get('encounter_monsters', [])

    def validate_encounter_balance(self, monsters: List[Dict[str, Any]], party_level: int, party_size: int) -> str:
        """
        Validate the balance of an encounter.

        Args:
            monsters: List of monster dictionaries
            party_level: Level of the party
            party_size: Number of party members

        Returns:
            String describing the encounter difficulty (e.g., "Easy", "Medium", "Hard", "Deadly")

        Raises:
            ValidationError: If balance calculation fails
        """
        try:
            return self.builder.calculate_encounter_difficulty(monsters, party_level, party_size)
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Failed to validate encounter balance: {e}")

    def generate_encounter_warnings(self, monsters: List[Dict[str, Any]], party_level: int, party_size: int) -> List[str]:
        """
        Generate warnings for an encounter based on difficulty and composition.

        Args:
            monsters: List of monster dictionaries
            party_level: Level of the party
            party_size: Number of party members

        Returns:
            List of warning strings, empty if no warnings

        Raises:
            ValidationError: If warning generation fails
        """
        try:
            warning = self.builder.generate_encounter_warning(monsters, party_level, party_size)
            # Return as a list for consistency with the frontend
            # Filter out the "balanced" message as it's not really a warning
            return [warning] if warning and warning != BALANCED_ENCOUNTER_MESSAGE else []
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Failed to generate encounter warnings: {e}")
