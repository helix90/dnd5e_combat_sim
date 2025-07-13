import os
import tempfile
import pytest
from models.db import DatabaseManager

def dbm():
    # Use a temporary file for the test DB
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    db = DatabaseManager(db_path)
    yield db
    os.remove(db_path)

def test_create_and_get_session(monkeypatch):
    db_fd, db_path = tempfile.mkstemp()
    os.close(db_fd)
    db = DatabaseManager(db_path)
    session_id = 'test-session-1'
    rowid = db.create_session(session_id)
    assert isinstance(rowid, int)
    # Creating again should not error
    rowid2 = db.create_session(session_id)
    assert rowid2 == 0 or isinstance(rowid2, int)
    os.remove(db_path)

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