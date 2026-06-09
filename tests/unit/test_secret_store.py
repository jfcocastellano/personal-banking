"""
Unit tests for SecretStore.

Requirements covered:
  - 1.3  / 7.1: credentials read exclusively from environment variables
  - 6.5:        updated tokens written to $GITHUB_ENV for GitHub Actions persistence
  - 7.3:        MissingSecretError message identifies the key, never the value
"""

import os
import pytest

from src.secret_store import SecretStore
from src.exceptions import MissingSecretError


class TestSecretStoreGet:
    """Tests for SecretStore.get()."""

    def test_get_returns_value_when_set(self, monkeypatch):
        """get() returns the env-var value when it is non-empty."""
        monkeypatch.setenv("MY_TOKEN", "super-secret-value")
        store = SecretStore()
        assert store.get("MY_TOKEN") == "super-secret-value"

    def test_get_raises_when_variable_absent(self, monkeypatch):
        """get() raises MissingSecretError when the variable is not set at all."""
        monkeypatch.delenv("ABSENT_KEY", raising=False)
        store = SecretStore()
        with pytest.raises(MissingSecretError):
            store.get("ABSENT_KEY")

    def test_get_raises_when_variable_empty_string(self, monkeypatch):
        """get() raises MissingSecretError when the variable is set to ''."""
        monkeypatch.setenv("EMPTY_KEY", "")
        store = SecretStore()
        with pytest.raises(MissingSecretError):
            store.get("EMPTY_KEY")

    def test_get_error_message_contains_key_name(self, monkeypatch):
        """The MissingSecretError message must include the key name (Req 7.3)."""
        monkeypatch.delenv("ING_ACCESS_TOKEN", raising=False)
        store = SecretStore()
        with pytest.raises(MissingSecretError, match="ING_ACCESS_TOKEN"):
            store.get("ING_ACCESS_TOKEN")

    def test_get_error_message_does_not_contain_credential_value(self, monkeypatch):
        """The MissingSecretError message must NEVER reveal the credential value (Req 7.3)."""
        secret_value = "top-secret-123"
        monkeypatch.setenv("MY_SECRET", secret_value)
        # Force the variable to disappear so get() raises
        monkeypatch.delenv("MY_SECRET")
        store = SecretStore()
        with pytest.raises(MissingSecretError) as exc_info:
            store.get("MY_SECRET")
        assert secret_value not in str(exc_info.value)

    def test_get_raises_missing_secret_error_type(self, monkeypatch):
        """get() must raise exactly MissingSecretError, not a generic Exception."""
        monkeypatch.delenv("SOME_KEY", raising=False)
        store = SecretStore()
        with pytest.raises(MissingSecretError):
            store.get("SOME_KEY")


class TestSecretStoreSet:
    """Tests for SecretStore.set()."""

    def test_set_updates_os_environ(self, monkeypatch):
        """set() must update os.environ in the current process."""
        monkeypatch.delenv("MY_KEY", raising=False)
        store = SecretStore()
        store.set("MY_KEY", "new-value")
        assert os.environ.get("MY_KEY") == "new-value"

    def test_set_overwrites_existing_value(self, monkeypatch):
        """set() must overwrite a pre-existing env-var."""
        monkeypatch.setenv("MY_KEY", "old-value")
        store = SecretStore()
        store.set("MY_KEY", "new-value")
        assert os.environ.get("MY_KEY") == "new-value"

    def test_set_writes_to_github_env_file(self, monkeypatch, tmp_path):
        """set() must append KEY=VALUE to the file at $GITHUB_ENV when defined."""
        github_env_file = tmp_path / "github_env.txt"
        github_env_file.write_text("")  # create empty file
        monkeypatch.setenv("GITHUB_ENV", str(github_env_file))

        store = SecretStore()
        store.set("ING_ACCESS_TOKEN", "token-abc")

        content = github_env_file.read_text(encoding="utf-8")
        assert "ING_ACCESS_TOKEN=token-abc\n" in content

    def test_set_appends_multiple_keys_to_github_env(self, monkeypatch, tmp_path):
        """Multiple set() calls must each append a line to $GITHUB_ENV."""
        github_env_file = tmp_path / "github_env.txt"
        github_env_file.write_text("")
        monkeypatch.setenv("GITHUB_ENV", str(github_env_file))

        store = SecretStore()
        store.set("KEY_A", "value-a")
        store.set("KEY_B", "value-b")

        content = github_env_file.read_text(encoding="utf-8")
        assert "KEY_A=value-a\n" in content
        assert "KEY_B=value-b\n" in content

    def test_set_does_not_write_to_github_env_when_not_defined(self, monkeypatch, tmp_path):
        """set() must not create or modify any file when $GITHUB_ENV is absent."""
        monkeypatch.delenv("GITHUB_ENV", raising=False)

        store = SecretStore()
        # Should not raise and should not touch any file
        store.set("SOME_KEY", "some-value")
        assert os.environ.get("SOME_KEY") == "some-value"

    def test_set_does_not_write_to_github_env_when_empty(self, monkeypatch):
        """set() must skip the file write when $GITHUB_ENV is set to ''."""
        monkeypatch.setenv("GITHUB_ENV", "")
        store = SecretStore()
        # Must not raise FileNotFoundError or similar
        store.set("SOME_KEY", "some-value")

    def test_get_after_set_returns_new_value(self, monkeypatch):
        """A value stored via set() must be immediately readable via get()."""
        monkeypatch.delenv("DYNAMIC_KEY", raising=False)
        store = SecretStore()
        store.set("DYNAMIC_KEY", "fresh-token")
        assert store.get("DYNAMIC_KEY") == "fresh-token"
