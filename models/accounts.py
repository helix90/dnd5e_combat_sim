"""
Accounts: checking emails and passwords, hashing passwords, password reset links, and the keys that tie a signed-in
visitor's session and history to their account.
"""

import hashlib
import hmac
import re
from typing import Any, Callable, Dict, Optional

from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

MAX_EMAIL_LENGTH = 254
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def email_problem(email: str) -> Optional[str]:
    """Why an (already normalized) email can't be used, or None."""
    if not email:
        return "Enter your email address."
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(email):
        return "That doesn't look like an email address."
    return None


def password_problem(password: str, email: str = "") -> Optional[str]:
    """Why a new password can't be used, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use a password of at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Use a password of at most {MAX_PASSWORD_LENGTH} characters."
    if email and password.strip().lower() == email:
        return "Use a password that isn't your email address."
    return None


def hash_password(password: str) -> str:
    return generate_password_hash(password, method="scrypt")


def password_matches(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


# Checked against when a visitor signs in with an unknown email, so that takes as long as a
# wrong password and the time doesn't tell which emails have accounts
DUMMY_HASH = hash_password("not anyone's password")


def owner_key(user_id: int) -> str:
    """What a signed-in visitor's history is saved under, in place of a session's id."""
    return f"user:{user_id}"


def session_token(secret_key: str, user_id: int, password_hash: str) -> str:
    """
    Kept in a signed-in session and checked on every request: it changes when the password
    does, which signs out every other browser. (A digest, as the session cookie is signed but
    readable, so it mustn't hold the hash itself.)
    """
    message = f"{user_id}:{password_hash}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


RESET_LINK_MAX_AGE_SECONDS = 3600
RESET_SALT = "password-reset"


def reset_token(secret_key: str, user: Dict[str, Any]) -> str:
    """
    The token in a password reset link: signed, and good for an hour and one reset, as it
    names the password it replaces, which the reset changes.
    """
    return URLSafeTimedSerializer(secret_key, salt=RESET_SALT).dumps(
        [user["id"], _reset_fingerprint(secret_key, user)]
    )


def reset_user(
    secret_key: str, token: str, get_user: Callable[[int], Any]
) -> Optional[Dict[str, Any]]:
    """The account a reset link's token is for, or None if it's forged, expired or used."""
    try:
        user_id, fingerprint = URLSafeTimedSerializer(secret_key, salt=RESET_SALT).loads(
            token, max_age=RESET_LINK_MAX_AGE_SECONDS
        )
    except (BadData, TypeError, ValueError):
        return None
    user = get_user(user_id) if isinstance(user_id, int) else None
    if user and hmac.compare_digest(str(fingerprint), _reset_fingerprint(secret_key, user)):
        return user
    return None


def _reset_fingerprint(secret_key: str, user: Dict[str, Any]) -> str:
    # Unlike session_token's, so a reset link can't stand in for a session's token
    message = f"reset:{user['id']}:{user['password_hash']}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()[:32]
