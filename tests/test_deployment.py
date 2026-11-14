"""The Docker image builds, the health check answers, and the app is set up for Fly.io. (How the app reads SECRET_KEY is tested
in test_app_fixes.py.)"""

import json
import os
import shutil
import subprocess
import sys
import time
import tomllib

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = "dnd5e-combat-sim:test"


@pytest.mark.slow
def test_docker_build():
    """
    The Docker image builds with none of the local files left out of it, and its HEALTHCHECK
    passes against the running app, which runs as appuser with its database on a volume. Skipped without Docker, or without access to its daemon.
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
    # The database on a volume owned by root, as Fly.io mounts one
    container = docker(
        "run",
        "-d",
        "-e",
        "SECRET_KEY=test",
        "-e",
        "DATABASE_URL=sqlite:////data/app.db",
        "-v",
        "/data",
        IMAGE,
    ).stdout.strip()
    try:
        for _ in range(30):
            healthy = docker("exec", container, *check[1:], check=False)
            if healthy.returncode == 0:
                break
            time.sleep(1)
        assert healthy.returncode == 0, healthy.stdout + healthy.stderr

        # The app runs as appuser, and could create its database on the volume
        owners = docker(
            "exec", container, "stat", "-c", "%U", "/proc/1", "/data/app.db"
        ).stdout.split()
        assert owners == ["appuser", "appuser"]
    finally:
        docker("rm", "-f", "-v", container)


def docker(*args, check=True):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_healthz_endpoint(client):
    rv = client.get("/healthz")
    assert rv.status_code == 200
    assert rv.data.strip() == b"ok"


# Fly.io


def run_app(env, code):
    """Run code in a fresh Python that imports the app with these environment variables."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("SECRET_KEY", "FLASK_SECRET_KEY", "FLY_APP_NAME", "TRUSTED_PROXIES")
    } | env
    return subprocess.run(
        [sys.executable, "-c", "from app import app\n" + code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


VISITOR_ADDRESS = """
from flask import request
app.add_url_rule("/address", "address", lambda: request.remote_addr)
headers = {"X-Forwarded-For": "203.0.113.9, 198.51.100.7"}
print(app.test_client().get("/address", headers=headers).get_data(as_text=True))
"""


@pytest.mark.parametrize(
    "env, address",
    [
        # Fly.io's proxy adds the visitor's address last; whatever came before, they could forge
        ({"FLY_APP_NAME": "sim", "SECRET_KEY": "s"}, "198.51.100.7"),
        ({"TRUSTED_PROXIES": "2"}, "203.0.113.9"),
        # With no proxy in front, X-Forwarded-For is the visitor's own say-so: ignored
        ({}, "127.0.0.1"),
    ],
)
def test_visitors_are_told_apart_behind_a_proxy(env, address):
    result = run_app(env, VISITOR_ADDRESS)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == address


def test_on_fly_the_app_will_not_start_with_the_default_secret_key():
    result = run_app({"FLY_APP_NAME": "sim"}, "")
    assert result.returncode != 0
    assert "fly secrets set SECRET_KEY" in result.stderr


def test_fly_toml_keeps_one_machine_running_with_the_database_on_its_volume():
    with open(os.path.join(ROOT, "fly.toml"), "rb") as f:
        config = tomllib.load(f)
    service = config["http_service"]
    assert service["auto_stop_machines"] == "off" and service["min_machines_running"] == 1
    assert service["internal_port"] == 5000
    assert service["checks"][0]["path"] == "/healthz"
    database = config["env"]["DATABASE_URL"]
    assert database.startswith("sqlite:///" + config["mounts"][0]["destination"] + "/")
    assert "SECRET_KEY" not in config["env"]
