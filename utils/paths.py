"""
Paths to the project's files, resolved from the project root rather than the working
directory, so the app finds its data wherever it is started from.
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")


def data_path(filename: str) -> str:
    """Absolute path of a file in the data directory."""
    return os.path.join(DATA_DIR, filename)
