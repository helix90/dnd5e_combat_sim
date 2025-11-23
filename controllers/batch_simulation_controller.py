import threading
import time
import json
from typing import List, Dict, Any, Optional
from models.combat import Combat
from models.db import DatabaseManager
from models.character import Character
from models.monster import Monster
from models.spell_manager import SpellManager
from utils.exceptions import SimulationError, BatchSimulationError
from utils.logging import log_exception

class BatchSimulationController:
    def __init__(self):
        self.db = DatabaseManager()
        self.spell_manager = SpellManager()
        self.batch_threads = {}  # batch_id -> thread
        self.batch_states = {}   # batch_id -> state dict
        self.state_lock = threading.Lock()  # Thread safety for shared state
        self.character_cache = None  # Cache for character data
        self._load_character_cache()

    def execute_batch_simulation(self, party, monsters, num_runs: int, batch_name: str, session_id: str):
        """
        Start a batch combat simulation in a background thread.
        Returns the batch_id for tracking.
        """
        # Input validation
        if num_runs <= 0:
            raise ValueError("num_runs must be greater than 0")
        if num_runs > 10000:
            raise ValueError("num_runs cannot exceed 10000 to prevent resource exhaustion")
        if not party or len(party) == 0:
            raise ValueError("party cannot be empty")
        if not monsters or len(monsters) == 0:
            raise ValueError("monsters cannot be empty")

        # Create batch simulation record first
        party_level = max([char.get('level', 1) for char in party]) if party else 1
        encounter_type = 'custom'  # Could be enhanced to detect prebuilt encounters
        batch_id = self.db.create_batch_simulation(session_id, batch_name, party_level, encounter_type)

        # Initialize state BEFORE starting thread so it's immediately available for progress polling
        with self.state_lock:
            self.batch_states[batch_id] = {
                'progress': 0,
                'completed_runs': 0,
                'failed_runs': 0,
                'total_runs': num_runs,
                'party_wins': 0,
                'monster_wins': 0,
                'total_rounds': 0,
                'total_party_hp_remaining': 0,
                'done': False,
                'error': None
            }

        def run():
            try:
                
                # Run simulations
                for run_number in range(1, num_runs + 1):
                    try:
                        # Convert party dictionaries to Character objects
                        character_objects = []
                        if party:
                            for char_data in party:
                                if isinstance(char_data, dict):
                                    # Load full character data from characters.json
                                    full_char_data = self._load_full_character_data(char_data)
                                    if full_char_data:
                                        char = Character(
                                            name=full_char_data.get('name', char_data.get('name', 'Unknown')),
                                            level=full_char_data.get('level', char_data.get('level', 1)),
                                            character_class=full_char_data.get('character_class', char_data.get('class', 'Fighter')),
                                            race=full_char_data.get('race', 'Human'),
                                            ability_scores=full_char_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
                                            hp=full_char_data.get('hp', 10),
                                            ac=full_char_data.get('ac', 10),
                                            proficiency_bonus=full_char_data.get('proficiency_bonus', 2),
                                            spell_slots=full_char_data.get('spell_slots', {}),
                                            spell_list=full_char_data.get('spell_list', [])
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
                                            name=char_data.get('name', 'Unknown'),
                                            level=char_data.get('level', 1),
                                            character_class=char_data.get('class', 'Fighter'),
                                            race=char_data.get('race', 'Human'),
                                            ability_scores=char_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
                                            hp=char_data.get('hp', 10),
                                            ac=char_data.get('ac', 10),
                                            proficiency_bonus=char_data.get('proficiency_bonus', 2)
                                        )
                                        character_objects.append(char)
                                elif isinstance(char_data, Character):
                                    character_objects.append(char_data)
                        
                        # Convert monster dictionaries to Monster objects
                        monster_objects = []
                        if monsters:
                            for monster_data in monsters:
                                if isinstance(monster_data, dict):
                                    monster = Monster(
                                        name=monster_data.get('name', 'Unknown'),
                                        challenge_rating=monster_data.get('cr', '1/4'),
                                        hp=monster_data.get('hp', 10),
                                        ac=monster_data.get('ac', 10),
                                        ability_scores=monster_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10})
                                    )
                                    monster_objects.append(monster)
                                elif isinstance(monster_data, Monster):
                                    monster_objects.append(monster_data)
                        
                        # Create combat and run simulation
                        combat = Combat(character_objects + monster_objects)
                        result = combat.run()
                        
                        # Save individual simulation
                        sim_id = self.db.save_simulation_result(session_id, result)
                        
                        # Add to batch
                        self.db.add_batch_run(
                            batch_id, sim_id, run_number,
                            result.get('winner', 'unknown'),
                            result.get('rounds', 0),
                            result.get('party_hp_remaining', 0)
                        )
                        
                        # Update batch statistics with thread safety
                        with self.state_lock:
                            state = self.batch_states[batch_id]
                            state['completed_runs'] += 1
                            state['total_rounds'] += result.get('rounds', 0)
                            state['total_party_hp_remaining'] += result.get('party_hp_remaining', 0)

                            if result.get('winner') == 'party':
                                state['party_wins'] += 1
                            else:
                                state['monster_wins'] += 1

                            # Update progress (includes both completed and failed)
                            total_processed = state['completed_runs'] + state['failed_runs']
                            state['progress'] = (total_processed / state['total_runs']) * 100

                    except Exception as e:
                        log_exception(e)
                        # Track failed runs
                        with self.state_lock:
                            state = self.batch_states[batch_id]
                            state['failed_runs'] += 1
                            total_processed = state['completed_runs'] + state['failed_runs']
                            state['progress'] = (total_processed / state['total_runs']) * 100
                        # Continue with next run even if one fails
                        continue
                
                # Finalize batch statistics with thread safety
                with self.state_lock:
                    state = self.batch_states[batch_id]
                    if state['completed_runs'] > 0:
                        avg_rounds = state['total_rounds'] / state['completed_runs']
                        avg_party_hp = state['total_party_hp_remaining'] / state['completed_runs']
                    else:
                        avg_rounds = 0
                        avg_party_hp = 0

                    self.db.update_batch_statistics(
                        batch_id, state['completed_runs'], state['party_wins'],
                        state['monster_wins'], avg_rounds, avg_party_hp
                    )

                    state['done'] = True

            except Exception as e:
                log_exception(e)
                # Don't raise in thread - store error in state instead
                with self.state_lock:
                    self.batch_states[batch_id] = {
                        'error': str(e),
                        'done': True,
                        'progress': 0,
                        'completed_runs': 0,
                        'failed_runs': 0,
                        'total_runs': num_runs
                    }
        
        t = threading.Thread(target=run)
        t.start()
        self.batch_threads[batch_id] = t
        return batch_id

    def _load_character_cache(self):
        """
        Load and cache character data from characters.json for fast lookups.
        Creates an indexed cache: {(name, class, level): character_data}
        """
        try:
            with open('data/characters.json', 'r') as f:
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
        except Exception as e:
            log_exception(e)
            self.character_cache = {}

    def _load_full_character_data(self, char_data):
        """
        Load full character data from cache based on name, class, and level.
        """
        if self.character_cache is None:
            return None

        char_name = char_data.get('name', '')
        char_class = char_data.get('class', '')
        char_level = char_data.get('level', 1)

        cache_key = (char_name, char_class, char_level)
        return self.character_cache.get(cache_key)

    def get_batch_progress(self, batch_id: int) -> Dict[str, Any]:
        """
        Get the current progress of a batch simulation.
        """
        with self.state_lock:
            return self.batch_states.get(batch_id, {
                'progress': 0,
                'completed_runs': 0,
                'failed_runs': 0,
                'total_runs': 0,
                'party_wins': 0,
                'monster_wins': 0,
                'done': False,
                'error': None
            }).copy()  # Return a copy to avoid external modifications

    def get_batch_results(self, batch_id: int) -> Dict[str, Any]:
        """
        Get the final results of a batch simulation.
        """
        try:
            batch = self.db.get_batch_simulation(batch_id)
            if not batch:
                raise BatchSimulationError(f"Batch simulation {batch_id} not found")
            
            runs = self.db.get_batch_runs(batch_id)
            
            # Calculate additional statistics
            win_rate = (batch['party_wins'] / batch['total_runs']) * 100 if batch['total_runs'] > 0 else 0
            loss_rate = (batch['monster_wins'] / batch['total_runs']) * 100 if batch['total_runs'] > 0 else 0
            
            return {
                'batch': batch,
                'runs': runs,
                'statistics': {
                    'win_rate': round(win_rate, 2),
                    'loss_rate': round(loss_rate, 2),
                    'average_rounds': round(batch['average_rounds'], 2),
                    'average_party_hp_remaining': round(batch['average_party_hp_remaining'], 2)
                }
            }
        except Exception as e:
            log_exception(e)
            raise BatchSimulationError(f"Failed to get batch results: {e}")

    def get_batch_history(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get batch simulation history for a session.
        """
        try:
            return self.db.get_batch_history(session_id)
        except Exception as e:
            log_exception(e)
            raise BatchSimulationError(f"Failed to get batch history: {e}")

    def cleanup_batch(self, batch_id: int):
        """
        Clean up resources for a completed batch simulation.
        Should be called after retrieving final results.
        """
        with self.state_lock:
            # Only cleanup if batch is done
            if batch_id in self.batch_states and self.batch_states[batch_id].get('done', False):
                # Remove state
                if batch_id in self.batch_states:
                    del self.batch_states[batch_id]
                # Remove thread reference
                if batch_id in self.batch_threads:
                    del self.batch_threads[batch_id]

    def cleanup_completed_batches(self):
        """
        Clean up all completed batch simulations to free memory.
        Should be called periodically or when memory is a concern.
        """
        with self.state_lock:
            completed_ids = [
                batch_id for batch_id, state in self.batch_states.items()
                if state.get('done', False)
            ]

        # Cleanup outside the lock to avoid holding it too long
        for batch_id in completed_ids:
            self.cleanup_batch(batch_id)

    def shutdown(self):
        """
        Gracefully shutdown by waiting for all batch threads to complete.
        Call this before application exit.
        """
        with self.state_lock:
            thread_ids = list(self.batch_threads.keys())

        for batch_id in thread_ids:
            thread = self.batch_threads.get(batch_id)
            if thread and thread.is_alive():
                thread.join(timeout=30)  # Wait max 30 seconds per thread 