"""Shared pytest fixtures for unit tests."""

import json
import secrets
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from banking.config.secret_store import SecretStore


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
    """

    def _make(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    return _make
