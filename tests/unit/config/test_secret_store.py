"""Tests for SecretStore: MasterKey validation and encrypt/decrypt operations."""

import secrets
from pathlib import Path

import pytest

from banking.config.secret_store import (
    ConfigurationError,
    DecryptionError,
    SecretStore,
)

# ---------------------------------------------------------------------------
# T011 — MasterKey validation
# ---------------------------------------------------------------------------


def test_missing_master_key_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent BANKING_MASTER_KEY raises ConfigurationError with 'not set'."""
    monkeypatch.delenv("BANKING_MASTER_KEY", raising=False)
    with pytest.raises(ConfigurationError, match="not set"):
        SecretStore()


def test_malformed_master_key_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BANKING_MASTER_KEY with wrong length raises ConfigurationError."""
    monkeypatch.setenv("BANKING_MASTER_KEY", "tooshort")
    with pytest.raises(ConfigurationError, match="64 hex characters"):
        SecretStore()


# ---------------------------------------------------------------------------
# T012 — SecretStore operations
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_round_trip(mock_master_key: str, tmp_env_file: Path) -> None:
    """Encrypting then decrypting returns the original plaintext."""
    store = SecretStore(env_file=tmp_env_file)
    store.set("ROUND_TRIP_KEY", "hello world")
    assert store.get("ROUND_TRIP_KEY") == "hello world"


def test_decrypt_with_wrong_key_raises_decryption_error(
    mock_master_key: str, tmp_env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Decrypting a blob with a different MasterKey raises DecryptionError."""
    store = SecretStore(env_file=tmp_env_file)
    store.set("WRONG_KEY_TEST", "original_value")

    # Switch to a different MasterKey
    different_key = secrets.token_hex(32)
    monkeypatch.setenv("BANKING_MASTER_KEY", different_key)
    store2 = SecretStore(env_file=tmp_env_file)

    with pytest.raises(DecryptionError, match="MasterKey may be incorrect"):
        store2.get("WRONG_KEY_TEST")


def test_malformed_blob_raises_decryption_error(mock_master_key: str, tmp_env_file: Path) -> None:
    """A manually corrupted enc: blob raises DecryptionError with 'malformed'."""
    # Write a malformed blob directly
    tmp_env_file.write_text("CORRUPT_KEY=enc:!!!not_valid_base64!!!\n")
    store = SecretStore(env_file=tmp_env_file)
    with pytest.raises(DecryptionError, match="malformed"):
        store.get("CORRUPT_KEY")


def test_get_absent_key_raises_key_error(mock_master_key: str, tmp_env_file: Path) -> None:
    """get() on a key that does not exist raises KeyError."""
    store = SecretStore(env_file=tmp_env_file)
    with pytest.raises(KeyError):
        store.get("NONEXISTENT_KEY")
