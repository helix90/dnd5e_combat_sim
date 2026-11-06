"""
Test-wide setup:
- logs go to a temporary folder rather than the app's logs/ folder;
- the database is a temporary file, so tests never write to data/app.db;
- errors in the AI fail tests rather than quietly fall back to Defend or Wait;
- each test gets the random generator back as it found it, so seeding in one test doesn't
  decide the dice of the tests after it;
- `client` is a test client for the app.
"""

import os
import random
import tempfile

import pytest

# Set before anything imports utils.logging, which opens the log file on import, or creates a
# DatabaseManager, which reads DATABASE_URL
os.environ.setdefault("LOG_DIR", tempfile.mkdtemp(prefix="dnd5e-test-logs-"))
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(
    tempfile.mkdtemp(prefix="dnd5e-test-db-"), "test.db"
)

from ai import errors  # noqa: E402

errors.RAISE_ERRORS = True


@pytest.fixture(autouse=True)
def restore_random_state():
    state = random.getstate()
    yield
    random.setstate(state)


@pytest.fixture
def client():
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client
