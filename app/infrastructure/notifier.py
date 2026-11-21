"""Notifier adapters: e-mail over SMTP (production) and an in-memory outbox (tests, no SMTP configured)."""
from __future__ import annotations

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage


@dataclass
class SmtpNotifier:
    host: str
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = ""
    starttls: bool = True
    timeout_s: float = 30.0

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender or self.user
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_s) as smtp:
            if self.starttls:
                smtp.starttls()
            if self.user:
                smtp.login(self.user, self.password)
            smtp.send_message(msg)


@dataclass
class OutboxNotifier:
    """Keeps messages in memory – used when SMTP_HOST is empty (and in tests)."""
    sent: list[tuple[str, str, str]] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


def from_config():
    from backend import config

    if not config.SMTP_HOST:
        return OutboxNotifier()
    return SmtpNotifier(config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER, config.SMTP_PASSWORD,
                        config.SMTP_FROM, config.SMTP_STARTTLS)
