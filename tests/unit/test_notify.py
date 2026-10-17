"""Tests for `banking.notify`: configuration, transport and email content."""

import dataclasses
import logging
import smtplib
from email.message import EmailMessage
from unittest.mock import Mock

import pytest
from pytest_mock import MockerFixture

from banking import notify
from banking.config.secret_store import ConfigurationError, SecretStore
from banking.notify import DeliveryStatus, EmailConfig, EmailNotifier
from banking.sync import BankOutcome

_SMTP_VALUES = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "465",
    "SMTP_USER": "bot@example.com",
    "SMTP_PASSWORD": "app-password-1234",
    "NOTIFY_EMAIL_TO": "owner@example.com",
}


def _store_with(**overrides: str | None) -> Mock:
    """Build a SecretStore double whose contents are `_SMTP_VALUES` plus overrides.

    Passing ``None`` for a key removes it, which is how missing configuration is
    simulated.
    """
    values = dict(_SMTP_VALUES)
    for key, value in overrides.items():
        if value is None:
            values.pop(key, None)
        else:
            values[key] = value

    def _get(key: str) -> str:
        if key not in values:
            raise KeyError(key)
        return values[key]

    store = Mock(spec=SecretStore)
    store.get.side_effect = _get
    return store


def _no_factory(config: EmailConfig) -> smtplib.SMTP:
    raise AssertionError("smtp_factory must not be called at construction time")


# --- Tipos y construcción perezosa -----------------------------------------


def test_email_config_is_a_frozen_dataclass_with_the_documented_fields() -> None:
    config = EmailConfig(
        host="smtp.example.com",
        port=465,
        user="bot@example.com",
        password="app-password-1234",
        to_address="owner@example.com",
    )

    assert dataclasses.is_dataclass(config)
    assert config.host == "smtp.example.com"
    assert config.port == 465
    assert config.user == "bot@example.com"
    assert config.password == "app-password-1234"
    assert config.to_address == "owner@example.com"
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.host = "other.example.com"  # type: ignore[misc]


def test_delivery_status_exposes_the_three_documented_states() -> None:
    assert {status.name for status in DeliveryStatus} == {"SENT", "SKIPPED", "FAILED"}


def test_notifier_does_not_read_secrets_or_open_a_connection_on_construction() -> None:
    """Configuration is loaded lazily, on the first send (FR-003, US3)."""
    store = _store_with()

    EmailNotifier(store=store, smtp_factory=_no_factory)

    store.get.assert_not_called()
    store.set.assert_not_called()


# --- _load_config ------------------------------------------------------------


def test_load_config_returns_the_full_configuration_with_an_int_port() -> None:
    notifier = EmailNotifier(store=_store_with(), smtp_factory=_no_factory)

    config = notifier._load_config()

    assert config == EmailConfig(
        host="smtp.example.com",
        port=465,
        user="bot@example.com",
        password="app-password-1234",
        to_address="owner@example.com",
    )
    assert isinstance(config, EmailConfig)
    assert config.port == 465


@pytest.mark.parametrize(
    "missing_key",
    ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_EMAIL_TO"],
)
def test_load_config_returns_none_when_a_key_is_missing(
    missing_key: str, caplog: pytest.LogCaptureFixture
) -> None:
    notifier = EmailNotifier(store=_store_with(**{missing_key: None}))

    with caplog.at_level(logging.DEBUG, logger="banking.notify"):
        config = notifier._load_config()

    assert config is None
    records = [r for r in caplog.records if r.name == "banking.notify"]
    assert any(r.levelno == logging.WARNING and missing_key in r.getMessage() for r in records)
    assert not any(r.levelno >= logging.ERROR for r in records)


def test_load_config_returns_none_when_the_port_is_not_an_integer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    notifier = EmailNotifier(store=_store_with(SMTP_PORT="abc"))

    with caplog.at_level(logging.DEBUG, logger="banking.notify"):
        config = notifier._load_config()

    assert config is None
    records = [r for r in caplog.records if r.name == "banking.notify"]
    assert any(r.levelno == logging.WARNING and "SMTP_PORT" in r.getMessage() for r in records)
    assert not any(r.levelno >= logging.ERROR for r in records)


def test_load_config_returns_none_when_the_secret_store_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No master key (or an unreadable store) is missing configuration, not a failure."""

    def _unavailable(env_file: object = None) -> SecretStore:
        raise ConfigurationError("BANKING_MASTER_KEY environment variable is not set.")

    monkeypatch.setattr(notify, "SecretStore", _unavailable)
    notifier = EmailNotifier()

    with caplog.at_level(logging.DEBUG, logger="banking.notify"):
        config = notifier._load_config()

    assert config is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_load_config_never_logs_the_password(caplog: pytest.LogCaptureFixture) -> None:
    notifier = EmailNotifier(store=_store_with())

    with caplog.at_level(logging.DEBUG, logger="banking.notify"):
        notifier._load_config()

    logged = " ".join(r.getMessage() for r in caplog.records)
    assert _SMTP_VALUES["SMTP_PASSWORD"] not in logged


# --- Transporte (_send) ------------------------------------------------------


def test_send_logs_in_sends_and_quits_returning_sent(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    smtp = mocker.Mock(spec=smtplib.SMTP)
    factory = mocker.Mock(return_value=smtp)
    notifier = EmailNotifier(store=_store_with(), smtp_factory=factory)
    message = EmailMessage()
    message["Subject"] = "asunto"
    message["To"] = "owner@example.com"
    message.set_content("cuerpo")

    with caplog.at_level(logging.DEBUG, logger="banking.notify"):
        status = notifier._send(message)

    assert status is DeliveryStatus.SENT
    factory.assert_called_once()
    sent_config = factory.call_args.args[0]
    assert sent_config.host == "smtp.example.com"
    assert sent_config.port == 465
    assert smtp.method_calls == [
        mocker.call.login("bot@example.com", "app-password-1234"),
        mocker.call.send_message(message),
        mocker.call.quit(),
    ]
    info = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.INFO)
    assert "owner@example.com" in info


@pytest.mark.parametrize(
    "exc",
    [
        smtplib.SMTPAuthenticationError(535, b"bad credentials"),
        smtplib.SMTPException("smtp exploded"),
        OSError("network down"),
    ],
    ids=["auth", "smtp", "os"],
)
@pytest.mark.parametrize("failing_method", ["login", "send_message"])
def test_send_returns_failed_on_transport_errors_without_raising(
    exc: Exception,
    failing_method: str,
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
) -> None:
    smtp = mocker.Mock(spec=smtplib.SMTP)
    getattr(smtp, failing_method).side_effect = exc
    notifier = EmailNotifier(store=_store_with(), smtp_factory=mocker.Mock(return_value=smtp))
    message = EmailMessage()
    message["Subject"] = "asunto"
    message["To"] = "owner@example.com"

    with caplog.at_level(logging.DEBUG, logger="banking.notify"):
        status = notifier._send(message)

    assert status is DeliveryStatus.FAILED
    assert smtp.quit.called or smtp.close.called
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert errors
    joined = " ".join(errors)
    assert type(exc).__name__ in joined
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert _SMTP_VALUES["SMTP_PASSWORD"] not in logged


def test_send_skips_when_configuration_is_missing(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    factory = mocker.Mock()
    notifier = EmailNotifier(store=_store_with(SMTP_PASSWORD=None), smtp_factory=factory)
    message = EmailMessage()
    message["Subject"] = "asunto"

    with caplog.at_level(logging.DEBUG, logger="banking.notify"):
        status = notifier._send(message)

    assert status is DeliveryStatus.SKIPPED
    factory.assert_not_called()
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings


def test_default_smtp_factory_uses_smtp_ssl_with_the_configured_host_and_a_timeout(
    mocker: MockerFixture,
) -> None:
    """The default transport is SMTP_SSL (implicit TLS) with a bounded timeout."""
    smtp_ssl = mocker.patch.object(smtplib, "SMTP_SSL", autospec=True)
    config = EmailConfig(
        host="smtp.example.com",
        port=465,
        user="bot@example.com",
        password="app-password-1234",
        to_address="owner@example.com",
    )

    notify._default_smtp_factory(config)

    smtp_ssl.assert_called_once_with("smtp.example.com", 465, timeout=notify._SMTP_TIMEOUT_SECONDS)


# --- US1: fallo parcial ------------------------------------------------------


def _outcomes(*specs: tuple[str, bool, int | None, str | None]) -> list[BankOutcome]:
    return [
        BankOutcome(bank_name=name, succeeded=succeeded, rows_written=rows, failure_reason=reason)
        for name, succeeded, rows, reason in specs
    ]


def _smtp_double(mocker: MockerFixture) -> tuple[smtplib.SMTP, Mock]:
    smtp = mocker.Mock(spec=smtplib.SMTP)
    return smtp, mocker.Mock(return_value=smtp)


def _sent_message(smtp: smtplib.SMTP) -> EmailMessage:
    assert isinstance(smtp.send_message.call_args, type(smtp.send_message.call_args))
    message = smtp.send_message.call_args.args[0]
    assert isinstance(message, EmailMessage)
    return message


def _partial_outcomes() -> list[BankOutcome]:
    return _outcomes(
        ("ING España", True, 3, None),
        ("Revolut", False, None, "sesión expirada"),
        ("MyInvestor", True, 2, None),
        ("Banco Sabadell", True, 1, None),
    )


def test_notify_failure_partial_sends_one_email_with_subject_headers_and_body(
    mocker: MockerFixture,
) -> None:
    smtp, factory = _smtp_double(mocker)
    notifier = EmailNotifier(store=_store_with(), smtp_factory=factory)

    status = notifier.notify_failure(
        outcomes=_partial_outcomes(),
        sheets_error=None,
        tab_name="2026-08",
        duration_seconds=3.42,
    )

    assert status is DeliveryStatus.SENT
    smtp.send_message.assert_called_once()
    message = _sent_message(smtp)
    assert message["Subject"] == "Sincronización parcial: 3/4 bancos — fallo en 2026-08"
    assert message["From"] == _SMTP_VALUES["SMTP_USER"]
    assert message["To"] == _SMTP_VALUES["NOTIFY_EMAIL_TO"]
    assert "text/plain" in message["Content-Type"]
    assert 'charset="utf-8"' in message["Content-Type"]

    body = message.get_content()
    assert "Fecha:" in body
    assert "Pestaña: 2026-08" in body
    assert "Duración: 3.42s" in body
    for name, rows in [("ING España", 3), ("MyInvestor", 2), ("Banco Sabadell", 1)]:
        assert f"- {name}: {rows} movimientos" in body
    assert "- Revolut: FALLÓ — sesión expirada" in body
    assert _SMTP_VALUES["SMTP_PASSWORD"] not in body
    assert _SMTP_VALUES["SMTP_PASSWORD"] not in str(message["Subject"])


def test_notify_failure_partial_with_two_failed_banks_sends_a_single_email(
    mocker: MockerFixture,
) -> None:
    smtp, factory = _smtp_double(mocker)
    notifier = EmailNotifier(store=_store_with(), smtp_factory=factory)
    outcomes = _outcomes(
        ("ING España", True, 3, None),
        ("Revolut", False, None, "RateLimitExceededError: límite alcanzado"),
        ("MyInvestor", False, None, "EnableBankingAPIError: 500"),
        ("Banco Sabadell", True, 4, None),
    )

    status = notifier.notify_failure(
        outcomes=outcomes, sheets_error=None, tab_name="2026-08", duration_seconds=1.0
    )

    assert status is DeliveryStatus.SENT
    smtp.send_message.assert_called_once()
    message = _sent_message(smtp)
    assert message["Subject"] == "Sincronización parcial: 2/4 bancos — fallo en 2026-08"
    body = message.get_content()
    assert "RateLimitExceededError: límite alcanzado" in body
    assert "EnableBankingAPIError: 500" in body
    assert "- ING España: 3 movimientos" in body
    assert "- Banco Sabadell: 4 movimientos" in body


# --- US2: fallo total y fallo de escritura en Sheets ------------------------


def _total_failure_outcomes() -> list[BankOutcome]:
    return _outcomes(
        ("ING España", False, None, "ReauthorizationRequiredError: sesión caducada"),
        ("Revolut", False, None, "RateLimitExceededError: límite alcanzado"),
        ("MyInvestor", False, None, "EnableBankingAPIError: 500"),
        ("Banco Sabadell", False, None, "TimeoutError: sin respuesta"),
    )


def test_notify_failure_total_sends_one_email_with_the_four_reasons(
    mocker: MockerFixture,
) -> None:
    smtp, factory = _smtp_double(mocker)
    notifier = EmailNotifier(store=_store_with(), smtp_factory=factory)

    status = notifier.notify_failure(
        outcomes=_total_failure_outcomes(),
        sheets_error=None,
        tab_name="2026-08",
        duration_seconds=12.5,
    )

    assert status is DeliveryStatus.SENT
    smtp.send_message.assert_called_once()
    message = _sent_message(smtp)
    assert message["Subject"] == "Sincronización fallida: los 4 bancos fallaron — 2026-08"
    body = message.get_content()
    for reason in [
        "sesión caducada",
        "límite alcanzado",
        "EnableBankingAPIError: 500",
        "sin respuesta",
    ]:
        assert reason in body
    assert "movimientos" not in body
    assert "ERROR (Sheets)" not in body
    assert _SMTP_VALUES["SMTP_PASSWORD"] not in body


def test_notify_failure_sheets_only_reports_the_write_error_as_the_main_cause(
    mocker: MockerFixture,
) -> None:
    smtp, factory = _smtp_double(mocker)
    notifier = EmailNotifier(store=_store_with(), smtp_factory=factory)
    outcomes = _outcomes(
        ("ING España", True, 3, None),
        ("Revolut", True, 2, None),
        ("MyInvestor", True, 0, None),
        ("Banco Sabadell", True, 1, None),
    )

    status = notifier.notify_failure(
        outcomes=outcomes,
        sheets_error="SheetsAccessError: sin permisos",
        tab_name="2026-08",
        duration_seconds=4.0,
    )

    assert status is DeliveryStatus.SENT
    smtp.send_message.assert_called_once()
    message = _sent_message(smtp)
    assert (
        message["Subject"] == "Sincronización fallida: error escribiendo en Google Sheets — 2026-08"
    )
    body = message.get_content()
    assert "ERROR (Sheets): SheetsAccessError: sin permisos" in body
    assert "FALLÓ —" not in body
    assert "- ING España: 3 movimientos" in body
    assert _SMTP_VALUES["SMTP_PASSWORD"] not in body


def test_notify_failure_combined_case_sends_a_single_email_with_both_causes(
    mocker: MockerFixture,
) -> None:
    smtp, factory = _smtp_double(mocker)
    notifier = EmailNotifier(store=_store_with(), smtp_factory=factory)
    outcomes = _outcomes(
        ("ING España", True, 3, None),
        ("Revolut", False, None, "ReauthorizationRequiredError: re-auth needed"),
        ("MyInvestor", True, 1, None),
        ("Banco Sabadell", False, None, "TimeoutError: sin respuesta"),
    )

    status = notifier.notify_failure(
        outcomes=outcomes,
        sheets_error="SheetsQuotaExceededError: cuota",
        tab_name="2026-08",
        duration_seconds=7.5,
    )

    assert status is DeliveryStatus.SENT
    smtp.send_message.assert_called_once()
    message = _sent_message(smtp)
    assert message["Subject"] == (
        "Sincronización fallida: error escribiendo en Google Sheets (con fallos de banco) — 2026-08"
    )
    body = message.get_content()
    assert "ERROR (Sheets): SheetsQuotaExceededError: cuota" in body
    assert "- Revolut: FALLÓ — ReauthorizationRequiredError: re-auth needed" in body
    assert "- Banco Sabadell: FALLÓ — TimeoutError: sin respuesta" in body
    assert "- ING España: 3 movimientos" in body


def test_notify_failure_without_outcome_context_still_classifies_the_sheets_failure(
    mocker: MockerFixture,
) -> None:
    """Defensive fallback for callers that raise without structured context."""
    smtp, factory = _smtp_double(mocker)
    notifier = EmailNotifier(store=_store_with(), smtp_factory=factory)

    status = notifier.notify_failure(
        outcomes=[],
        sheets_error="SheetsConfigError: credenciales",
        tab_name="2026-08",
        duration_seconds=0.0,
    )

    assert status is DeliveryStatus.SENT
    message = _sent_message(smtp)
    assert (
        message["Subject"] == "Sincronización fallida: error escribiendo en Google Sheets — 2026-08"
    )
    assert "ERROR (Sheets): SheetsConfigError: credenciales" in message.get_content()


def test_notify_failure_failed_subject_when_configuration_skips(
    mocker: MockerFixture,
) -> None:
    """A failed delivery is reported as FAILED even for the new failure modes."""
    factory = mocker.Mock()
    notifier = EmailNotifier(store=_store_with(SMTP_HOST=None), smtp_factory=factory)

    status = notifier.notify_failure(
        outcomes=_total_failure_outcomes(),
        sheets_error=None,
        tab_name="2026-08",
        duration_seconds=1.0,
    )

    assert status is DeliveryStatus.SKIPPED
    factory.assert_not_called()
