import threading
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from flask import session
from models.combat import Combat
from models.db import DatabaseManager
from models.character import Character
from models.monster import Monster
from models.spell_manager import SpellManager
from utils.exceptions import SimulationError, ValidationError
from utils.logging import log_exception
from models.actions import AttackAction, Action

# Constants
DEFAULT_PARTY_LEVEL = 5
DEFAULT_CHARACTER_LEVEL = 1
DEFAULT_HP = 10
DEFAULT_AC = 10
DEFAULT_PROFICIENCY_BONUS = 2
DEFAULT_ABILITY_SCORES = {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}
DEFAULT_DAMAGE_DICE = '1d6'
DEFAULT_DAMAGE_TYPE = 'bludgeoning'
DEFAULT_RACE = 'Human'
DEFAULT_CLASS = 'Fighter'
DEFAULT_CR = '1/4'
UNKNOWN_NAME = 'Unknown'
MIN_PARTY_LEVEL = 1
MAX_PARTY_LEVEL = 20
MAX_PARTY_SIZE = 20
MAX_MONSTER_COUNT = 100
CHARACTERS_DATA_FILE = 'data/characters.json'

logger = logging.getLogger(__name__)


class SimulationController:
    """
    Controller for managing combat simulations in background threads.
    Handles character/monster conversion, combat execution, and result persistence.
    """

    def __init__(self):
        """Initialize the simulation controller with caching and thread safety."""
        self.db = DatabaseManager()
        self.spell_manager = SpellManager()
        self.simulation_threads: Dict[str, threading.Thread] = {}  # session_id -> thread
        self.simulation_states: Dict[str, Dict[str, Any]] = {}   # session_id -> state dict
        self.state_lock = threading.Lock()  # Thread safety for shared state
        self.character_cache: Optional[Dict[Tuple[str, str, int], Dict[str, Any]]] = None
        self._load_character_cache()

    def _load_character_cache(self) -> None:
        """
        Load and cache character data from characters.json for fast lookups.
        Creates an indexed cache: {(name, class, level): character_data}
        """
        try:
            with open(CHARACTERS_DATA_FILE, 'r') as f:
                characters_data = json.load(f)

            self.character_cache = {}
            for level_data in characters_data:
                level = level_data.get('level')
                for char in level_data.get('party', []):
                    cache_key = (
                        char.get('name'),
                        char.get('character_class'),
                        level
                    )
                    self.character_cache[cache_key] = char
            logger.info(f"Loaded {len(self.character_cache)} character entries into cache")
        except Exception as e:
            log_exception(e)
            logger.warning(f"Failed to load character cache: {e}")
            self.character_cache = {}

    def _validate_simulation_inputs(
        self,
        party: List[Any],
        monsters: List[Any],
        session_id: str,
        party_level: int
    ) -> None:
        """
        Validate simulation inputs before execution.

        Args:
            party: List of character data
            monsters: List of monster data
            session_id: Session identifier
            party_level: Level for the party

        Raises:
            ValidationError: If any validation fails
        """
        # Validate session_id
        if not session_id or not isinstance(session_id, str):
            raise ValidationError("session_id must be a non-empty string")
        if len(session_id) > 200:
            raise ValidationError("session_id is too long")

        # Validate party (type and size, but allow empty for compatibility)
        if party is None or not isinstance(party, list):
            raise ValidationError("party must be a list")
        if len(party) > MAX_PARTY_SIZE:
            raise ValidationError(f"party size cannot exceed {MAX_PARTY_SIZE}")

        # Validate monsters (type and size, but allow empty for compatibility)
        if monsters is None or not isinstance(monsters, list):
            raise ValidationError("monsters must be a list")
        if len(monsters) > MAX_MONSTER_COUNT:
            raise ValidationError(f"monster count cannot exceed {MAX_MONSTER_COUNT}")

        # Validate party_level
        if not isinstance(party_level, int):
            raise ValidationError("party_level must be an integer")
        if party_level < MIN_PARTY_LEVEL or party_level > MAX_PARTY_LEVEL:
            raise ValidationError(f"party_level must be between {MIN_PARTY_LEVEL} and {MAX_PARTY_LEVEL}")

    def _build_actions_from_dicts(self, action_dicts: Optional[List[Dict[str, Any]]]) -> List[Action]:
        """
        Convert action dictionaries to Action/AttackAction objects.

        Args:
            action_dicts: List of action dictionaries

        Returns:
            List of Action objects
        """
        actions = []
        for ad in action_dicts or []:
            if ad.get('type') == 'attack':
                actions.append(AttackAction(
                    name=ad.get('name', 'Attack'),
                    description=ad.get('description', ad.get('name', 'Attack')),
                    weapon_name=ad.get('name', 'Weapon'),
                    damage_dice=ad.get('damage_dice', DEFAULT_DAMAGE_DICE),
                    damage_type=ad.get('damage_type', DEFAULT_DAMAGE_TYPE)
                ))
            elif ad.get('type') == 'special':
                actions.append(Action(
                    action_type='special',
                    name=ad.get('name', 'Special'),
                    description=ad.get('description', ad.get('name', 'Special'))
                ))
        return actions

    def _load_full_character_data(self, char_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Load full character data from cache based on name, class, and level.
        Finds the highest available level <= requested, or fallback to lowest available.

        Args:
            char_data: Character data dictionary with name, class, and level

        Returns:
            Full character data dictionary, or None if not found
        """
        if self.character_cache is None:
            return None

        char_name = char_data.get('name', '')
        char_class = char_data.get('class') or char_data.get('character_class') or ''
        char_level = char_data.get('level', DEFAULT_CHARACTER_LEVEL)

        logger.debug(f"Looking up character: name='{char_name}', class='{char_class}', level={char_level}")

        # Gather all matching entries for this name/class
        matches = []
        for (cache_name, cache_class, cache_level), char in self.character_cache.items():
            if cache_name == char_name and cache_class == char_class:
                matches.append((cache_level, char))

        if not matches:
            logger.warning(f"No match found for character: name='{char_name}', class='{char_class}'")
            return None

        # Find the highest level <= requested
        best = None
        best_level = -1
        for lvl, char in matches:
            if lvl is not None and lvl <= char_level and lvl > best_level:
                best = char
                best_level = lvl

        if best:
            logger.debug(f"Found best match for {char_name} at level {best_level}")
            return best

        # Fallback: return the lowest available level
        min_level, min_char = min(matches, key=lambda x: x[0] if x[0] is not None else 999)
        logger.debug(f"Using fallback match for {char_name} at level {min_level}")
        return min_char

    def _convert_party_to_characters(
        self,
        party: List[Any],
        party_level: int
    ) -> List[Character]:
        """
        Convert party data (dicts or Character objects) to Character objects.

        Args:
            party: List of character data (dicts or Character objects)
            party_level: Level to use for all characters

        Returns:
            List of Character objects
        """
        character_objects = []

        for char_data in party:
            if isinstance(char_data, Character):
                character_objects.append(char_data)
                continue

            if not isinstance(char_data, dict):
                logger.warning(f"Skipping character with unexpected type: {type(char_data)}")
                continue

            # Override level with selected party level
            char_data = char_data.copy()
            char_data['level'] = party_level

            # Ensure both 'class' and 'character_class' are set for lookup
            if 'class' in char_data:
                char_data['character_class'] = char_data['class']
            elif 'character_class' in char_data:
                char_data['class'] = char_data['character_class']

            # Load full character data from cache
            full_char_data = self._load_full_character_data(char_data)

            if full_char_data:
                # Convert actions from dicts to Action/AttackAction objects
                actions = self._build_actions_from_dicts(full_char_data.get('actions', []))

                char = Character(
                    name=full_char_data.get('name', char_data.get('name', UNKNOWN_NAME)),
                    level=party_level,
                    character_class=full_char_data.get('character_class', char_data.get('class', DEFAULT_CLASS)),
                    race=full_char_data.get('race', DEFAULT_RACE),
                    ability_scores=full_char_data.get('ability_scores', DEFAULT_ABILITY_SCORES),
                    hp=full_char_data.get('hp', DEFAULT_HP),
                    ac=full_char_data.get('ac', DEFAULT_AC),
                    proficiency_bonus=full_char_data.get('proficiency_bonus', DEFAULT_PROFICIENCY_BONUS),
                    spell_slots=full_char_data.get('spell_slots', {}),
                    spell_list=full_char_data.get('spell_list', []),
                    features=full_char_data.get('features', []),
                    items=full_char_data.get('items', []),
                    spells=full_char_data.get('spells', {}),
                    actions=actions,
                    reactions=full_char_data.get('reactions', []),
                    bonus_actions=full_char_data.get('bonus_actions', []),
                    initiative_bonus=full_char_data.get('initiative_bonus', 0),
                    notes=full_char_data.get('notes', ''),
                )

                # Add spells to character
                for spell_name in full_char_data.get('spell_list', []):
                    spell = self.spell_manager.get_spell(spell_name)
                    if spell:
                        char.add_spell(spell)

                character_objects.append(char)
            else:
                # Fallback to basic character creation
                char = Character(
                    name=char_data.get('name', UNKNOWN_NAME),
                    level=char_data.get('level', DEFAULT_CHARACTER_LEVEL),
                    character_class=char_data.get('class', DEFAULT_CLASS),
                    race=char_data.get('race', DEFAULT_RACE),
                    ability_scores=char_data.get('ability_scores', DEFAULT_ABILITY_SCORES),
                    hp=char_data.get('hp', DEFAULT_HP),
                    ac=char_data.get('ac', DEFAULT_AC),
                    proficiency_bonus=char_data.get('proficiency_bonus', DEFAULT_PROFICIENCY_BONUS)
                )
                character_objects.append(char)

        return character_objects

    def _convert_monsters_to_objects(self, monsters: List[Any]) -> List[Monster]:
        """
        Convert monster data (dicts or Monster objects) to Monster objects.

        Args:
            monsters: List of monster data (dicts or Monster objects)

        Returns:
            List of Monster objects
        """
        monster_objects = []

        for i, monster_data in enumerate(monsters):
            if isinstance(monster_data, Monster):
                monster_objects.append(monster_data)
                continue

            if not isinstance(monster_data, dict):
                logger.warning(f"Skipping monster {i+1} with unexpected type: {type(monster_data)}")
                continue

            actions = self._build_actions_from_dicts(monster_data.get('actions', []))

            monster = Monster(
                name=monster_data.get('name', UNKNOWN_NAME),
                challenge_rating=monster_data.get('cr', DEFAULT_CR),
                hp=monster_data.get('hp', DEFAULT_HP),
                ac=monster_data.get('ac', DEFAULT_AC),
                ability_scores=monster_data.get('ability_scores', DEFAULT_ABILITY_SCORES),
                damage_resistances=monster_data.get('damage_resistances', []),
                damage_immunities=monster_data.get('damage_immunities', []),
                special_abilities=monster_data.get('special_abilities', []),
                legendary_actions=monster_data.get('legendary_actions', []),
                multiattack=monster_data.get('multiattack', False),
                actions=actions
            )
            monster_objects.append(monster)

        return monster_objects

    def _run_simulation_thread(
        self,
        party: List[Any],
        monsters: List[Any],
        session_id: str,
        party_level: int
    ) -> None:
        """
        Run the simulation in a background thread.

        Args:
            party: List of character data
            monsters: List of monster data
            session_id: Session identifier
            party_level: Level for the party
        """
        try:
            logger.info(f"Starting simulation thread for session {session_id}, party level {party_level}")

            # Convert party and monsters to objects
            character_objects = self._convert_party_to_characters(party, party_level)
            monster_objects = self._convert_monsters_to_objects(monsters)

            logger.info(f"Simulation setup: {len(character_objects)} characters vs {len(monster_objects)} monsters")

            # Create combat with proper objects
            combat = Combat(character_objects + monster_objects)

            def progress_callback(state: Dict[str, Any]) -> None:
                with self.state_lock:
                    if session_id in self.simulation_states:
                        self.simulation_states[session_id].update(state)

            # Run combat simulation
            result = combat.run(progress_callback=progress_callback)

            # Update final state with complete log
            with self.state_lock:
                if session_id in self.simulation_states:
                    self.simulation_states[session_id]['log'] = result.get('log', [])

            # Save results to database
            sim_id = self.save_simulation_results(result, session_id)
            logger.info(f"Simulation completed successfully, saved as ID {sim_id}")

            # Mark as done
            with self.state_lock:
                if session_id in self.simulation_states:
                    self.simulation_states[session_id]['done'] = True
                    logger.info(f"Marked simulation as done for session {session_id}. Final state: {self.simulation_states[session_id]}")
                else:
                    logger.warning(f"Cannot mark as done - session {session_id} not in simulation_states")

        except Exception as e:
            log_exception(e)
            logger.error(f"Simulation failed for session {session_id}: {e}")
            # Store error in state (don't raise - thread is detached)
            with self.state_lock:
                self.simulation_states[session_id] = {
                    'error': str(e),
                    'done': True,
                    'progress': 0,
                    'log': []
                }

    def execute_simulation(
        self,
        party: List[Any],
        monsters: List[Any],
        session_id: str,
        party_level: int = DEFAULT_PARTY_LEVEL
    ) -> None:
        """
        Execute a combat simulation in a background thread.

        Args:
            party: List of character data (dicts or Character objects)
            monsters: List of monster data (dicts or Monster objects)
            session_id: Session identifier for tracking
            party_level: Level to use for all party members

        Raises:
            ValidationError: If input validation fails
        """
        # Input validation
        self._validate_simulation_inputs(party, monsters, session_id, party_level)

        logger.info(f"Executing simulation for session {session_id}: {len(party)} party members at level {party_level} vs {len(monsters)} monsters")

        # Initialize state before starting thread (prevents race condition)
        with self.state_lock:
            # Clear any existing simulation state and thread for this session
            if session_id in self.simulation_states:
                del self.simulation_states[session_id]
            if session_id in self.simulation_threads:
                del self.simulation_threads[session_id]

            # Set initial state
            self.simulation_states[session_id] = {
                'progress': 0,
                'log': [],
                'done': False
            }

        # Create and start thread
        t = threading.Thread(
            target=self._run_simulation_thread,
            args=(party, monsters, session_id, party_level)
        )
        t.daemon = True  # Allow program to exit even if thread is running

        with self.state_lock:
            self.simulation_threads[session_id] = t

        t.start()

    def get_simulation_id(self, session_id: str) -> Optional[int]:
        """
        Get the simulation ID for a given session from the simulation state.

        Args:
            session_id: Session identifier

        Returns:
            Simulation ID if found, None otherwise
        """
        with self.state_lock:
            if session_id in self.simulation_states:
                return self.simulation_states[session_id].get('simulation_id')
        return None

    def handle_simulation_progress(self) -> Dict[str, Any]:
        """
        Return the current simulation state for the current session.

        Returns:
            Dictionary containing progress, log, done status, and optional error

        Raises:
            KeyError: If session_id not in Flask session
        """
        session_id = session['session_id']
        with self.state_lock:
            logger.info(f"handle_simulation_progress: session_id={session_id}, available_sessions={list(self.simulation_states.keys())}")
            state = self.simulation_states.get(session_id, {
                'progress': 0,
                'log': [],
                'done': False
            })
            logger.info(f"handle_simulation_progress: returning state={state}")
            return state.copy()  # Return copy to prevent external modifications

    def save_simulation_results(self, result: Dict[str, Any], session_id: str) -> int:
        """
        Save simulation results to the database.

        Args:
            result: Combat result dictionary
            session_id: Session identifier

        Returns:
            Simulation ID from database

        Raises:
            SimulationError: If saving fails
        """
        try:
            # Ensure session exists in database before saving simulation results
            self.db.create_session(session_id)

            sim_id = self.db.save_simulation_result(session_id, result)
            logger.info(f"Saved simulation results as ID {sim_id} for session {session_id}")

            # Store the simulation ID in the session state for easy access
            with self.state_lock:
                if session_id in self.simulation_states:
                    self.simulation_states[session_id]['simulation_id'] = sim_id

            # Store the simulation ID in the Flask session (only if in request context)
            try:
                session['last_simulation_id'] = sim_id
                session['simulation_id'] = sim_id
            except RuntimeError:
                # Working outside of request context, skip session storage
                logger.debug("Not in request context, skipping Flask session storage")
                pass

            return sim_id
        except Exception as e:
            log_exception(e)
            raise SimulationError(f"Failed to save simulation results: {e}")

    def cleanup_simulation(self, session_id: str) -> None:
        """
        Clean up resources for a completed simulation.
        Should be called after retrieving final results.

        Args:
            session_id: Session identifier to clean up
        """
        with self.state_lock:
            # Only cleanup if simulation is done
            if session_id in self.simulation_states:
                if self.simulation_states[session_id].get('done', False):
                    del self.simulation_states[session_id]
                    logger.debug(f"Cleaned up simulation state for session {session_id}")

            if session_id in self.simulation_threads:
                del self.simulation_threads[session_id]
                logger.debug(f"Cleaned up simulation thread for session {session_id}")

    def cleanup_completed_simulations(self) -> None:
        """
        Clean up all completed simulations to free memory.
        Should be called periodically or when memory is a concern.
        """
        with self.state_lock:
            completed_sessions = [
                sid for sid, state in self.simulation_states.items()
                if state.get('done', False)
            ]

        # Cleanup outside the lock to avoid holding it too long
        for session_id in completed_sessions:
            self.cleanup_simulation(session_id)

        if completed_sessions:
            logger.info(f"Cleaned up {len(completed_sessions)} completed simulations")

    def shutdown(self) -> None:
        """
        Gracefully shutdown by waiting for all simulation threads to complete.
        Call this before application exit.
        """
        with self.state_lock:
            session_ids = list(self.simulation_threads.keys())

        logger.info(f"Shutting down simulation controller, waiting for {len(session_ids)} threads")

        for session_id in session_ids:
            with self.state_lock:
                thread = self.simulation_threads.get(session_id)

            if thread and thread.is_alive():
                logger.debug(f"Waiting for simulation thread {session_id} to complete")
                thread.join(timeout=30)  # Wait max 30 seconds per thread

                if thread.is_alive():
                    logger.warning(f"Simulation thread {session_id} did not complete within timeout")

        logger.info("Simulation controller shutdown complete")
