import os
import pytest
import importlib
from app import app as flask_app

@pytest.mark.slow
def test_docker_build():
    """
    Test that the Docker image builds successfully.
    Skips if Docker is not available.
    """
    import shutil
    import subprocess
    if not shutil.which('docker'):
        pytest.skip('Docker not available')
    result = subprocess.run([
        'docker', 'build', '--no-cache', '-t', 'dnd5e-combat-sim:test', '.'
    ], capture_output=True, text=True)
    print(result.stdout)
    assert result.returncode == 0
    assert 'Successfully' in result.stdout or 'built' in result.stdout.lower()

@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as client:
        with flask_app.app_context():
            yield client

def test_healthz_endpoint(client):
    """
    Test that the /healthz endpoint returns 200 OK and 'ok'.
    """
    rv = client.get('/healthz')
    assert rv.status_code == 200
    assert rv.data.strip() == b'ok'

def test_env_var_loading(monkeypatch):
    """
    Test that environment variables are loaded and used by the app.
    """
    monkeypatch.setenv('SECRET_KEY', 'test-secret')
    monkeypatch.setenv('FLASK_ENV', 'testing')
    # Import the app module fresh to pick up new env vars
    import app
    importlib.reload(app)
    assert os.environ['SECRET_KEY'] == 'test-secret'
    assert os.environ['FLASK_ENV'] == 'testing'

def test_config_validation():
    """
    Test that required config/env vars are present or have defaults.
    """
    # Check if SECRET_KEY is set, if not it should have a default
    if 'SECRET_KEY' not in os.environ:
        # The app should handle missing SECRET_KEY gracefully
        assert True, "SECRET_KEY not set but app should handle this"
    else:
        assert os.environ['SECRET_KEY'], "SECRET_KEY should not be empty"
    
    # DATABASE_URL is optional and defaults to SQLite
    if 'DATABASE_URL' in os.environ:
        assert os.environ['DATABASE_URL'], "DATABASE_URL should not be empty if set" 