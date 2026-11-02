import threading
import logging
from typing import Dict, List, Any, Optional
from flask import session
from models.combat import Combat
from models.db import DatabaseManager
from models.spell_manager import SpellManager
from models.character_builder import build_party
from models.monster_builder import build_monsters
from utils.exceptions import SimulationError, ValidationError
from utils.logging import log_exception

# Constants
DEFAULT_PARTY_LEVEL = 5
MIN_PARTY_LEVEL = 1
MAX_PARTY_LEVEL = 20
MAX_PARTY_SIZE = 20
MAX_MONSTER_COUNT = 100

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
            character_objects = build_party(party, self.spell_manager)
            monster_objects = build_monsters(monsters)

            logger.info(f"Simulation setup: {len(character_objects)} characters vs {len(monster_objects)} monsters")

            # Create combat with proper objects
            combat = Combat(character_objects + monster_objects)

            def progress_callback(state: Dict[str, Any]) -> None:
                with self.state_lock:
                    if session_id in self.simulation_states:
                        self.simulation_states[session_id].update(state)

            # Run combat simulation
            result = combat.run(progress_callback=progress_callback)

            # Update final state with complete log (convert to JSON-safe format)
            with self.state_lock:
                if session_id in self.simulation_states:
                    # Convert log to JSON-safe format by removing any non-serializable objects
                    log = result.get('log', [])
                    # Log is already in JSON-safe dict format from combat.run(), just ensure no references
                    self.simulation_states[session_id]['log'] = []  # Don't include log in status, it's saved to DB

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
