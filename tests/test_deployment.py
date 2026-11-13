"""The Docker image builds, and the health check answers. (How the app reads SECRET_KEY is tested
in test_app_fixes.py.)"""

import json
import shutil
import subprocess
import time

import pytest

IMAGE = "dnd5e-combat-sim:test"


@pytest.mark.slow
def test_docker_build():
    """
    The Docker image builds with none of the local files left out of it, and its HEALTHCHECK
    passes against the running app. Skipped without Docker, or without access to its daemon.
    """
    if not shutil.which("docker"):
        pytest.skip("Docker not available")
    if docker("info", check=False).returncode != 0:
        pytest.skip("Can't reach the Docker daemon (not in the docker group?)")
    result = subprocess.run(
        ["docker", "build", "--no-cache", "-t", IMAGE, "."],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    # .dockerignore keeps local environments, history, logs and databases out of the image
    leftovers = docker(
        "run",
        "--rm",
        "--entrypoint",
        "sh",
        IMAGE,
        "-c",
        "for f in .git .venv .claude logs data/app.db; do [ -e /app/$f ] && echo $f; done; true",
    )
    assert leftovers.stdout.split() == []

    # The image's own HEALTHCHECK passes against the running app
    check = json.loads(
        docker(
            "image", "inspect", "-f", "{{json .Config.Healthcheck.Test}}", IMAGE
        ).stdout
    )
    assert check[0] == "CMD"  # exec form: no shell needed
    container = docker("run", "-d", "-e", "SECRET_KEY=test", IMAGE).stdout.strip()
    try:
        for _ in range(30):
            healthy = docker("exec", container, *check[1:], check=False)
            if healthy.returncode == 0:
                break
            time.sleep(1)
        assert healthy.returncode == 0, healthy.stdout + healthy.stderr
    finally:
        docker("rm", "-f", container)


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_healthz_endpoint(client):
    rv = client.get("/healthz")
    assert rv.status_code == 200
    assert rv.data.strip() == b"ok"
