"""The Docker image builds, and the health check answers. (How the app reads SECRET_KEY is tested
in test_app_fixes.py.)"""
import shutil
import subprocess

import pytest


@pytest.mark.slow
def test_docker_build():
    """The Docker image builds. Skipped without Docker."""
    if not shutil.which('docker'):
        pytest.skip('Docker not available')
    result = subprocess.run(['docker', 'build', '--no-cache', '-t', 'dnd5e-combat-sim:test', '.'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_healthz_endpoint(client):
    rv = client.get('/healthz')
    assert rv.status_code == 200
    assert rv.data.strip() == b'ok'
