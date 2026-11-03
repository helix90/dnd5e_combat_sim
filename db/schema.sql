-- D&D 5e Combat Simulator database schema (SQLite)
-- Executed on every DatabaseManager init, so all statements must be idempotent.

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    selected_party_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- session_id is intentionally not a foreign key: sessions are upserted with
-- INSERT OR REPLACE and pruned by cleanup_old_sessions, neither of which
-- should disturb saved simulation history.
CREATE TABLE IF NOT EXISTS simulations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    party_level INTEGER,
    encounter_type TEXT,
    result TEXT,
    rounds INTEGER DEFAULT 0,
    party_hp_remaining INTEGER DEFAULT 0,
    arena TEXT,  -- map name, NULL for a fight without an arena
    replay BLOB,  -- zlib-compressed JSON battle-map replay (fights on an arena only)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS combat_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id INTEGER NOT NULL,
    round_number INTEGER DEFAULT 0,
    action_order INTEGER DEFAULT 0,
    character_name TEXT,
    action_type TEXT,
    target TEXT,
    result TEXT,
    damage INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (simulation_id) REFERENCES simulations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS batch_simulations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    batch_name TEXT,
    party_level INTEGER,
    encounter_type TEXT,
    total_runs INTEGER DEFAULT 0,
    party_wins INTEGER DEFAULT 0,
    monster_wins INTEGER DEFAULT 0,
    average_rounds REAL DEFAULT 0.0,
    average_party_hp_remaining REAL DEFAULT 0.0,
    arena TEXT,  -- map name, NULL for batches without an arena
    baseline_batch_id INTEGER,  -- the same encounter run without the arena, for comparison
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS batch_simulation_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL,
    simulation_id INTEGER NOT NULL,
    run_number INTEGER,
    result TEXT,
    rounds INTEGER DEFAULT 0,
    party_hp_remaining INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (batch_id) REFERENCES batch_simulations(id) ON DELETE CASCADE,
    FOREIGN KEY (simulation_id) REFERENCES simulations(id) ON DELETE CASCADE
);
