import os
import sqlite3

def init_db(db_path='data/app.db', schema_path='db/schema.sql'):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    if not os.path.exists(db_path):
        print(f"Creating database at {db_path}")
        conn = sqlite3.connect(db_path)
        with open(schema_path, 'r') as f:
            conn.executescript(f.read())
        conn.close()
        print("Database initialized.")
    else:
        print("Database already exists. Skipping init.")

if __name__ == '__main__':
    init_db() 