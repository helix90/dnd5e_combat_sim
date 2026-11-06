import os
import tempfile
import pytest
from models.db import DatabaseManager, resolve_db_path, PROJECT_ROOT
from utils.exceptions import DatabaseError

def test_create_and_get_session(tmp_path):
    db = DatabaseManager(str(tmp_path / 'test.db'))
    assert db.create_session('test-session-1') is True
    # Creating it again updates the same row rather than failing or adding another
    assert db.create_session('test-session-1') is True
    with db._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions WHERE session_id = 'test-session-1'").fetchone()[0] == 1


def test_save_and_get_simulation(monkeypatch):
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    db = DatabaseManager(db_path)
    session_id = 'test-session-2'
    db.create_session(session_id)
    sim_id = db.save_simulation(session_id, 3, 'goblin', 'win', 4, 12)
    assert isinstance(sim_id, int)
    history = db.get_simulation_history(session_id)
    assert len(history) == 1
    assert history[0]['encounter_type'] == 'goblin'
    os.remove(db_path)

def test_save_and_get_combat_log(monkeypatch):
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    db = DatabaseManager(db_path)
    session_id = 'test-session-3'
    db.create_session(session_id)
    sim_id = db.save_simulation(session_id, 3, 'goblin', 'win', 4, 12)
    log_id = db.save_combat_log(sim_id, 1, 1, 'Hero', 'attack', 'Goblin', 'hit', 8)
    assert isinstance(log_id, int)
    logs = db.get_combat_logs(sim_id)
    assert len(logs) == 1
    assert logs[0]['character_name'] == 'Hero'
    os.remove(db_path) 

def test_create_session_preserves_party(tmp_path):
    db = DatabaseManager(str(tmp_path / 'test.db'))
    db.create_session('s1', selected_party_id=3)
    db.create_session('s1')  # callers without a party must not wipe it
    with db._get_connection() as conn:
        row = conn.execute("SELECT selected_party_id FROM sessions WHERE session_id = 's1'").fetchone()
    assert row['selected_party_id'] == 3
    db.create_session('s1', selected_party_id=5)
    with db._get_connection() as conn:
        row = conn.execute("SELECT selected_party_id FROM sessions WHERE session_id = 's1'").fetchone()
    assert row['selected_party_id'] == 5


def test_resolve_db_path(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    assert resolve_db_path() == os.path.join(PROJECT_ROOT, 'data', 'app.db')
    assert resolve_db_path('sqlite:////data/app.db') == '/data/app.db'
    assert resolve_db_path('sqlite:///x/y.db') == os.path.join(PROJECT_ROOT, 'x', 'y.db')
    monkeypatch.setenv('DATABASE_URL', 'sqlite:////tmp/env.db')
    assert resolve_db_path() == '/tmp/env.db'
    with pytest.raises(DatabaseError):
        resolve_db_path('postgresql://localhost/db')


def test_schema_loads_outside_repo_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = DatabaseManager(str(tmp_path / 'test.db'))
    assert db.create_session('s1')


def _result(winner='party', damage=5):
    return {
        'winner': winner, 'rounds': 3, 'party_hp_remaining': 10,
        'log': [{'type': 'action', 'actor': 'Hero', 'result': {'action': 'Attack', 'target': 'Goblin', 'hit': True, 'damage': damage}}],
    }


def test_last_simulation_id_uses_insert_order(tmp_path):
    db = DatabaseManager(str(tmp_path / 'test.db'))
    # Saved within the same second, so created_at ties; id must decide
    ids = [db.save_simulation('s1', 1, 'goblin', 'win', 1, 1) for _ in range(5)]
    assert db.get_last_simulation_id('s1') == ids[-1]
    assert [h['id'] for h in db.get_simulation_history('s1')] == ids[::-1]


def test_batch_runs_excluded_from_single_simulation_history(tmp_path):
    db = DatabaseManager(str(tmp_path / 'test.db'))
    single = db.save_simulation_result('s1', _result())
    batch_id = db.create_batch_simulation('s1', 'b', 1, 'custom')
    batch_sim = db.save_batch_run_result('s1', batch_id, 1, _result())
    assert batch_sim > single
    assert db.get_last_simulation_id('s1') == single
    assert [h['id'] for h in db.get_simulation_history('s1')] == [single]
    runs = db.get_batch_runs(batch_id)
    assert [r['simulation_id'] for r in runs] == [batch_sim]
    assert len(db.get_combat_logs(batch_sim)) == 1


def test_save_batch_run_result_is_atomic(tmp_path):
    db = DatabaseManager(str(tmp_path / 'test.db'))
    # Nonexistent batch_id violates the foreign key, so the run insert fails
    with pytest.raises(DatabaseError):
        db.save_batch_run_result('s1', 9999, 1, _result())
    with db._get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM simulations").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM combat_logs").fetchone()[0] == 0


def test_combat_log_tolerates_missing_damage_and_healing(tmp_path):
    db = DatabaseManager(str(tmp_path / 'test.db'))
    logs = db._convert_combat_log_format([
        {'type': 'action', 'actor': 'Hero', 'result': {'action': 'Attack', 'target': 'Goblin', 'hit': True, 'damage': None}},
        {'type': 'action', 'actor': 'Cleric', 'result': {'action': 'Cure Wounds', 'type': 'spell', 'target': 'Hero', 'healing': None}},
        {'type': 'action', 'actor': 'Wizard', 'result': {'action': 'Fireball', 'type': 'spell', 'target': ['A', 'B'], 'total_damage': None, 'damage': 7}},
    ])
    assert [l['damage'] for l in logs] == [0, 0, 7]
    assert logs[0]['result'] == 'Hit for 0 damage'


def test_init_sets_wal_and_drops_redundant_index(tmp_path):
    db = DatabaseManager(str(tmp_path / 'test.db'))
    with db._get_connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == 'wal'
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert 'idx_sessions_session_id' not in names
    assert 'idx_batch_runs_simulation_id' in names
