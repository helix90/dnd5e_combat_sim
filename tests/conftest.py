"""Test-wide setup: log to a temporary folder rather than the app's logs/ folder."""
import os
import tempfile

# Set before anything imports utils.logging, which opens the log file on import
os.environ.setdefault('LOG_DIR', tempfile.mkdtemp(prefix='dnd5e-test-logs-'))
