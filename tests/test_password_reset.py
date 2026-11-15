"""Resetting a forgotten password with a link sent by email: asking for it, the link working
once and for an hour, signing in with the new password, and the email's sending."""

import re
import threading
import time
import uuid
from unittest.mock import patch

import pytest

from app import app, public_url_for
from models import accounts, mailer
from models.db import DatabaseManager
from tests.helpers import session_id
from tests.test_accounts import PASSWORD, sign_in, sign_up, token

NEW_PASSWORD = "a brand new password"


@pytest.fixture
def email(monkeypatch):
    """A new account's email (the tests share one database), with sign_up and sign_in using it."""
    address = f"grace-{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setattr("tests.test_accounts.EMAIL", address)
    return address


class Outbox(list):
    """The emails sent, as (to, subject, body). They're sent off the request thread."""

    def __init__(self):
        super().__init__()
        self.arrived = threading.Event()

    def send(self, to, subject, body):
        self.append((to, subject, body))
        self.arrived.set()

    def wait(self, timeout=5):
        """The next email, once it's sent."""
        assert self.arrived.wait(timeout), "no email was sent"
        self.arrived.clear()
        return self[-1]


@pytest.fixture
def outbox(monkeypatch):
    sent = Outbox()
    monkeypatch.setattr(mailer, "send", sent.send)
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    return sent


def ask_for_link(client, email, address="127.0.0.1"):
    return client.post(
        "/password/forgot",
        data={"csrf_token": token(client, "/password/forgot"), "email": email},
        environ_overrides={"REMOTE_ADDR": address},
    )


def reset_link(client, email, outbox):
    ask_for_link(client, email)
    _, _, body = outbox.wait()
    return re.search(r"http://localhost(/password/reset/\S+)", body).group(1)


def reset(client, path, password=NEW_PASSWORD, confirm=None):
    return client.post(
        path,
        data={
            "csrf_token": token(client, "/password/forgot"),
            "password": password,
            "confirm_password": password if confirm is None else confirm,
        },
    )


def test_the_sign_in_page_links_to_resetting(client):
    page = client.get("/login").get_data(as_text=True)
    assert 'href="/password/forgot"' in page and "no reset by email" not in page


def test_a_reset_link_changes_the_password_and_signs_in(client, email, outbox):
    sign_up(app.test_client())
    phone = app.test_client()
    sign_in(phone)
    assert phone.get("/account").status_code == 200

    response = ask_for_link(client, email.upper())
    assert response.status_code == 200
    assert f"If an account uses <strong>{email}</strong>" in response.get_data(as_text=True)
    to, subject, body = outbox.wait()
    assert to == email and subject == "Reset your password"
    assert "within 60 minutes" in body
    path = re.search(r"http://localhost(/password/reset/\S+)", body).group(1)

    page = client.get(path)
    assert page.status_code == 200 and email in page.get_data(as_text=True)
    assert page.headers["Referrer-Policy"] == "no-referrer"

    response = reset(client, path)
    assert response.status_code == 302 and response.location.endswith("/account")
    assert session_id(client) == accounts.owner_key(DatabaseManager().get_user_by_email(email)["id"])
    assert client.get("/account").status_code == 200
    assert phone.get("/account").status_code == 302  # signed in with the old password
    assert sign_in(app.test_client()).status_code == 400
    assert sign_in(app.test_client(), password=NEW_PASSWORD).status_code == 302


def test_a_link_works_once(client, email, outbox):
    sign_up(app.test_client())
    path = reset_link(client, email, outbox)
    reset(client, path)
    again = app.test_client()
    response = reset(again, path, password="yet another password")
    assert response.status_code == 400
    assert "This link doesn't work any more" in response.get_data(as_text=True)
    assert sign_in(app.test_client(), password=NEW_PASSWORD).status_code == 302


def test_a_link_lasts_an_hour(client, email, outbox):
    sign_up(app.test_client())
    path = reset_link(client, email, outbox)
    later = time.time() + accounts.RESET_LINK_MAX_AGE_SECONDS + 1
    with patch("itsdangerous.timed.time.time", return_value=later):
        assert client.get(path).status_code == 400


def test_changing_the_password_another_way_ends_the_link(client, email, outbox):
    sign_up(client)
    path = reset_link(app.test_client(), email, outbox)
    client.post(
        "/account/password",
        data={
            "csrf_token": token(client, "/account"),
            "password": PASSWORD,
            "new_password": NEW_PASSWORD,
            "confirm_password": NEW_PASSWORD,
        },
    )
    assert app.test_client().get(path).status_code == 400


@pytest.mark.parametrize(
    "path",
    [
        "/password/reset/nonsense",
        "/password/reset/" + accounts.URLSafeTimedSerializer("another key", salt="password-reset").dumps([1, "x"]),
    ],
)
def test_made_up_links_dont_work(client, path):
    response = client.get(path)
    assert response.status_code == 400 and "Email me a new link" in response.get_data(as_text=True)


def test_an_unknown_email_gets_the_same_answer_and_no_email(client, outbox):
    response = ask_for_link(client, "nobody-here@example.com")
    assert response.status_code == 200
    assert "If an account uses <strong>nobody-here@example.com</strong>" in response.get_data(as_text=True)
    time.sleep(0.2)
    assert outbox == []


def test_new_password_problems_are_explained(client, email, outbox):
    sign_up(app.test_client())
    path = reset_link(client, email, outbox)
    for fields, problem in [
        ({"password": "short"}, "Use a password of at least 8 characters."),
        ({"confirm": "something else"}, "The passwords don&#39;t match."),
        ({"password": email}, "Use a password that isn&#39;t your email address."),
    ]:
        response = reset(client, path, **fields)
        assert response.status_code == 400 and problem in response.get_data(as_text=True)
    assert sign_in(app.test_client()).status_code == 302  # the password is unchanged


def test_forms_without_the_token_are_refused(client, email, outbox):
    sign_up(app.test_client())
    response = client.post("/password/forgot", data={"email": email})
    assert response.status_code == 400 and "The form expired" in response.get_data(as_text=True)
    path = reset_link(client, email, outbox)
    response = client.post(path, data={"password": NEW_PASSWORD, "confirm_password": NEW_PASSWORD})
    assert response.status_code == 400 and "The form expired" in response.get_data(as_text=True)


def test_links_use_the_public_address_not_the_requests_host(monkeypatch):
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)

    def link():
        with app.test_request_context(base_url="http://evil.example"):
            return public_url_for("password_reset", token="abc")

    assert link() == "http://evil.example/password/reset/abc"  # for development, with neither set
    monkeypatch.setenv("FLY_APP_NAME", "combat-sim")
    assert link() == "https://combat-sim.fly.dev/password/reset/abc"
    monkeypatch.setenv("PUBLIC_URL", "https://sim.example.com/")
    assert link() == "https://sim.example.com/password/reset/abc"


def test_asking_is_rate_limited_per_email(client, email, outbox):
    sign_up(app.test_client())
    # From different addresses, as someone flooding an inbox might send them
    for n in range(3):
        assert ask_for_link(app.test_client(), email, f"10.0.0.{n}").status_code == 200
    assert ask_for_link(app.test_client(), email, "10.0.0.9").status_code == 429
    # Another email isn't held up by this one's limit
    assert ask_for_link(app.test_client(), "someone-else@example.com", "10.0.0.9").status_code == 200


def test_asking_is_rate_limited_per_address(client, outbox):
    for n in range(3):
        assert ask_for_link(client, f"someone-{n}@example.com").status_code == 200
    assert ask_for_link(client, "someone-9@example.com").status_code == 429


def test_a_failed_send_is_logged_not_raised(email, caplog):
    import app as app_module

    with patch.object(mailer, "send", side_effect=OSError("connection refused")):
        app_module.send_reset_email(email, "http://localhost/password/reset/x")
    assert "Failed to send a password reset email: connection refused" in caplog.text


class TestMailer:
    def test_without_smtp_the_email_is_logged(self, monkeypatch, caplog):
        monkeypatch.delenv("SMTP_HOST", raising=False)
        with patch("smtplib.SMTP") as smtp:
            mailer.send("ada@example.com", "Hello", "the body")
        smtp.assert_not_called()
        assert "wasn't sent" in caplog.text and "the body" in caplog.text

    def test_starttls_and_login(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_USERNAME", "user")
        monkeypatch.setenv("SMTP_PASSWORD", "pass")
        monkeypatch.setenv("SMTP_FROM", "Sim <noreply@example.com>")
        monkeypatch.delenv("SMTP_PORT", raising=False)
        monkeypatch.delenv("SMTP_STARTTLS", raising=False)
        with patch("smtplib.SMTP") as smtp:
            mailer.send("ada@example.com", "Hello", "the body")
        smtp.assert_called_once_with("smtp.example.com", 587, timeout=mailer.SMTP_TIMEOUT_SECONDS)
        server = smtp.return_value
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("user", "pass")
        message = server.send_message.call_args.args[0]
        assert message["To"] == "ada@example.com" and message["From"] == "Sim <noreply@example.com>"
        assert message.get_content().strip() == "the body"

    def test_port_465_is_tls_from_the_start(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SMTP_PORT", "465")
        monkeypatch.delenv("SMTP_USERNAME", raising=False)
        with patch("smtplib.SMTP_SSL") as smtp_ssl:
            mailer.send("ada@example.com", "Hello", "the body")
        server = smtp_ssl.return_value
        server.starttls.assert_not_called()
        server.login.assert_not_called()
        server.send_message.assert_called_once()

    def test_starttls_can_be_skipped_for_a_local_server(self, monkeypatch):
        monkeypatch.setenv("SMTP_HOST", "localhost")
        monkeypatch.setenv("SMTP_PORT", "1025")
        monkeypatch.setenv("SMTP_STARTTLS", "false")
        with patch("smtplib.SMTP") as smtp:
            mailer.send("ada@example.com", "Hello", "the body")
        smtp.return_value.starttls.assert_not_called()
