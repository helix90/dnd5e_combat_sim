import threading
import time
from typing import List, Dict, Any, Optional
from models.combat import Combat
from models.db import DatabaseManager
from models.monster import Monster
from models.spell_manager import SpellManager
from models.character_builder import build_party
from models.actions import AttackAction, Action
from utils.exceptions import SimulationError, BatchSimulationError
from utils.logging import log_exception

class BatchSimulationController:
    def __init__(self):
        self.db = DatabaseManager()
        self.spell_manager = SpellManager()
        self.batch_threads = {}  # batch_id -> thread
        self.batch_states = {}   # batch_id -> state dict
        self.state_lock = threading.Lock()  # Thread safety for shared state

    def execute_batch_simulation(self, party, monsters, num_runs: int, batch_name: str, session_id: str):
        """
        Start a batch combat simulation in a background thread.
        Returns the batch_id for tracking.
        """
        from utils.logging import logger

        logger.info(f"execute_batch_simulation called: session_id={session_id}, num_runs={num_runs}, batch_name={batch_name}")
        logger.info(f"Party: {len(party)} members, Monsters: {len(monsters)} monsters")

        # Input validation
        if num_runs <= 0:
            raise ValueError("num_runs must be greater than 0")
        if num_runs > 10000:
            raise ValueError("num_runs cannot exceed 10000 to prevent resource exhaustion")
        if not party or len(party) == 0:
            raise ValueError("party cannot be empty")
        if not monsters or len(monsters) == 0:
            raise ValueError("monsters cannot be empty")

        logger.info("Input validation passed")

        # Create batch simulation record first
        party_level = max([char.get('level', 1) for char in party]) if party else 1
        encounter_type = 'custom'  # Could be enhanced to detect prebuilt encounters
        logger.info(f"Creating batch simulation record: party_level={party_level}, encounter_type={encounter_type}")
        batch_id = self.db.create_batch_simulation(session_id, batch_name, party_level, encounter_type)
        logger.info(f"Created batch simulation with ID: {batch_id}")

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

        logger.info(f"Initialized batch state for batch_id={batch_id}")

        def run():
            try:
                logger.info(f"Batch {batch_id} thread started, beginning {num_runs} simulations")

                # Run simulations
                for run_number in range(1, num_runs + 1):
                    logger.debug(f"Batch {batch_id}: Starting run {run_number}/{num_runs}")
                    try:
                        # Fresh Character objects each run, since combat changes HP, slots and buffs
                        character_objects = build_party(party, self.spell_manager)
                        
                        # Convert monster dictionaries to Monster objects
                        monster_objects = []
                        if monsters:
                            for monster_data in monsters:
                                if isinstance(monster_data, dict):
                                    # Build actions from JSON data (same as single simulation controller)
                                    actions = self._build_actions_from_dicts(monster_data.get('actions', []))

                                    monster = Monster(
                                        name=monster_data.get('name', 'Unknown'),
                                        challenge_rating=monster_data.get('cr', '1/4'),
                                        hp=monster_data.get('hp', 10),
                                        ac=monster_data.get('ac', 10),
                                        ability_scores=monster_data.get('ability_scores', {'str': 10, 'dex': 10, 'con': 10, 'int': 10, 'wis': 10, 'cha': 10}),
                                        damage_resistances=monster_data.get('damage_resistances', []),
                                        damage_immunities=monster_data.get('damage_immunities', []),
                                        damage_vulnerabilities=monster_data.get('damage_vulnerabilities', []),
                                        special_abilities=monster_data.get('special_abilities', []),
                                        legendary_actions=monster_data.get('legendary_actions', []),
                                        multiattack=monster_data.get('multiattack', False),
                                        regeneration=monster_data.get('regeneration'),
                                        actions=actions
                                    )
                                    monster_objects.append(monster)
                                elif isinstance(monster_data, Monster):
                                    monster_objects.append(monster_data)
                        
                        # Create combat and run simulation
                        logger.debug(f"Batch {batch_id} run {run_number}: Creating combat with {len(character_objects)} characters and {len(monster_objects)} monsters")
                        combat = Combat(character_objects + monster_objects)
                        logger.debug(f"Batch {batch_id} run {run_number}: Running combat simulation")
                        result = combat.run()
                        logger.debug(f"Batch {batch_id} run {run_number}: Combat finished, winner={result.get('winner', 'unknown')}, rounds={result.get('rounds', 0)}")

                        # Save the simulation and its batch run row atomically
                        sim_id = self.db.save_batch_run_result(session_id, batch_id, run_number, result)
                        logger.debug(f"Batch {batch_id} run {run_number}: Saved simulation as ID {sim_id}")

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
                        logger.error(f"Batch {batch_id} run {run_number} failed with error: {e}", exc_info=True)
                        log_exception(e)
                        # Track failed runs
                        with self.state_lock:
                            state = self.batch_states[batch_id]
                            state['failed_runs'] += 1
                            total_processed = state['completed_runs'] + state['failed_runs']
                            state['progress'] = (total_processed / state['total_runs']) * 100
                        # Continue with next run even if one fails
                        continue

                logger.info(f"Batch {batch_id} completed all {num_runs} runs, finalizing statistics")

                # Snapshot final statistics under the lock, but write them to the DB
                # outside it so progress polling and other batches aren't blocked on I/O
                with self.state_lock:
                    state = self.batch_states[batch_id]
                    completed_runs = state['completed_runs']
                    party_wins = state['party_wins']
                    monster_wins = state['monster_wins']
                    if completed_runs > 0:
                        avg_rounds = state['total_rounds'] / completed_runs
                        avg_party_hp = state['total_party_hp_remaining'] / completed_runs
                    else:
                        avg_rounds = 0
                        avg_party_hp = 0

                logger.info(f"Batch {batch_id}: Updating database statistics")
                self.db.update_batch_statistics(
                    batch_id, completed_runs, party_wins, monster_wins, avg_rounds, avg_party_hp
                )

                # Only mark done once the stats are in the DB, since the results page reads them from there
                with self.state_lock:
                    self.batch_states[batch_id]['done'] = True
                logger.info(f"Batch {batch_id} COMPLETE: {completed_runs} runs, {party_wins} party wins, {monster_wins} monster wins")

            except Exception as e:
                logger.error(f"Batch {batch_id} thread failed with fatal error: {e}", exc_info=True)
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

        logger.info(f"Batch {batch_id}: Starting background thread")
        t = threading.Thread(target=run)
        t.daemon = False  # Ensure thread is not daemon so it completes
        t.start()
        self.batch_threads[batch_id] = t
        logger.info(f"Batch {batch_id}: Thread started, is_alive={t.is_alive()}")
        return batch_id

    def _build_actions_from_dicts(self, action_dicts: Optional[List[Dict[str, Any]]]) -> List[Action]:
        """
        Convert action dictionaries to Action/AttackAction objects.
        Handles both regular attacks and special actions (including breath weapons).

        Args:
            action_dicts: List of action dictionaries from JSON

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
                    damage_dice=ad.get('damage_dice', '1d6'),
                    damage_type=ad.get('damage_type', 'bludgeoning'),
                    weapon_type=ad.get('weapon_type', 'melee'),
                    hit_bonus=ad.get('hit_bonus'),
                    area_effect=ad.get('area_effect', False),
                    save_type=ad.get('save_type'),
                    save_dc=ad.get('save_dc'),
                    on_hit=ad.get('on_hit')
                ))
            elif ad.get('type') == 'special':
                # Check if this is a breath weapon or other damaging special ability
                # Breath weapons have damage_dice and save_dc in their JSON
                if 'damage_dice' in ad and 'save_dc' in ad:
                    # This is a breath weapon - create as AttackAction with area_effect=True
                    actions.append(AttackAction(
                        name=ad.get('name', 'Special'),
                        description=ad.get('description', ad.get('name', 'Special')),
                        weapon_name=ad.get('name', 'Special'),
                        damage_dice=ad.get('damage_dice', '1d6'),
                        damage_type=ad.get('damage_type', 'fire'),
                        weapon_type='melee',  # Not used for save-based attacks
                        hit_bonus=ad.get('hit_bonus'),
                        area_effect=True,  # Breath weapons are always area effects
                        save_type=ad.get('save_type', 'dex'),
                        save_dc=ad.get('save_dc', 10)
                    ))
                else:
                    # Regular special action (like Multiattack)
                    actions.append(Action(
                        action_type='special',
                        name=ad.get('name', 'Special'),
                        description=ad.get('description', ad.get('name', 'Special'))
                    ))
        return actions

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