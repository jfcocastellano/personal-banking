"""
TransactionFetcher: fetches daily transactions from the Enable Banking API.

Security requirements:
  - Req 7.2: All API calls use HTTPS exclusively.
  - Req 7.3 / 7.4: No token or credential value appears in log messages or
    exception messages. Exception messages identify the bank entity and the
    HTTP status code only.
  - Req 1.1 / 1.3: Tokens are read exclusively from the SecretStore (env vars).

Retry strategy (Req 1.6, 2.4):
  - Network errors and HTTP 5xx / 429 → exponential backoff, max 5 attempts.
  - HTTP 401 / 403 → no retry; raises BankAuthError immediately after attempting
    a single token refresh on the first 401 from the transactions endpoint.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
    wait_combine,
)

from .exceptions import BankAuthError, BankAPIError
from .secret_store import SecretStore

# Module-level logger (Python stdlib) — used only for internal debug traces
# that must never contain credential values.
_log = logging.getLogger(__name__)

# Base URL for all Enable Banking API calls. HTTPS is the only permitted scheme.
_BASE_URL = "https://api.enablebanking.com"


# ---------------------------------------------------------------------------
# Module-level utility
# ---------------------------------------------------------------------------

def get_yesterday(today: date) -> date:
    """Return the calendar day immediately before *today*.

    Parameters
    ----------
    today:
        The reference date (typically ``datetime.date.today()``).

    Returns
    -------
    date
        ``today - 1 day``.

    Validates: Requirements 2.1 (Property 3)
    """
    return today - timedelta(days=1)


# ---------------------------------------------------------------------------
# Internal sentinel exception — used to signal "retry-able" HTTP errors
# without leaking status codes or credentials into external exception messages
# until all retries are exhausted.
# ---------------------------------------------------------------------------

class _RetryableHTTPError(Exception):
    """Internal: raised for HTTP 5xx / 429 to trigger tenacity retry."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"HTTP {status}")


# ---------------------------------------------------------------------------
# TransactionFetcher
# ---------------------------------------------------------------------------

class TransactionFetcher:
    """Authenticate with the Enable Banking API and fetch transactions.

    Parameters
    ----------
    bank:
        Bank entity name (e.g. ``"ING"``, ``"Sabadell"``).  The token keys in
        the Secret Store are derived by uppercasing this name.
    secret_store:
        A :class:`~src.secret_store.SecretStore` instance used to read and
        write access / refresh tokens.

    On construction the fetcher reads ``{BANK_UPPER}_ACCESS_TOKEN`` and
    ``{BANK_UPPER}_REFRESH_TOKEN`` from the Secret Store.  A
    :exc:`~src.exceptions.MissingSecretError` propagates immediately if
    either key is absent or empty.
    """

    def __init__(self, bank: str, secret_store: SecretStore) -> None:
        self._bank = bank
        self._bank_upper = bank.upper()
        self._secret_store = secret_store

        # Read tokens at construction time; MissingSecretError propagates to
        # the caller if a token is absent (Req 7.3).
        self._access_token: str = secret_store.get(
            f"{self._bank_upper}_ACCESS_TOKEN"
        )
        self._refresh_token: str = secret_store.get(
            f"{self._bank_upper}_REFRESH_TOKEN"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_transactions(self, date_from: date, date_to: date) -> list[dict]:
        """Fetch raw transactions from the Enable Banking API.

        Sends ``GET /transactions`` with ``date_from`` and ``date_to`` as ISO
        8601 query parameters and an ``Authorization: Bearer`` header.

        On HTTP 401 the method attempts a single token refresh then retries
        the original request once.  Persistent auth failures raise
        :exc:`~src.exceptions.BankAuthError`.

        Network errors and HTTP 5xx / 429 responses are retried up to 5 times
        with exponential backoff plus random jitter before raising
        :exc:`~src.exceptions.BankAPIError`.

        Parameters
        ----------
        date_from:
            Start of the date range (inclusive), ISO 8601 format in the query.
        date_to:
            End of the date range (inclusive), ISO 8601 format in the query.

        Returns
        -------
        list[dict]
            Raw transaction dicts returned by the API.

        Raises
        ------
        BankAuthError
            If authentication cannot be established (invalid/expired tokens).
        BankAPIError
            If the API returns a non-auth HTTP error after all retries are
            exhausted.
        """
        params = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }
        return self._fetch_with_refresh(params)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_with_refresh(self, params: dict[str, str]) -> list[dict]:
        """Perform the transactions request, refreshing the token once on 401.

        This method is intentionally separated from the tenacity-wrapped inner
        helper so that the token-refresh logic runs *outside* the retry loop —
        a 401 triggers exactly one refresh attempt, not five.
        """
        try:
            return self._fetch_transactions_with_retry(params)
        except BankAuthError:
            # 401 from the transactions endpoint → try to refresh first.
            self._refresh_access_token()
            # After a successful refresh, retry the transaction request once
            # through the same retry-aware helper (so transient 5xx after the
            # refresh are still retried normally).
            return self._fetch_transactions_with_retry(params)

    @retry(
        retry=retry_if_exception_type(_RetryableHTTPError) | retry_if_exception_type(requests.exceptions.ConnectionError) | retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ChunkedEncodingError),
        stop=stop_after_attempt(5),
        wait=wait_combine(
            wait_exponential(multiplier=1, min=1, max=16),
            wait_random(0, 1),
        ),
        reraise=False,
    )
    def _fetch_transactions_with_retry(self, params: dict[str, str]) -> list[dict]:
        """Inner helper wrapped with tenacity retry for transient errors.

        Raises
        ------
        BankAuthError
            Immediately on HTTP 401 or 403 (no retry).
        _RetryableHTTPError
            On HTTP 5xx or 429 — tenacity will catch and retry.
        BankAPIError
            After all retries are exhausted (raised by tenacity's after_all_retries
            via the ``retry_error_callback``; see note below).
        """
        url = f"{_BASE_URL}/transactions"
        # Security: assert HTTPS before every outbound call (Req 7.2).
        assert url.startswith("https://"), f"Refusing non-HTTPS URL: {url}"

        try:
            response = requests.get(
                url,
                params=params,
                headers=self._auth_headers(),
                timeout=30,
            )
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as exc:
            # Re-raise so tenacity retries on network errors.
            raise

        status = response.status_code

        if status == 200:
            data: Any = response.json()
            # The API wraps the list in a "transactions" key or returns it directly.
            if isinstance(data, list):
                return data
            return data.get("transactions", [])

        if status in (401, 403):
            # Auth failure — do not retry; raise immediately.
            raise BankAuthError(
                f"{self._bank}: authentication failed (HTTP {status})"
            )

        if status == 429 or status >= 500:
            raise _RetryableHTTPError(status)

        # Any other 4xx: non-recoverable client error.
        raise BankAPIError(
            f"{self._bank}: API returned HTTP {status} after retries"
        )

    def _refresh_access_token(self) -> None:
        """POST to the token endpoint to obtain a new access token.

        Uses the stored refresh token.  On success, updates ``_access_token``
        and persists the new value in the Secret Store.

        Raises
        ------
        BankAuthError
            If the token endpoint returns 401 / 403, or if the response does
            not contain a usable access token (Req 1.4, 1.5).
        BankAPIError
            If the token endpoint returns a transient error after retries are
            exhausted (Req 1.6).
        """
        url = f"{_BASE_URL}/token"
        # Security: assert HTTPS before every outbound call (Req 7.2).
        assert url.startswith("https://"), f"Refusing non-HTTPS URL: {url}"

        try:
            response = self._post_token_with_retry(url)
        except _RetryableHTTPError as exc:
            raise BankAPIError(
                f"{self._bank}: API returned HTTP {exc.status} after retries"
            ) from exc

        status = response.status_code

        if status in (401, 403):
            # Security: do NOT include token value in message (Req 7.3/7.4).
            raise BankAuthError(
                f"{self._bank}: refresh token is invalid or expired"
            )

        if status != 200:
            raise BankAPIError(
                f"{self._bank}: API returned HTTP {status} after retries"
            )

        body: Any = response.json()
        new_token: str | None = body.get("access_token")

        if not new_token:
            # Response was 200 but contained no usable token.
            raise BankAuthError(
                f"{self._bank}: refresh token is invalid or expired"
            )

        # Persist the new token (Req 1.4).
        self._access_token = new_token
        self._secret_store.set(f"{self._bank_upper}_ACCESS_TOKEN", new_token)

    @retry(
        retry=retry_if_exception_type(_RetryableHTTPError) | retry_if_exception_type(requests.exceptions.ConnectionError) | retry_if_exception_type(requests.exceptions.Timeout) | retry_if_exception_type(requests.exceptions.ChunkedEncodingError),
        stop=stop_after_attempt(5),
        wait=wait_combine(
            wait_exponential(multiplier=1, min=1, max=16),
            wait_random(0, 1),
        ),
        reraise=True,
    )
    def _post_token_with_retry(self, url: str) -> requests.Response:
        """POST to the token endpoint with retry for transient errors.

        Returns the raw :class:`requests.Response`; the caller inspects the
        status code.  HTTP 5xx / 429 raises :exc:`_RetryableHTTPError` so
        tenacity retries.  Auth errors (401/403) are returned as-is so the
        caller can raise :exc:`BankAuthError` cleanly without a token value
        in the traceback.
        """
        assert url.startswith("https://"), f"Refusing non-HTTPS URL: {url}"

        try:
            response = requests.post(
                url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                timeout=30,
            )
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ):
            raise

        status = response.status_code
        if status == 429 or status >= 500:
            raise _RetryableHTTPError(status)

        # Return the response (200, 401, 403, or other 4xx) to the caller.
        return response

    def _auth_headers(self) -> dict[str, str]:
        """Return the ``Authorization`` header dict for API requests.

        The token value is passed only in the header; it is never logged or
        included in exception messages (Req 7.4).
        """
        return {"Authorization": f"Bearer {self._access_token}"}
