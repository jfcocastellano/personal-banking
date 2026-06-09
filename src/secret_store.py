"""
SecretStore: secure abstraction for reading and writing credentials from
environment variables.

Security requirements:
  - Requirement 7.1: credentials are read exclusively from environment variables;
    never from source files or versioned configs.
  - Requirement 7.3: when a secret is missing, the error message identifies
    *which* key is absent — never the expected value.
  - Requirement 6.5: in GitHub Actions, updated tokens are persisted to the
    $GITHUB_ENV file so subsequent workflow steps can read the new value.
"""

import os

from .exceptions import MissingSecretError


class SecretStore:
    """Read and write credentials from/to environment variables.

    In a GitHub Actions workflow the ``$GITHUB_ENV`` environment variable
    points to a file that is sourced between steps.  Calling :meth:`set`
    appends ``KEY=VALUE`` to that file so the renewed token is available to
    subsequent steps without any shell-command side-effects.
    """

    def get(self, key: str) -> str:
        """Return the value of the environment variable *key*.

        Parameters
        ----------
        key:
            Name of the environment variable to read.

        Returns
        -------
        str
            The non-empty value associated with *key*.

        Raises
        ------
        MissingSecretError
            If the variable is not set **or** is set to an empty string.
            The error message includes only *key*, never its value, to
            satisfy Requirement 7.3.
        """
        value = os.environ.get(key, "")
        if not value:
            raise MissingSecretError(
                f"Required secret '{key}' is not set or is empty"
            )
        return value

    def set(self, key: str, value: str) -> None:
        """Persist *value* under *key* in the current process environment.

        Additionally, if the ``GITHUB_ENV`` environment variable is defined
        and non-empty, the ``KEY=VALUE`` pair is appended to that file so
        that subsequent GitHub Actions steps inherit the updated secret
        (Requirement 6.5).

        Parameters
        ----------
        key:
            Name of the environment variable to set.
        value:
            New value to store.  This value is **never** written to logs or
            exception messages (Requirement 7.4).
        """
        os.environ[key] = value

        github_env = os.environ.get("GITHUB_ENV", "")
        if github_env:
            with open(github_env, "a", encoding="utf-8") as fh:
                fh.write(f"{key}={value}\n")
