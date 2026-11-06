import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db import DatabaseManager, resolve_db_path


def init_db(db_path=None):
    """Create the database (if needed) and apply the schema at DATABASE_URL."""
    db_path = db_path or resolve_db_path()
    DatabaseManager(db_path)
    print(f"Database ready at {db_path}")


if __name__ == "__main__":
    init_db()
