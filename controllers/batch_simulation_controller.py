import copy
import threading
from typing import List, Dict, Any, Optional
from models.arena_library import get_arena
from models.combat import Combat
from models.db import DatabaseManager
from models.spell_manager import SpellManager
from models.character_builder import build_party
from models.monster_builder import build_monsters
from utils.exceptions import SimulationError, BatchSimulationError
from utils.logging import log_exception


class BatchSimulationController:
    def __init__(self):
        self.db = DatabaseManager()
        self.spell_manager = SpellManager()
        self.batch_threads = {}  # batch_id -> thread
        self.batch_states = {}  # batch_id -> state dict
        self.state_lock = threading.Lock()  # Thread safety for shared state

    def execute_batch_simulation(
        self,
        party,
        monsters,
        num_runs: int,
        batch_name: str,
        session_id: str,
        arena_name: str = None,
        compare_without_arena: bool = False,
    ):
        """
        Start a batch combat simulation in a background thread, on the named arena (a map in
        data/arenas.json) or without one. Returns the batch_id for tracking.

        With an arena and compare_without_arena, each run is fought again without the arena,
        saved as a second batch (the "baseline") that the first one points to, so the results
        page can show what the map changed.
        """
        from utils.logging import logger

        logger.info(
            f"execute_batch_simulation called: session_id={session_id}, num_runs={num_runs}, batch_name={batch_name}"
        )
        logger.debug(f"Party: {len(party)} members, Monsters: {len(monsters)} monsters")

        # Input validation
        if num_runs <= 0:
            raise ValueError("num_runs must be greater than 0")
        if num_runs > 10000:
            raise ValueError(
                "num_runs cannot exceed 10000 to prevent resource exhaustion"
            )
        if not party or len(party) == 0:
            raise ValueError("party cannot be empty")
        if not monsters or len(monsters) == 0:
            raise ValueError("monsters cannot be empty")
        arena = get_arena(arena_name)  # ValueError for an unknown map

        logger.debug("Input validation passed")

        # Create batch simulation record first
        party_level = max(
            (
                char.get("level", 1)
                if isinstance(char, dict)
                else getattr(char, "level", 1)
            )
            for char in party
        )
        encounter_type = "custom"  # Could be enhanced to detect prebuilt encounters
        logger.debug(
            f"Creating batch simulation record: party_level={party_level}, encounter_type={encounter_type}"
        )
        baseline_id = None
        if arena is not None and compare_without_arena:
            baseline_id = self.db.create_batch_simulation(
                session_id, f"{batch_name} (no arena)", party_level, encounter_type
            )
        batch_id = self.db.create_batch_simulation(
            session_id,
            batch_name,
            party_level,
            encounter_type,
            arena=arena_name or None,
            baseline_batch_id=baseline_id,
        )
        logger.info(
            f"Created batch simulation with ID: {batch_id}"
            + (f" and baseline batch {baseline_id}" if baseline_id else "")
        )
        fights = [(batch_id, arena)] + ([(baseline_id, None)] if baseline_id else [])

        # Initialize state BEFORE starting thread so it's immediately available for progress polling
        with self.state_lock:
            self.batch_states[batch_id] = {
                "progress": 0,
                "completed_runs": 0,
                "failed_runs": 0,
                "total_runs": num_runs,
                "party_wins": 0,
                "monster_wins": 0,
                "total_rounds": 0,
                "total_party_hp_remaining": 0,
                "done": False,
                "error": None,
            }
            if baseline_id:
                self.batch_states[batch_id]["baseline"] = {
                    "batch_id": baseline_id,
                    "completed_runs": 0,
                    "failed_runs": 0,
                    "party_wins": 0,
                    "monster_wins": 0,
                    "total_rounds": 0,
                    "total_party_hp_remaining": 0,
                }

        logger.debug(f"Initialized batch state for batch_id={batch_id}")

        def tally(target_id: int) -> Dict[str, Any]:
            """The state's counters for one of the batches (the main one or its baseline)."""
            state = self.batch_states[batch_id]
            return state if target_id == batch_id else state["baseline"]

        def update_progress() -> None:
            state = self.batch_states[batch_id]
            processed = state["completed_runs"] + state["failed_runs"]
            if "baseline" in state:
                processed += (
                    state["baseline"]["completed_runs"]
                    + state["baseline"]["failed_runs"]
                )
            state["progress"] = (processed / (state["total_runs"] * len(fights))) * 100

        def run():
            try:
                logger.info(
                    f"Batch {batch_id} thread started, beginning {num_runs} simulations"
                )

                # Run simulations
                for run_number in range(1, num_runs + 1):
                    for target_id, fight_arena in fights:
                        logger.debug(
                            f"Batch {target_id}: Starting run {run_number}/{num_runs}"
                        )
                        try:
                            # Fresh Character and Monster objects each run, since combat changes HP,
                            # slots and buffs. Rebuilding from dicts is cheap; built objects are copied.
                            character_objects = build_party(
                                copy.deepcopy(party), self.spell_manager
                            )
                            monster_objects = build_monsters(copy.deepcopy(monsters))
                            combat = Combat(
                                character_objects + monster_objects, arena=fight_arena
                            )
                            result = combat.run()
                            logger.debug(
                                f"Batch {target_id} run {run_number}: winner={result.get('winner', 'unknown')}, rounds={result.get('rounds', 0)}"
                            )

                            # Save the simulation and its batch run row atomically
                            self.db.save_batch_run_result(
                                session_id, target_id, run_number, result
                            )

                            with self.state_lock:
                                counts = tally(target_id)
                                counts["completed_runs"] += 1
                                counts["total_rounds"] += result.get("rounds", 0)
                                counts["total_party_hp_remaining"] += result.get(
                                    "party_hp_remaining", 0
                                )
                                if result.get("winner") == "party":
                                    counts["party_wins"] += 1
                                else:
                                    counts["monster_wins"] += 1
                                update_progress()

                        except Exception as e:
                            logger.error(
                                f"Batch {target_id} run {run_number} failed with error: {e}",
                                exc_info=True,
                            )
                            log_exception(e)
                            with self.state_lock:
                                tally(target_id)["failed_runs"] += 1
                                update_progress()
                            # Continue with next run even if one fails
                            continue

                logger.info(
                    f"Batch {batch_id} completed all {num_runs} runs, finalizing statistics"
                )

                # Snapshot final statistics under the lock, but write them to the DB
                # outside it so progress polling and other batches aren't blocked on I/O
                with self.state_lock:
                    totals = [
                        (target_id, dict(tally(target_id))) for target_id, _ in fights
                    ]
                for target_id, counts in totals:
                    completed_runs = counts["completed_runs"]
                    avg_rounds = (
                        counts["total_rounds"] / completed_runs if completed_runs else 0
                    )
                    avg_party_hp = (
                        counts["total_party_hp_remaining"] / completed_runs
                        if completed_runs
                        else 0
                    )
                    logger.debug(f"Batch {target_id}: Updating database statistics")
                    self.db.update_batch_statistics(
                        target_id,
                        completed_runs,
                        counts["party_wins"],
                        counts["monster_wins"],
                        avg_rounds,
                        avg_party_hp,
                    )
                completed_runs, party_wins, monster_wins = (
                    totals[0][1]["completed_runs"],
                    totals[0][1]["party_wins"],
                    totals[0][1]["monster_wins"],
                )

                # Only mark done once the stats are in the DB, since the results page reads them from there
                with self.state_lock:
                    self.batch_states[batch_id]["done"] = True
                logger.info(
                    f"Batch {batch_id} COMPLETE: {completed_runs} runs, {party_wins} party wins, {monster_wins} monster wins"
                )

            except Exception as e:
                logger.error(
                    f"Batch {batch_id} thread failed with fatal error: {e}",
                    exc_info=True,
                )
                log_exception(e)
                # Don't raise in thread - store error in state instead
                with self.state_lock:
                    self.batch_states[batch_id] = {
                        "error": str(e),
                        "done": True,
                        "progress": 0,
                        "completed_runs": 0,
                        "failed_runs": 0,
                        "total_runs": num_runs,
                    }

        logger.debug(f"Batch {batch_id}: Starting background thread")
        t = threading.Thread(target=run)
        t.daemon = False  # Ensure thread is not daemon so it completes
        t.start()
        self.batch_threads[batch_id] = t
        logger.debug(f"Batch {batch_id}: Thread started, is_alive={t.is_alive()}")
        return batch_id

    def get_batch_progress(self, batch_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the current progress of a batch simulation, or None for a batch this controller
        didn't start (one from before a server restart).
        """
        with self.state_lock:
            state = self.batch_states.get(batch_id)
            if state is None:
                return None
            progress = dict(
                state
            )  # a copy, so callers can't change it or see it change
            if "baseline" in progress:
                progress["baseline"] = dict(progress["baseline"])
            return progress

    def get_batch_results(self, batch_id: int) -> Dict[str, Any]:
        """
        Get the final results of a batch simulation.
        """
        try:
            batch = self.db.get_batch_simulation(batch_id)
            if not batch:
                raise BatchSimulationError(f"Batch simulation {batch_id} not found")

            runs = self.db.get_batch_runs(batch_id)

            return {
                "batch": batch,
                "runs": runs,
                "statistics": self._statistics(batch),
                "comparison": self._comparison(batch),
            }
        except Exception as e:
            log_exception(e)
            raise BatchSimulationError(f"Failed to get batch results: {e}")

    @staticmethod
    def _statistics(batch: Dict[str, Any]) -> Dict[str, float]:
        total = batch["total_runs"]
        return {
            "win_rate": round(batch["party_wins"] / total * 100, 2) if total > 0 else 0,
            "loss_rate": (
                round(batch["monster_wins"] / total * 100, 2) if total > 0 else 0
            ),
            "average_rounds": round(batch["average_rounds"], 2),
            "average_party_hp_remaining": round(batch["average_party_hp_remaining"], 2),
        }

    def _comparison(self, batch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        For a batch run on an arena with a no-arena baseline (or for that baseline), the same
        statistics for both and the arena's effect on each. None for batches without a pair.
        """
        if batch.get("baseline_batch_id"):
            with_arena, without = batch, self.db.get_batch_simulation(
                batch["baseline_batch_id"]
            )
        else:
            with_arena, without = self.db.get_batch_with_baseline(batch["id"]), batch
        if not with_arena or not without:
            return None
        on, off = self._statistics(with_arena), self._statistics(without)
        rows = [
            (label, key, on[key], off[key], round(on[key] - off[key], 2))
            for label, key in (
                ("Party win rate (%)", "win_rate"),
                ("Average rounds", "average_rounds"),
                ("Average party HP remaining", "average_party_hp_remaining"),
            )
        ]
        return {
            "arena": with_arena.get("arena"),
            "arena_batch_id": with_arena["id"],
            "baseline_batch_id": without["id"],
            "rows": [
                {
                    "label": label,
                    "key": key,
                    "with_arena": a,
                    "without_arena": b,
                    "difference": d,
                }
                for label, key, a, b, d in rows
            ],
        }

    def get_batch_history(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Get batch simulation history for a session.
        """
        try:
            return self.db.get_batch_history(session_id)
        except Exception as e:
            log_exception(e)
            raise BatchSimulationError(f"Failed to get batch history: {e}")
