"""AES-256-GCM SecretStore: encrypted key-value storage in a .env file."""

import base64
import logging
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_ENC_PREFIX = "enc:"
_NONCE_BYTES = 12
_KEY_BYTES = 32  # 256-bit


class ConfigurationError(Exception):
    """Raised when the MasterKey is absent or malformed."""


class DecryptionError(Exception):
    """Raised when an encrypted blob cannot be decrypted."""


def _load_master_key() -> bytes:
    """Load and validate BANKING_MASTER_KEY from the OS environment.

    Returns the raw 32-byte key.

    Raises:
        ConfigurationError: if the env var is absent or not 64 hex characters.
    """
    raw = os.environ.get("BANKING_MASTER_KEY")
    if raw is None:
        raise ConfigurationError(
            "BANKING_MASTER_KEY environment variable is not set. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    if len(raw) != 64 or not all(c in "0123456789abcdefABCDEF" for c in raw):
        raise ConfigurationError(
            f"BANKING_MASTER_KEY is invalid. Expected 64 hex characters (32 bytes), "
            f"got {len(raw)} characters."
        )
    return bytes.fromhex(raw)


def _encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt *plaintext* with AES-256-GCM and return an ``enc:<base64url>`` string."""
    nonce = os.urandom(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    ciphertext_with_tag = aesgcm.encrypt(nonce, plaintext.encode(), None)
    blob = base64.urlsafe_b64encode(nonce + ciphertext_with_tag).decode()
    return f"{_ENC_PREFIX}{blob}"


def _decrypt(encrypted_value: str, key: bytes, key_name: str) -> str:
    """Decrypt an ``enc:<base64url>`` string and return the plaintext.

    Raises:
        DecryptionError: if the blob is malformed or the authentication tag fails.
    """
    if not encrypted_value.startswith(_ENC_PREFIX):
        return encrypted_value  # plain-text value, return as-is

    b64 = encrypted_value[len(_ENC_PREFIX) :]
    try:
        raw = base64.urlsafe_b64decode(b64 + "==")  # add padding tolerance
    except Exception:
        raise DecryptionError(
            f"Stored value for key '{key_name}' is malformed and cannot be decoded."
        )

    if len(raw) < _NONCE_BYTES + 16:  # nonce + minimum GCM tag
        raise DecryptionError(
            f"Stored value for key '{key_name}' is malformed and cannot be decoded."
        )

    nonce = raw[:_NONCE_BYTES]
    ciphertext_with_tag = raw[_NONCE_BYTES:]
    aesgcm = AESGCM(key)
    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
    except InvalidTag:
        raise DecryptionError(
            f"Decryption failed for key '{key_name}'. "
            "The MasterKey may be incorrect or the stored value is corrupted."
        )
    return plaintext_bytes.decode()


def _read_env_file(env_file: Path) -> dict[str, str]:
    """Parse a dotenv file into a {key: raw_value} dict.

    Comments and blank lines are ignored.  Values with an ``enc:`` prefix
    are returned as-is (still encrypted).
    """
    if not env_file.exists():
        return {}
    entries: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        k, _, v = stripped.partition("=")
        entries[k.strip()] = v.strip()
    return entries


def _write_env_file(env_file: Path, entries: dict[str, str]) -> None:
    """Write *entries* to *env_file* in dotenv format."""
    lines = [f"{k}={v}\n" for k, v in entries.items()]
    env_file.write_text("".join(lines), encoding="utf-8")


class SecretStore:
    """Encrypted key-value store backed by a dotenv-format ``.env`` file.

    Usage::

        store = SecretStore()
        store.set("MY_SECRET", "plaintext")
        value = store.get("MY_SECRET")  # returns "plaintext"

    The ``BANKING_MASTER_KEY`` OS environment variable (64 hex chars) is
    required at construction time.  All values written via :meth:`set` are
    stored with an ``enc:`` prefix.
    """

    def __init__(self, env_file: Path | None = None) -> None:
        """Initialise the store.

        Args:
            env_file: Path to the ``.env`` file.  Defaults to the value of the
                ``BANKING_ENV_FILE`` environment variable, or ``.env`` in the
                current working directory if that variable is not set.

        Raises:
            ConfigurationError: if ``BANKING_MASTER_KEY`` is absent or malformed.
        """
        if env_file is None:
            env_path = os.environ.get("BANKING_ENV_FILE")
            env_file = Path(env_path) if env_path else Path(".env")
        self._env_file = env_file
        self._key = _load_master_key()

    def set(self, key: str, plaintext: str) -> None:
        """Encrypt *plaintext* and write it to the SecretStore under *key*.

        If the key already exists its value is overwritten.

        Args:
            key: Environment variable name (e.g. ``"MY_SECRET"``).
            plaintext: The sensitive value to encrypt and store.
        """
        entries = _read_env_file(self._env_file)
        entries[key] = _encrypt(plaintext, self._key)
        _write_env_file(self._env_file, entries)
        logger.debug("SecretStore: set key '%s'", key)

    def get(self, key: str) -> str:
        """Decrypt and return the value stored under *key*.

        Args:
            key: Environment variable name.

        Returns:
            The decrypted plaintext string.

        Raises:
            KeyError: if *key* is not present in the store.
            DecryptionError: if the stored blob is malformed or decryption fails.
        """
        entries = _read_env_file(self._env_file)
        if key not in entries:
            raise KeyError(key)
        return _decrypt(entries[key], self._key, key)
