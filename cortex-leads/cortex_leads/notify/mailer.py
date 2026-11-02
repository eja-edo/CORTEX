"""Outgoing email (password reset, WP39+). One small interface and three ways to satisfy it: SMTP (standard library, TLS), a directory
of files for development, and a list in memory for tests. Nothing here knows what a mail says; the caller builds the text.
A mail leaves the system for a third party, so callers put in it only what the person needs: a link, never a password."""
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, parseaddr
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from cortex_leads.config import get_settings

log = logging.getLogger(__name__)


class Mailer(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class MailError(Exception):
    pass


def _message(sender: str, to: str, subject: str, body: str) -> EmailMessage:
    if re.search(r"[\r\n]", to + subject + sender):  # header injection: an address or subject never holds a line break
        raise MailError("line break in a header")
    msg = EmailMessage()
    name, addr = parseaddr(sender)
    msg["From"] = formataddr((name, addr)) if name else addr
    msg["To"], msg["Subject"], msg["Date"] = to, subject, formatdate(usegmt=True)
    msg.set_content(body)
    return msg


class SmtpMailer:
    def __init__(self, host: str, port: int, user: str | None, password: str | None, sender: str, starttls: bool) -> None:
        self.host, self.port, self.user, self.password, self.sender, self.starttls = host, port, user, password, sender, starttls

    def _deliver(self, msg: EmailMessage) -> None:
        ctx = ssl.create_default_context()
        if self.starttls:
            with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                smtp.starttls(context=ctx)
                if self.user:
                    smtp.login(self.user, self.password or "")
                smtp.send_message(msg)
        else:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=ctx) as smtp:
                if self.user:
                    smtp.login(self.user, self.password or "")
                smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        import asyncio

        msg = _message(self.sender, to, subject, body)
        try:
            await asyncio.to_thread(self._deliver, msg)
        except (OSError, smtplib.SMTPException) as e:
            raise MailError(type(e).__name__) from e  # the class only: the server's reply can echo the address or a credential


class FileMailer:
    """Development: each mail is a plain text file in `directory` (readable as it is, unlike the encoded form on the wire), so the link can
    be opened without any mail server."""

    def __init__(self, directory: str, sender: str) -> None:
        self.directory, self.sender = Path(directory), sender

    async def send(self, to: str, subject: str, body: str) -> None:
        msg = _message(self.sender, to, subject, body)  # the same checks as a real send
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{uuid4().hex}.txt").write_text(f"From: {msg['From']}\nTo: {to}\nSubject: {subject}\n\n{body}", encoding="utf-8")


class MemoryMailer:
    """Tests: what would have been sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []
        self.fail = False

    async def send(self, to: str, subject: str, body: str) -> None:
        if self.fail:
            raise MailError("simulated")
        self.sent.append({"to": to, "subject": subject, "body": body})


_override: Mailer | None = None


def set_mailer(mailer: Mailer | None) -> None:
    """Tests (and a development server) install their own."""
    global _override
    _override = mailer


def get_mailer() -> Mailer | None:
    """None = no way to send: the feature that needs a mail says so instead of pretending."""
    if _override is not None:
        return _override
    cfg = get_settings()
    sender = cfg.MAIL_FROM or "Cortex <no-reply@localhost>"
    if cfg.SMTP_HOST and cfg.MAIL_FROM:
        return SmtpMailer(cfg.SMTP_HOST, cfg.SMTP_PORT, cfg.SMTP_USER, cfg.SMTP_PASSWORD, cfg.MAIL_FROM, cfg.SMTP_STARTTLS)
    if cfg.MAIL_DIR:
        return FileMailer(cfg.MAIL_DIR, sender)
    return None
