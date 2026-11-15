"""
Sending email, for password reset links, over SMTP: every email service (Resend, Postmark,
SendGrid, Mailgun, Amazon SES, a Gmail app password) offers it. Configured by environment:

- SMTP_HOST: the server; without it, emails are written to the log instead, for development
- SMTP_PORT: 587 (STARTTLS) by default; 465 connects over TLS from the start
- SMTP_STARTTLS: "false" to skip STARTTLS on other ports, for a local test server such as Mailpit
- SMTP_USERNAME, SMTP_PASSWORD: the login, if the server needs one
- SMTP_FROM: the sender's address, such as "D&D Combat Sim <noreply@example.com>"
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_SECONDS = 20


def configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def send(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises on failure: callers off the request thread log it."""
    host = os.environ.get("SMTP_HOST")
    sender = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USERNAME") or "noreply@localhost"
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    if not host:
        logger.warning(f"SMTP_HOST isn't set, so this email to {to} wasn't sent:\n{body}")
        return

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    context = ssl.create_default_context()
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
    with server:
        if port != 465 and os.environ.get("SMTP_STARTTLS", "true").lower() != "false":
            server.starttls(context=context)
        if username:
            server.login(username, os.environ.get("SMTP_PASSWORD", ""))
        server.send_message(message)
    logger.info(f"Sent '{subject}' email")
