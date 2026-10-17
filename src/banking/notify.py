"""Failure notifications over Gmail SMTP (IT6).

Builds a single aggregated email for a failed sync run and delivers it through
an injectable SMTP transport. Everything here is standard library only
(``smtplib`` + ``email``), so no new dependency is introduced.

Design notes:
    * Notification is best effort: `notify_failure` never raises, and a missing
      configuration degrades to a warning plus `DeliveryStatus.SKIPPED` (FR-007).
    * Nothing sensitive is ever rendered: the password is used only for the
      ``login`` call and never interpolated into logs, subject, body or headers
      (FR-008, Principio IV).
    * The transport is injectable so tests can run with ``Mock(spec=smtplib.SMTP)``
      and never touch the network (FR-010, Principio III).
"""

import logging
import smtplib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from enum import Enum

from banking.config.secret_store import ConfigurationError, DecryptionError, SecretStore
from banking.sync import BankOutcome

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT_SECONDS = 30
_REQUIRED_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_EMAIL_TO")


class DeliveryStatus(Enum):
    """The result of trying to deliver one notification email."""

    SENT = "sent"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class EmailConfig:
    """The SMTP settings needed to send one notification."""

    host: str
    port: int
    user: str
    password: str
    to_address: str


def _default_smtp_factory(config: EmailConfig) -> smtplib.SMTP:
    """Open an implicit-TLS SMTP connection to the configured host."""
    return smtplib.SMTP_SSL(config.host, config.port, timeout=_SMTP_TIMEOUT_SECONDS)


class EmailNotifier:
    """Sends the aggregated failure email for a sync run.

    Args:
        store: Secret store to read the SMTP configuration from. Defaults to
            :class:`SecretStore`, and is only consulted on the first send.
        smtp_factory: Callable building the SMTP transport from an
            :class:`EmailConfig`. Injected by tests.
    """

    def __init__(
        self,
        store: SecretStore | None = None,
        smtp_factory: Callable[[EmailConfig], smtplib.SMTP] | None = None,
    ) -> None:
        self._store = store
        self._smtp_factory = smtp_factory or _default_smtp_factory

    def _load_config(self) -> EmailConfig | None:
        """Read the SMTP configuration from the store.

        Returns:
            The configuration, or ``None`` when any key is missing, the store is
            unavailable, or ``SMTP_PORT`` is not an integer. Never raises.
        """
        try:
            store = self._store if self._store is not None else SecretStore()
        except (ConfigurationError, DecryptionError):
            logger.warning("Email notification skipped: the SecretStore is not available")
            return None
        values: dict[str, str] = {}
        for key in _REQUIRED_KEYS:
            try:
                values[key] = store.get(key)
            except (KeyError, ConfigurationError, DecryptionError):
                logger.warning("Email notification skipped: missing configuration key %s", key)
                return None

        try:
            port = int(values["SMTP_PORT"])
        except ValueError:
            logger.warning("Email notification skipped: SMTP_PORT is not a valid port number")
            return None

        return EmailConfig(
            host=values["SMTP_HOST"],
            port=port,
            user=values["SMTP_USER"],
            password=values["SMTP_PASSWORD"],
            to_address=values["NOTIFY_EMAIL_TO"],
        )

    def _send(self, message: EmailMessage, config: EmailConfig | None = None) -> DeliveryStatus:
        """Deliver *message* through SMTP, never raising.

        Args:
            message: The message to deliver.
            config: Already-resolved configuration, to avoid reading the store
                twice. Loaded from the store when omitted.

        Returns:
            `DeliveryStatus.SENT` on success, `DeliveryStatus.SKIPPED` when the
            configuration is absent, `DeliveryStatus.FAILED` on any transport
            error.
        """
        resolved = config if config is not None else self._load_config()
        if resolved is None:
            return DeliveryStatus.SKIPPED

        connection: smtplib.SMTP | None = None
        started = time.monotonic()
        try:
            connection = self._smtp_factory(resolved)
            connection.login(resolved.user, resolved.password)
            connection.send_message(message)
        except Exception as exc:
            logger.error("Email notification failed: %s: %s", type(exc).__name__, exc)
            return DeliveryStatus.FAILED
        else:
            elapsed = time.monotonic() - started
            logger.info("Email notification sent to %s in %.3fs", resolved.to_address, elapsed)
            return DeliveryStatus.SENT
        finally:
            if connection is not None:
                try:
                    connection.quit()
                except Exception:
                    try:
                        connection.close()
                    except Exception:
                        logger.debug("SMTP connection could not be closed cleanly")

    def notify_failure(
        self,
        outcomes: list[BankOutcome],
        sheets_error: str | None,
        tab_name: str,
        duration_seconds: float,
    ) -> DeliveryStatus:
        """Send the aggregated failure email for one sync run.

        Args:
            outcomes: Per-bank outcomes of the run. Bank failures are reported
                individually; successful banks are summarised.
            sheets_error: The Sheets error message, when the run failed (or
                partially failed) while writing.
            tab_name: The destination tab, e.g. ``"2026-08"``.
            duration_seconds: How long the sync run took.

        Returns:
            The delivery status. Never raises.
        """
        try:
            config = self._load_config()
            if config is None:
                return DeliveryStatus.SKIPPED
            subject = _build_subject(outcomes, sheets_error, tab_name)
            body = _build_body(outcomes, sheets_error, tab_name, duration_seconds)
            message = self._build_message(config, subject, body)
        except Exception as exc:
            logger.error("Email notification failed: %s: %s", type(exc).__name__, exc)
            return DeliveryStatus.FAILED
        return self._send(message, config)

    def _build_message(self, config: EmailConfig, subject: str, body: str) -> EmailMessage:
        """Assemble the message with the From/To headers and a plain-text body."""
        message = EmailMessage()
        message["From"] = config.user
        message["To"] = config.to_address
        message["Subject"] = subject
        message.set_content(body, subtype="plain", charset="utf-8")
        return message


def _count_succeeded(outcomes: list[BankOutcome]) -> int:
    """Return how many banks succeeded in the run."""
    return sum(1 for outcome in outcomes if outcome.succeeded)


def _build_subject(outcomes: list[BankOutcome], sheets_error: str | None, tab_name: str) -> str:
    """Build the email subject for the run's failure mode (see research.md)."""
    succeeded = _count_succeeded(outcomes)

    if sheets_error is None:
        if succeeded and succeeded < len(outcomes):
            return (
                f"Sincronización parcial: {succeeded}/{len(outcomes)} bancos — fallo en {tab_name}"
            )
        return f"Sincronización fallida: los 4 bancos fallaron — {tab_name}"

    if any(not outcome.succeeded for outcome in outcomes):
        return (
            "Sincronización fallida: error escribiendo en Google Sheets "
            f"(con fallos de banco) — {tab_name}"
        )
    return f"Sincronización fallida: error escribiendo en Google Sheets — {tab_name}"


def _build_body(
    outcomes: list[BankOutcome],
    sheets_error: str | None,
    tab_name: str,
    duration_seconds: float,
) -> str:
    """Build the plain-text email body describing the failure (see contracts/)."""
    lines = [
        "La sincronización bancaria terminó con errores.",
        "",
        f"Fecha: {_format_timestamp()}",
        f"Pestaña: {tab_name}",
        f"Duración: {duration_seconds:.2f}s",
        "",
        "Bancos:",
    ]
    for outcome in outcomes:
        if outcome.succeeded:
            lines.append(f"  - {outcome.bank_name}: {outcome.rows_written} movimientos")
        else:
            lines.append(f"  - {outcome.bank_name}: FALLÓ — {outcome.failure_reason}")
    if sheets_error is not None:
        lines.extend(["", f"ERROR (Sheets): {sheets_error}"])
    return "\n".join(lines) + "\n"


def _format_timestamp() -> str:
    """Return the run timestamp as ``YYYY-MM-DD HH:MM``."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")
