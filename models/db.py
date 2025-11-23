import sqlite3
import os
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
import time
from utils.exceptions import DatabaseError
from utils.logging import log_exception

class DatabaseManager:
    """
    Manages SQLite database operations with optimized queries and connection pooling.
    """
    def __init__(self, db_path: str = "dnd5e_sim.db"):
        self.db_path = db_path
        self._ensure_db_directory()
        self._init_database()
        self._create_indexes()
    
    def _ensure_db_directory(self):
        """Ensure the database directory exists."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:  # Only create directory if there is a directory path
            os.makedirs(db_dir, exist_ok=True)
    
    def _init_database(self):
        """Initialize database with schema."""
        try:
            with self._get_connection() as conn:
                with open('db/schema.sql', 'r') as f:
                    conn.executescript(f.read())
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to initialize database: {e}")
    
    def _create_indexes(self):
        """Create performance indexes for common queries."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON sessions(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_simulations_session_id ON simulations(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_combat_logs_simulation_id ON combat_logs(simulation_id)",
            "CREATE INDEX IF NOT EXISTS idx_simulations_created_at ON simulations(created_at)",
        ]
        try:
            with self._get_connection() as conn:
                for index_sql in indexes:
                    conn.execute(index_sql)
        except Exception as e:
            log_exception(e)
            # Don't fail if indexes already exist
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with optimized settings."""
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row  # Enable dict-like access
        # Enable foreign keys and optimize for performance
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA cache_size = 10000")
        conn.execute("PRAGMA temp_store = MEMORY")
        try:
            yield conn
        finally:
            conn.close()
    
    def _log_slow_query(self, query: str, execution_time: float):
        """Log queries that take longer than 100ms."""
        # Disabled - slow query logging was too noisy
        pass
    
    def create_session(self, session_id: str, selected_party_id: Optional[int] = None) -> bool:
        """Create a new session with optimized query."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO sessions (session_id, selected_party_id) VALUES (?, ?)",
                    (session_id, selected_party_id)
                )
                conn.commit()
            self._log_slow_query("create_session", time.time() - start_time)
            return True
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to create session: {e}")
    
    def get_simulation(self, sim_id: int) -> Optional[Dict[str, Any]]:
        """Get simulation by ID with optimized query."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM simulations WHERE id = ?",
                    (sim_id,)
                )
                result = cursor.fetchone()
            self._log_slow_query("get_simulation", time.time() - start_time)
            return dict(result) if result else None
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to get simulation: {e}")
    
    def get_simulation_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get simulation history with optimized query and pagination."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT s.*, COUNT(cl.id) as log_count 
                    FROM simulations s 
                    LEFT JOIN combat_logs cl ON s.id = cl.simulation_id 
                    WHERE s.session_id = ? 
                    GROUP BY s.id 
                    ORDER BY s.created_at DESC 
                    LIMIT 50
                    """,
                    (session_id,)
                )
                results = [dict(row) for row in cursor.fetchall()]
            self._log_slow_query("get_simulation_history", time.time() - start_time)
            return results
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to get simulation history: {e}")

    def get_last_simulation_id(self, session_id: str) -> Optional[int]:
        """Get the most recent simulation ID for a session."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id FROM simulations 
                    WHERE session_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 1
                    """,
                    (session_id,)
                )
                result = cursor.fetchone()
            self._log_slow_query("get_last_simulation_id", time.time() - start_time)
            
            return result['id'] if result else None
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to get last simulation ID: {e}")

    def _convert_combat_log_format(self, logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert combat log from simulation format to database format."""
        converted_logs = []
        action_order = 0
        current_round = 1
        
        for log_entry in logs:
            if log_entry.get('type') == 'round_start':
                current_round = log_entry.get('round', current_round)
                continue
            elif log_entry.get('type') == 'action':
                actor = log_entry.get('actor', 'Unknown')
                result = log_entry.get('result', {})
                
                # Extract action information
                action_type = 'attack'  # Default
                target = ''
                damage = 0
                result_text = ''
                
                # Get target from result
                target = result.get('target', '')
                
                # Determine action type and damage
                if 'action' in result:
                    action_name = result.get('action', '')

                    # Convert Action object to string if needed
                    if hasattr(action_name, 'name'):
                        # It's an Action object, use its name attribute
                        action_name_str = action_name.name
                    else:
                        # It's already a string
                        action_name_str = str(action_name) if action_name else ''

                    # Determine action type based on action name or other indicators
                    if 'attack' in action_name_str.lower() or result.get('hit') is not None:
                        action_type = 'attack'
                    elif 'spell' in result or 'cast' in action_name_str.lower():
                        action_type = 'spell'
                    elif 'defend' in action_name_str.lower() or 'dodge' in action_name_str.lower():
                        action_type = 'defend'
                    elif 'wait' in action_name_str.lower():
                        action_type = 'wait'
                    else:
                        action_type = 'special'
                    
                    # Extract damage
                    damage = result.get('damage', 0)
                    
                    # Build result text
                    if action_type == 'attack':
                        if result.get('hit', False):
                            if damage > 0:
                                result_text = f"Hit for {damage} damage"
                            else:
                                result_text = "Hit for 0 damage"
                        else:
                            result_text = "Miss"
                    elif action_type == 'spell':
                        if result.get('healing', 0) > 0:
                            healing = result.get('healing', 0)
                            result_text = f"Heals {healing} HP"
                            damage = -healing  # Negative for healing
                        else:
                            result_text = f"Spell cast on {target}"
                            if damage > 0:
                                result_text += f": {damage} damage"
                    elif action_type == 'defend':
                        result_text = "Takes defensive stance"
                    elif action_type == 'wait':
                        result_text = "Takes no action"
                    else:
                        result_text = f"{action_name_str} on {target}"
                        if damage > 0:
                            result_text += f": {damage} damage"
                
                converted_logs.append({
                    'round_number': current_round,
                    'action_order': action_order,
                    'character_name': actor,
                    'action_type': action_type,
                    'target': target,
                    'result': result_text,
                    'damage': damage
                })
                action_order += 1
        
        return converted_logs

    def save_simulation_result(self, session_id: str, result: Dict[str, Any]) -> int:
        """Save simulation result with optimized batch insert."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                # Insert simulation
                cursor = conn.execute(
                    """
                    INSERT INTO simulations (session_id, party_level, encounter_type, result, rounds, party_hp_remaining)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        result.get('party_level', 1),
                        result.get('encounter_type', 'custom'),
                        str(result.get('winner', 'unknown')),
                        result.get('rounds', 0),
                        result.get('party_hp_remaining', 0)
                    )
                )
                sim_id = cursor.lastrowid
                
                # Convert and batch insert combat logs
                logs = result.get('log', [])
                if logs:
                    converted_logs = self._convert_combat_log_format(logs)
                    log_data = [
                        (sim_id, log.get('round_number', 0), log.get('action_order', 0),
                         log.get('character_name', ''), log.get('action_type', ''),
                         log.get('target', ''), str(log.get('result', '')), log.get('damage', 0))
                        for log in converted_logs
                    ]
                    conn.executemany(
                        """
                        INSERT INTO combat_logs 
                        (simulation_id, round_number, action_order, character_name, action_type, target, result, damage)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        log_data
                    )
                
                conn.commit()
            self._log_slow_query("save_simulation_result", time.time() - start_time)
            return sim_id
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to save simulation result: {e}")
    
    def cleanup_old_sessions(self, days_old: int = 7) -> int:
        """Clean up old sessions and related data."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                # Delete old sessions and related data
                cursor = conn.execute(
                    """
                    DELETE FROM sessions 
                    WHERE created_at < datetime('now', '-{} days')
                    """.format(days_old)
                )
                deleted_count = cursor.rowcount
                conn.commit()
            self._log_slow_query("cleanup_old_sessions", time.time() - start_time)
            return deleted_count
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to cleanup old sessions: {e}")
    
    def get_combat_logs(self, sim_id: int) -> List[Dict[str, Any]]:
        """Get combat logs for a specific simulation."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM combat_logs 
                    WHERE simulation_id = ? 
                    ORDER BY round_number, action_order
                    """,
                    (sim_id,)
                )
                results = [dict(row) for row in cursor.fetchall()]
            self._log_slow_query("get_combat_logs", time.time() - start_time)
            return results
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to get combat logs: {e}")

    def save_combat_log(self, sim_id: int, round_number: int, action_order: int, character_name: str, action_type: str, target: str, result: str, damage: int) -> int:
        """Legacy method for backward compatibility with tests."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO combat_logs (simulation_id, round_number, action_order, character_name, action_type, target, result, damage)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sim_id, round_number, action_order, character_name, action_type, target, result, damage)
                )
                log_id = cursor.lastrowid
                conn.commit()
            self._log_slow_query("save_combat_log", time.time() - start_time)
            return log_id
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to save combat log: {e}")

    def save_simulation(self, session_id: str, party_level: int, encounter_type: str, result: str, rounds: int, party_hp_remaining: int) -> int:
        """Legacy method for backward compatibility with tests."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO simulations (session_id, party_level, encounter_type, result, rounds, party_hp_remaining)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, party_level, encounter_type, result, rounds, party_hp_remaining)
                )
                sim_id = cursor.lastrowid
                conn.commit()
            self._log_slow_query("save_simulation", time.time() - start_time)
            return sim_id
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to save simulation: {e}")

    def create_batch_simulation(self, session_id: str, batch_name: str, party_level: int, encounter_type: str) -> int:
        """Create a new batch simulation record."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO batch_simulations (session_id, batch_name, party_level, encounter_type, total_runs, party_wins, monster_wins, average_rounds, average_party_hp_remaining)
                    VALUES (?, ?, ?, ?, 0, 0, 0, 0.0, 0.0)
                    """,
                    (session_id, batch_name, party_level, encounter_type)
                )
                batch_id = cursor.lastrowid
                conn.commit()
            self._log_slow_query("create_batch_simulation", time.time() - start_time)
            return batch_id
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to create batch simulation: {e}")

    def add_batch_run(self, batch_id: int, simulation_id: int, run_number: int, result: str, rounds: int, party_hp_remaining: int) -> int:
        """Add a single run to a batch simulation."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO batch_simulation_runs (batch_id, simulation_id, run_number, result, rounds, party_hp_remaining)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (batch_id, simulation_id, run_number, result, rounds, party_hp_remaining)
                )
                run_id = cursor.lastrowid
                conn.commit()
            self._log_slow_query("add_batch_run", time.time() - start_time)
            return run_id
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to add batch run: {e}")

    def update_batch_statistics(self, batch_id: int, total_runs: int, party_wins: int, monster_wins: int, average_rounds: float, average_party_hp_remaining: float) -> bool:
        """Update batch simulation statistics."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE batch_simulations 
                    SET total_runs = ?, party_wins = ?, monster_wins = ?, average_rounds = ?, average_party_hp_remaining = ?
                    WHERE id = ?
                    """,
                    (total_runs, party_wins, monster_wins, average_rounds, average_party_hp_remaining, batch_id)
                )
                conn.commit()
            self._log_slow_query("update_batch_statistics", time.time() - start_time)
            return True
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to update batch statistics: {e}")

    def get_batch_simulation(self, batch_id: int) -> Optional[Dict[str, Any]]:
        """Get batch simulation by ID."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM batch_simulations WHERE id = ?",
                    (batch_id,)
                )
                result = cursor.fetchone()
            self._log_slow_query("get_batch_simulation", time.time() - start_time)
            return dict(result) if result else None
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to get batch simulation: {e}")

    def get_batch_runs(self, batch_id: int) -> List[Dict[str, Any]]:
        """Get all runs for a batch simulation."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT bsr.*, s.encounter_type 
                    FROM batch_simulation_runs bsr
                    JOIN simulations s ON bsr.simulation_id = s.id
                    WHERE bsr.batch_id = ?
                    ORDER BY bsr.run_number
                    """,
                    (batch_id,)
                )
                results = [dict(row) for row in cursor.fetchall()]
            self._log_slow_query("get_batch_runs", time.time() - start_time)
            return results
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to get batch runs: {e}")

    def get_batch_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get batch simulation history for a session."""
        try:
            start_time = time.time()
            with self._get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM batch_simulations 
                    WHERE session_id = ? 
                    ORDER BY created_at DESC 
                    LIMIT 50
                    """,
                    (session_id,)
                )
                results = [dict(row) for row in cursor.fetchall()]
            self._log_slow_query("get_batch_history", time.time() - start_time)
            return results
        except Exception as e:
            log_exception(e)
            raise DatabaseError(f"Failed to get batch history: {e}") 