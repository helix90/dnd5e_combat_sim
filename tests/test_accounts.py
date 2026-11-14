"""Accounts with an email and password: signing up and in, a visitor's history moving into their
account, signing out, changing the password, and deleting the account."""

import re
import threading
import time
import uuid
from unittest.mock import patch

import pytest

from app import app, safe_next
from models.accounts import owner_key, password_problem
from models.combat import Combat
from models.db import DatabaseManager
from tests.helpers import run_simulation, session_id

PASSWORD = "correct horse battery"
EMAIL = "ada@example.com"


@pytest.fixture(autouse=True)
def fresh_email():
    """Each test's own email: the tests share one database, and an email has one account."""
    global EMAIL
    EMAIL = f"ada-{uuid.uuid4().hex[:8]}@example.com"


def token(client, page="/login"):
    html = client.get(page).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def sign_up(client, email=None, password=PASSWORD, confirm=None, **extra):
    return client.post(
        "/signup",
        data={
            "csrf_token": token(client, "/signup"),
            "email": EMAIL if email is None else email,
            "password": password,
            "confirm_password": password if confirm is None else confirm,
            **extra,
        },
    )


def sign_in(client, email=None, password=PASSWORD, **extra):
    return client.post(
        "/login",
        data={
            "csrf_token": token(client),
            "email": EMAIL if email is None else email,
            "password": password,
            **extra,
        },
    )


def choose_fight(client):
    client.post("/party", data={"party_id": "1", "party_level": "1"})
    client.post(
        "/encounter/prebuilt",
        json={"template_name": "Goblin Ambush", "party_level": 1, "party_size": 4},
    )


def wait_for(client, batch_id):
    deadline = time.time() + 60
    while not client.get(f"/batch/progress/{batch_id}").get_json().get("done"):
        assert time.time() < deadline, "batch did not finish"
        time.sleep(0.05)


def user_id():
    return DatabaseManager().get_user_by_email(EMAIL)["id"]


def test_signing_up_signs_in_and_brings_the_browsers_history(client):
    choose_fight(client)
    fight = run_simulation(client)["simulation_id"]
    response = sign_up(client, email=f"  {EMAIL.upper()} ", next="/history")
    assert response.status_code == 302 and response.location.endswith("/history")

    db = DatabaseManager()
    user = db.get_user_by_email(EMAIL)
    assert user["email"] == EMAIL  # trimmed and lower-cased
    assert user["password_hash"].startswith("scrypt:") and PASSWORD not in user["password_hash"]
    assert session_id(client) == owner_key(user["id"])
    assert db.get_simulation(fight)["session_id"] == owner_key(user["id"])

    page = client.get("/history").get_data(as_text=True)
    assert "Your fights and batches from this browser are in it." in page
    assert EMAIL in page and "Sign out" in page
    assert f'/results?sim_id={fight}"' in page
    # The party and encounter chosen before signing up are still chosen
    assert "Goblin Ambush" in client.get("/batch").get_data(as_text=True)


@pytest.mark.parametrize(
    "fields, problem",
    [
        ({"email": "not-an-email"}, "That doesn&#39;t look like an email address."),
        ({"email": ""}, "Enter your email address."),
        ({"password": "short"}, "Use a password of at least 8 characters."),
        ({"confirm": "something else"}, "The passwords don&#39;t match."),
    ],
)
def test_sign_up_problems_are_explained(client, fields, problem):
    response = sign_up(client, **fields)
    assert response.status_code == 400
    assert problem in response.get_data(as_text=True)
    assert not DatabaseManager().get_user_by_email(fields.get("email", EMAIL) or "x")


def test_an_email_has_one_account(client):
    sign_up(client)
    response = sign_up(app.test_client(), email=EMAIL.upper())
    assert response.status_code == 400
    assert "An account with that email already exists" in response.get_data(as_text=True)


def test_a_password_isnt_the_email():
    assert password_problem("ada@example.com", "ada@example.com")
    assert password_problem("x" * 129)
    assert password_problem(PASSWORD, "ada@example.com") is None


def test_forms_without_the_sessions_token_are_refused(client):
    response = client.post(
        "/signup",
        data={"email": EMAIL, "password": PASSWORD, "confirm_password": PASSWORD},
    )
    assert response.status_code == 400 and "The form expired" in response.get_data(as_text=True)
    assert not DatabaseManager().get_user_by_email(EMAIL)


def test_a_wrong_password_and_an_unknown_email_get_the_same_answer(client):
    sign_up(client)
    client.post("/logout", data={"csrf_token": token(client, "/")})
    wrong = sign_in(client, password="not the password")
    unknown = sign_in(client, email="nobody@example.com")
    for response in (wrong, unknown):
        assert response.status_code == 400
        assert "That email and password don&#39;t match." in response.get_data(as_text=True)


def test_signing_in_on_another_device_shows_the_same_history(client):
    sign_up(client)
    choose_fight(client)
    fight = run_simulation(client)["simulation_id"]

    laptop = app.test_client()
    laptop.get("/")
    choose_fight(laptop)
    laptop_fight = run_simulation(laptop)["simulation_id"]
    assert sign_in(laptop).status_code == 302
    page = laptop.get("/history").get_data(as_text=True)
    assert f"sim_id={fight}" in page and f"sim_id={laptop_fight}" in page
    assert "now in your account" in page
    assert f"sim_id={laptop_fight}" in client.get("/history").get_data(as_text=True)


def test_signing_out_starts_a_new_anonymous_visitor(client):
    sign_up(client)
    choose_fight(client)
    fight = run_simulation(client)["simulation_id"]
    response = client.post("/logout", data={"csrf_token": token(client, "/")})
    assert response.status_code == 302
    client.get("/")
    assert not session_id(client).startswith("user:")
    page = client.get("/history").get_data(as_text=True)
    assert f"sim_id={fight}" not in page and "Sign in" in page
    assert client.get(f"/results?sim_id={fight}").status_code == 404


def test_signing_out_needs_the_token(client):
    sign_up(client)
    client.post("/logout", data={})
    assert client.get("/account").status_code == 200  # still signed in


def test_changing_the_password_signs_out_other_browsers(client):
    sign_up(client)
    phone = app.test_client()
    sign_in(phone)
    assert phone.get("/account").status_code == 200

    response = client.post(
        "/account/password",
        data={
            "csrf_token": token(client, "/account"),
            "password": PASSWORD,
            "new_password": "a new long password",
            "confirm_password": "a new long password",
        },
    )
    assert response.status_code == 302
    assert client.get("/account").status_code == 200  # this browser stays signed in
    assert phone.get("/account").status_code == 302  # the other is signed out
    assert not session_id(phone).startswith("user:")

    other = app.test_client()
    assert sign_in(other).status_code == 400
    assert sign_in(other, password="a new long password").status_code == 302


def test_changing_the_password_needs_the_current_one(client):
    sign_up(client)
    response = client.post(
        "/account/password",
        data={
            "csrf_token": token(client, "/account"),
            "password": "wrong",
            "new_password": "a new long password",
            "confirm_password": "a new long password",
        },
    )
    assert response.status_code == 400
    assert "Your current password isn&#39;t right." in response.get_data(as_text=True)


def test_deleting_the_account_deletes_its_history(client):
    sign_up(client)
    choose_fight(client)
    fight = run_simulation(client)["simulation_id"]
    batch_id = client.post("/batch/start", json={"num_runs": 2}).get_json()["batch_id"]
    wait_for(client, batch_id)
    account = user_id()

    wrong = client.post(
        "/account/delete",
        data={"csrf_token": token(client, "/account"), "password": "wrong"},
    )
    assert wrong.status_code == 400 and DatabaseManager().get_user(account)

    response = client.post(
        "/account/delete",
        data={"csrf_token": token(client, "/account"), "password": PASSWORD},
    )
    assert response.status_code == 302
    db = DatabaseManager()
    assert db.get_user(account) is None
    assert db.get_simulation(fight) is None and db.get_batch_simulation(batch_id) is None
    assert sign_in(app.test_client()).status_code == 400


def test_a_batch_running_while_its_visitor_signs_in_finishes_in_their_account(client):
    choose_fight(client)
    release = threading.Event()
    real_run = Combat.run

    def held_run(self):
        release.wait(30)
        return real_run(self)

    with patch("models.combat.Combat.run", held_run):
        batch_id = client.post("/batch/start", json={"num_runs": 3}).get_json()["batch_id"]
        sign_up(client)
        release.set()
        wait_for(client, batch_id)
    db = DatabaseManager()
    owner = owner_key(user_id())
    assert db.get_batch_simulation(batch_id)["session_id"] == owner
    runs = db.get_batch_runs(batch_id)
    assert len(runs) == 3
    assert {db.get_simulation(r["simulation_id"])["session_id"] for r in runs} == {owner}
    assert client.get(f"/results?sim_id={runs[0]['simulation_id']}").status_code == 200


def test_the_account_page_needs_signing_in(client):
    response = client.get("/account")
    assert response.status_code == 302 and "/login?next=/account" in response.location


def test_after_signing_in_only_this_sites_pages(client):
    assert safe_next("/history?tab=batches") == "/history?tab=batches"
    with app.test_request_context():
        for target in ("//evil.example", "https://evil.example", "/\\evil.example", None, ""):
            assert safe_next(target) == "/"


def test_signing_in_is_rate_limited(client):
    for _ in range(10):
        sign_in(client, password="guess")
    response = sign_in(client, password="guess")
    assert response.status_code == 429
