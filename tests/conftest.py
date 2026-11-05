"""Test-wide setup: log to a temporary folder rather than the app's logs/ folder, and let errors
in the AI fail tests rather than quietly fall back to Defend or Wait."""
import os
import tempfile

# Set before anything imports utils.logging, which opens the log file on import
os.environ.setdefault('LOG_DIR', tempfile.mkdtemp(prefix='dnd5e-test-logs-'))

from ai import errors  # noqa: E402

errors.RAISE_ERRORS = True
