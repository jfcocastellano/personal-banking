"""Shared pytest fixtures for unit tests."""

import json
import secrets
import smtplib
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from banking.config.secret_store import SecretStore

_SMTP_CONFIG = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "465",
    "SMTP_USER": "bot@example.com",
    "SMTP_PASSWORD": "app-password-1234",
    "NOTIFY_EMAIL_TO": "owner@example.com",
}


class _RealSMTPAttempted(BaseException):
    """Raised when a test reaches a real SMTP connection.

    Deliberately a ``BaseException``: production code catches ``Exception``
    around the send path (FR-006), so an ordinary exception would be swallowed
    and the offending test would pass. This one fails the test instead.
    """


class _GuardedSMTP(smtplib.SMTP):
    """``smtplib.SMTP`` that refuses to open a connection (FR-010)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise _RealSMTPAttempted(
            "real SMTP connection attempted — inject an smtp_factory returning "
            "Mock(spec=smtplib.SMTP) instead"
        )


class _GuardedSMTPSSL(smtplib.SMTP_SSL):
    """``smtplib.SMTP_SSL`` that refuses to open a connection (FR-010)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise _RealSMTPAttempted(
            "real SMTP connection attempted — inject an smtp_factory returning "
            "Mock(spec=smtplib.SMTP) instead"
        )


@pytest.fixture(autouse=True)
def no_real_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that tries to open a real SMTP connection (FR-010).

    Subclasses of the real classes keep ``Mock(spec=smtplib.SMTP)`` working
    (the spec still lists every real attribute). A test that needs to
    monkeypatch these attributes itself simply patches over this guard.
    """
    monkeypatch.setattr(smtplib, "SMTP", _GuardedSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _GuardedSMTPSSL)


@pytest.fixture
def smtp_config_in_store(
    mock_master_key: str, tmp_env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, str]:
    """Store the five SMTP/notification keys the notifier reads.

    Returns:
        The plaintext values that were stored.
    """
    monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))
    store = SecretStore(tmp_env_file)
    for key, value in _SMTP_CONFIG.items():
        store.set(key, value)
    return dict(_SMTP_CONFIG)


@pytest.fixture
def valid_master_key() -> str:
    """Return a valid 64-character hex MasterKey string."""
    return secrets.token_hex(32)


@pytest.fixture
def mock_master_key(monkeypatch: pytest.MonkeyPatch, valid_master_key: str) -> str:
    """Set BANKING_MASTER_KEY in the environment and return its value."""
    monkeypatch.setenv("BANKING_MASTER_KEY", valid_master_key)
    return valid_master_key


@pytest.fixture
def tmp_env_file(tmp_path: Path) -> Path:
    """Return a temporary .env file path (file does not exist yet)."""
    return tmp_path / ".env"


@pytest.fixture
def rsa_private_key_pem() -> bytes:
    """Generate an ephemeral RSA-2048 private key and return its PEM bytes.

    Never a real credential — generated fresh per test.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture
def eb_config_dir(
    tmp_path: Path, rsa_private_key_pem: bytes, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Write a temporary ``eb-config.json`` + private key PEM and point the
    connector at them via ``BANKING_EB_CONFIG_DIR``.
    """
    config_dir = tmp_path / "banca-personal"
    config_dir.mkdir()
    private_key_path = config_dir / "private.pem"
    private_key_path.write_bytes(rsa_private_key_pem)
    config_file = config_dir / "eb-config.json"
    config_file.write_text(
        json.dumps({"app_id": "test-app-id", "private_key_path": str(private_key_path)}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(config_dir))
    return config_dir


@pytest.fixture
def session_id_in_store(
    mock_master_key: str, tmp_env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Store an encrypted ``ENABLE_BANKING_SESSION_ID`` secret the connector
    can read via the default ``SecretStore()``.
    """
    monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))
    session_id = "test-session-id"
    SecretStore(tmp_env_file).set("ENABLE_BANKING_SESSION_ID", session_id)
    return session_id


@pytest.fixture
def google_sheets_credentials_in_store(
    mock_master_key: str,
    tmp_env_file: Path,
    rsa_private_key_pem: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    """Store a syntactically valid (but fake) service-account JSON under
    ``GOOGLE_SHEETS_CREDENTIALS`` the writer can read via the default
    ``SecretStore()``. Returns the dict that was stored.
    """
    monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))
    info = {
        "type": "service_account",
        "project_id": "test-project",
        "private_key_id": "test-key-id",
        "private_key": rsa_private_key_pem.decode("utf-8"),
        "client_email": "test@test-project.iam.gserviceaccount.com",
        "client_id": "123456789",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    SecretStore(tmp_env_file).set("GOOGLE_SHEETS_CREDENTIALS", json.dumps(info))
    return info


@pytest.fixture
def mock_http_client() -> Callable[[Callable[[httpx.Request], httpx.Response]], httpx.Client]:
    """Return a factory that builds an ``httpx.Client`` backed by a
    ``MockTransport`` — no real network call is ever made.

    Automatically answers the connector's account-resolution call
    (``GET /sessions/{session_id}``) with a single linked account, so
    individual tests only need to handle the transactions endpoint.
    """

    def _make(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
        def _dispatch(request: httpx.Request) -> httpx.Response:
            segments = request.url.path.strip("/").split("/")
            if request.method == "GET" and segments[:1] == ["sessions"] and len(segments) == 2:
                return httpx.Response(
                    200, json={"status": "AUTHORIZED", "accounts": ["test-account-id"]}
                )
            return handler(request)

        return httpx.Client(transport=httpx.MockTransport(_dispatch))

    return _make
