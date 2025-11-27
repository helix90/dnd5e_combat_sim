import json
import os
import copy
import logging
import threading
from typing import List, Dict, Any, Tuple

from utils.exceptions import ValidationError
from utils.logging import log_exception

# Constants
PARTY_JSON_FILENAME = 'parties.json'
CHARACTER_JSON_FILENAME = 'characters.json'
DATA_DIR = 'data'
MIN_PARTY_ID = 1
MAX_PARTY_ID = 1000
MIN_LEVEL = 1
MAX_LEVEL = 20
KEY_NAME = 'name'
KEY_CLASS = 'class'
KEY_CHARACTER_CLASS = 'character_class'
KEY_PARTY = 'party'
KEY_CHARACTERS = 'characters'
KEY_LEVEL = 'level'
KEY_ID = 'id'

logger = logging.getLogger(__name__)


class PartyLoader:
    """
    Utility class for loading and managing party data with caching.

    Provides methods to load party configurations and enrich them with
    full character data at specified levels. Uses caching to avoid
    repeated file I/O operations.
    """

    # Class-level caches
    _parties_cache: List[Dict[str, Any]] = None
    _characters_cache: Dict[int, List[Dict[str, Any]]] = None  # level -> characters
    _character_index: Dict[Tuple[int, str, str], Dict[str, Any]] = None  # (level, name, class) -> character
    _cache_lock = threading.Lock()

    # File paths
    _party_json_path: str = None
    _character_json_path: str = None

    @classmethod
    def _initialize_paths(cls) -> None:
        """Initialize file paths if not already set."""
        if cls._party_json_path is None:
            base_dir = os.path.dirname(os.path.dirname(__file__))
            cls._party_json_path = os.path.join(base_dir, DATA_DIR, PARTY_JSON_FILENAME)
            cls._character_json_path = os.path.join(base_dir, DATA_DIR, CHARACTER_JSON_FILENAME)

    @classmethod
    def _load_parties_from_disk(cls) -> List[Dict[str, Any]]:
        """
        Load parties data from disk.

        Returns:
            List of party dictionaries

        Raises:
            ValidationError: If file not found, invalid JSON, or other errors
        """
        cls._initialize_paths()

        try:
            logger.debug(f"Loading parties from {cls._party_json_path}")
            with open(cls._party_json_path, 'r', encoding='utf-8') as f:
                parties = json.load(f)

            if not isinstance(parties, list):
                raise ValidationError("Party data must be a list")

            logger.info(f"Loaded {len(parties)} parties from disk")
            return parties

        except FileNotFoundError as e:
            log_exception(e)
            raise ValidationError(f"Party data file not found: {cls._party_json_path}")
        except json.JSONDecodeError as e:
            log_exception(e)
            raise ValidationError(f"Invalid JSON in party data file: {e}")
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Error loading party data: {e}")

    @classmethod
    def _load_characters_from_disk(cls) -> Dict[int, List[Dict[str, Any]]]:
        """
        Load characters data from disk and organize by level.

        Returns:
            Dictionary mapping level to list of characters

        Raises:
            ValidationError: If file not found, invalid JSON, or other errors
        """
        cls._initialize_paths()

        try:
            logger.debug(f"Loading characters from {cls._character_json_path}")
            with open(cls._character_json_path, 'r', encoding='utf-8') as f:
                all_levels = json.load(f)

            if not isinstance(all_levels, list):
                raise ValidationError("Character data must be a list")

            # Organize by level for O(1) level lookup
            characters_by_level = {}
            total_characters = 0

            for level_data in all_levels:
                level = level_data.get(KEY_LEVEL)
                if level is not None:
                    characters = level_data.get(KEY_PARTY, [])
                    characters_by_level[level] = characters
                    total_characters += len(characters)

            logger.info(f"Loaded {total_characters} characters across {len(characters_by_level)} levels from disk")
            return characters_by_level

        except FileNotFoundError as e:
            log_exception(e)
            raise ValidationError(f"Character data file not found: {cls._character_json_path}")
        except json.JSONDecodeError as e:
            log_exception(e)
            raise ValidationError(f"Invalid JSON in character data file: {e}")
        except Exception as e:
            log_exception(e)
            raise ValidationError(f"Error loading character data: {e}")

    @classmethod
    def _build_character_index(cls) -> Dict[Tuple[int, str, str], Dict[str, Any]]:
        """
        Build an indexed lookup table for O(1) character access.

        Returns:
            Dictionary mapping (level, name, class) to character data
        """
        if cls._characters_cache is None:
            cls._characters_cache = cls._load_characters_from_disk()

        index = {}
        for level, characters in cls._characters_cache.items():
            for char in characters:
                name = char.get(KEY_NAME, '').strip().lower()
                char_class = (
                    char.get(KEY_CLASS) or
                    char.get(KEY_CHARACTER_CLASS) or
                    ''
                ).strip().lower()

                if name and char_class:
                    key = (level, name, char_class)
                    index[key] = char

        logger.debug(f"Built character index with {len(index)} entries")
        return index

    @classmethod
    def _ensure_caches_loaded(cls) -> None:
        """
        Ensure all caches are loaded. Thread-safe.
        """
        with cls._cache_lock:
            if cls._parties_cache is None:
                cls._parties_cache = cls._load_parties_from_disk()

            if cls._characters_cache is None:
                cls._characters_cache = cls._load_characters_from_disk()

            if cls._character_index is None:
                cls._character_index = cls._build_character_index()

    @classmethod
    def clear_cache(cls) -> None:
        """
        Clear all cached data. Useful for testing or reloading data.
        """
        with cls._cache_lock:
            cls._parties_cache = None
            cls._characters_cache = None
            cls._character_index = None

        logger.info("Cleared all party loader caches")

    @classmethod
    def get_available_levels(cls) -> List[int]:
        """
        Get a sorted list of all available character levels.

        Returns:
            Sorted list of integer levels that have character data available

        Raises:
            ValidationError: If character data cannot be loaded
        """
        cls._ensure_caches_loaded()

        with cls._cache_lock:
            available_levels = sorted(cls._characters_cache.keys())

        logger.debug(f"Available character levels: {available_levels}")
        return available_levels

    @classmethod
    def load_parties(cls) -> List[Dict[str, Any]]:
        """
        Load all parties from the JSON file (cached).

        Returns:
            List of party dictionaries

        Raises:
            ValidationError: If data cannot be loaded
        """
        cls._ensure_caches_loaded()

        # Return a deep copy to prevent external modifications
        with cls._cache_lock:
            return copy.deepcopy(cls._parties_cache)

    @classmethod
    def _validate_party_id(cls, party_id: int) -> None:
        """
        Validate party ID parameter.

        Args:
            party_id: Party identifier to validate

        Raises:
            ValidationError: If party_id is invalid
        """
        if not isinstance(party_id, int):
            raise ValidationError("party_id must be an integer")
        if party_id < MIN_PARTY_ID or party_id > MAX_PARTY_ID:
            raise ValidationError(f"party_id must be between {MIN_PARTY_ID} and {MAX_PARTY_ID}")

    @classmethod
    def _validate_level(cls, level: int) -> None:
        """
        Validate level parameter.

        Args:
            level: Character level to validate

        Raises:
            ValidationError: If level is invalid
        """
        if not isinstance(level, int):
            raise ValidationError("level must be an integer")
        if level < MIN_LEVEL or level > MAX_LEVEL:
            raise ValidationError(f"level must be between {MIN_LEVEL} and {MAX_LEVEL}")

    @classmethod
    def get_party_by_id(cls, party_id: int) -> Dict[str, Any]:
        """
        Get a single party by its ID.

        Args:
            party_id: Unique identifier for the party

        Returns:
            Party dictionary with all party data

        Raises:
            ValidationError: If party_id is invalid or party not found
        """
        # Validate input
        cls._validate_party_id(party_id)

        # Ensure cache is loaded
        cls._ensure_caches_loaded()

        logger.debug(f"Looking up party with ID {party_id}")

        # Search for party
        with cls._cache_lock:
            for party in cls._parties_cache:
                if party.get(KEY_ID) == party_id:
                    logger.info(f"Found party with ID {party_id}: {party.get(KEY_NAME, 'Unknown')}")
                    # Return deep copy to prevent external modifications
                    return copy.deepcopy(party)

        # Not found
        logger.warning(f"Party with ID {party_id} not found")
        raise ValidationError(f"Party with ID {party_id} not found")

    @classmethod
    def _lookup_character(
        cls,
        name: str,
        char_class: str,
        level: int
    ) -> Dict[str, Any]:
        """
        Look up a character by name, class, and level using indexed cache.

        Args:
            name: Character name
            char_class: Character class
            level: Character level

        Returns:
            Character data dictionary, or None if not found
        """
        # Normalize for lookup
        name_normalized = name.strip().lower()
        class_normalized = char_class.strip().lower()

        # O(1) lookup using index
        key = (level, name_normalized, class_normalized)
        with cls._cache_lock:
            return cls._character_index.get(key)

    @classmethod
    def get_party_with_level(cls, party_id: int, level: int) -> Dict[str, Any]:
        """
        Get a party by ID, enriching each character with full data for the given level.

        Replaces basic character references with complete character data including
        stats, spells, abilities, etc. for the specified level.

        Args:
            party_id: Unique identifier for the party
            level: Character level to use (1-20)

        Returns:
            Party dictionary with enriched character data

        Raises:
            ValidationError: If party_id or level invalid, party not found,
                           or level data not found
        """
        # Validate inputs
        cls._validate_party_id(party_id)
        cls._validate_level(level)

        logger.info(f"Loading party {party_id} with level {level}")

        # Ensure caches are loaded
        cls._ensure_caches_loaded()

        # Get base party
        party = cls.get_party_by_id(party_id)

        # Check if level data exists, fall back to closest level if not
        actual_level = level
        with cls._cache_lock:
            if level not in cls._characters_cache:
                # Find the closest available level (prefer lower levels to avoid overpowering)
                available_levels = sorted(cls._characters_cache.keys())
                if not available_levels:
                    logger.error("No character data found for any level")
                    raise ValidationError("No character data available")

                # Find closest level <= requested level, or highest available if all are lower
                closest_level = None
                for avail_level in reversed(available_levels):
                    if avail_level <= level:
                        closest_level = avail_level
                        break

                if closest_level is None:
                    # All available levels are higher than requested, use the lowest
                    closest_level = available_levels[0]

                actual_level = closest_level
                logger.warning(
                    f"Level {level} not found in character data, "
                    f"using closest available level {actual_level}"
                )

        # Enrich party with full character data
        full_party = []
        characters = party.get(KEY_CHARACTERS, [])

        logger.debug(f"Enriching {len(characters)} characters for party {party_id} at level {actual_level}")

        for c in characters:
            # Extract character identifiers
            name = c.get(KEY_NAME, '').strip()
            char_class = (
                c.get(KEY_CLASS) or
                c.get(KEY_CHARACTER_CLASS) or
                ''
            ).strip()

            if not name or not char_class:
                logger.warning(f"Skipping character with missing name or class: {c}")
                full_party.append(copy.deepcopy(c))
                continue

            # O(1) lookup using index with actual_level
            found = cls._lookup_character(name, char_class, actual_level)

            if found:
                logger.debug(f"Found full data for {name} ({char_class}) at level {actual_level}")
                full_party.append(copy.deepcopy(found))
            else:
                # Fallback to original party character if not found
                logger.warning(
                    f"Character '{name}' ({char_class}) not found at level {actual_level}, "
                    f"using fallback data"
                )
                full_party.append(copy.deepcopy(c))

        # Create enriched party dictionary
        enriched_party = copy.deepcopy(party)
        enriched_party[KEY_CHARACTERS] = full_party
        # Store the actual level used
        enriched_party[KEY_LEVEL] = actual_level

        logger.info(
            f"Successfully loaded party {party_id} with {len(full_party)} characters at level {actual_level}"
            + (f" (requested level {level})" if actual_level != level else "")
        )

        return enriched_party
