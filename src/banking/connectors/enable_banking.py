"""Shared Enable Banking PSD2 connector logic: RS256 JWT auth, session lifecycle,
pagination, normalization."""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from banking.config.secret_store import SecretStore

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.enablebanking.com"
_JWT_ISSUER = "enablebanking.com"
_JWT_AUDIENCE = "api.enablebanking.com"
_CONFIG_DIR_ENV = "BANKING_EB_CONFIG_DIR"
_DEFAULT_CONFIG_DIR = Path.home() / ".config" / "banca-personal"
_JWT_TTL_SECONDS = 300
_MAX_PAGES = 100


class ConnectorConfigError(Exception):
    """Raised when eb-config.json or its referenced private key are missing/invalid."""


class InvalidDateRangeError(Exception):
    """Raised when start_date is after end_date."""


class ReauthorizationRequiredError(Exception):
    """Raised when the PSD2 session is rejected (403) or reported as expired."""


class RateLimitExceededError(Exception):
    """Raised on HTTP 429 — the PSD2 daily request quota (4/account/day) was exceeded."""


class EnableBankingAPIError(Exception):
    """Raised on any other unexpected HTTP error status from Enable Banking."""


class PaginationLimitExceededError(Exception):
    """Raised when MAX_PAGES is reached without the API exhausting continuation_key."""


@dataclass(frozen=True)
class Transaction:
    """A single normalized, settled (BOOK) account movement."""

    booking_date: date
    amount: Decimal
    currency: str
    description: str


@dataclass(frozen=True)
class _SigningCredential:
    app_id: str
    private_key: Any


def _resolve_config_dir(config_dir: Path | None) -> Path:
    if config_dir is not None:
        return config_dir
    env_value = os.environ.get(_CONFIG_DIR_ENV)
    if env_value:
        return Path(env_value)
    return _DEFAULT_CONFIG_DIR


def _load_signing_credential(config_dir: Path | None) -> _SigningCredential:
    """Load app_id + RSA private key from eb-config.json.

    Raises:
        ConnectorConfigError: if the file, its required fields, or the
            referenced private key are missing or invalid.
    """
    resolved_dir = _resolve_config_dir(config_dir)
    config_file = resolved_dir / "eb-config.json"
    if not config_file.is_file():
        raise ConnectorConfigError(f"Enable Banking config file not found at '{config_file}'.")

    try:
        raw = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConnectorConfigError(
            f"Enable Banking config file '{config_file}' is not valid JSON."
        ) from exc

    app_id = raw.get("app_id")
    private_key_path = raw.get("private_key_path")
    if not app_id or not private_key_path:
        raise ConnectorConfigError(
            f"Enable Banking config file '{config_file}' is missing 'app_id' or 'private_key_path'."
        )

    key_path = Path(private_key_path).expanduser()
    if not key_path.is_file():
        raise ConnectorConfigError(f"Enable Banking private key file not found at '{key_path}'.")

    try:
        private_key = load_pem_private_key(key_path.read_bytes(), password=None)
    except ValueError as exc:
        raise ConnectorConfigError(
            f"Enable Banking private key at '{key_path}' is not a valid private key."
        ) from exc

    return _SigningCredential(app_id=app_id, private_key=private_key)


def _build_jwt(credential: _SigningCredential) -> str:
    """Build a short-lived RS256-signed JWT. Never logs the key or the token."""
    now = int(time.time())
    claims = {
        "iss": _JWT_ISSUER,
        "aud": _JWT_AUDIENCE,
        "iat": now,
        "exp": now + _JWT_TTL_SECONDS,
    }
    return jwt.encode(
        claims,
        credential.private_key,
        algorithm="RS256",
        headers={"kid": credential.app_id},
    )


def _join_remittance_information(raw_remittance: object) -> str:
    """Enable Banking returns ``remittance_information`` as a list of lines."""
    if isinstance(raw_remittance, list):
        return " ".join(str(line) for line in raw_remittance)
    return str(raw_remittance) if raw_remittance else ""


def _parse_transaction(raw: dict[str, Any]) -> Transaction | None:
    """Parse one API transaction record into a Transaction, or None if malformed."""
    try:
        amount_block = raw["transaction_amount"]
        indicator = raw["credit_debit_indicator"]
        magnitude = Decimal(str(amount_block["amount"]))
        currency = amount_block["currency"]
        booking_date = date.fromisoformat(raw["booking_date"])
        description = _join_remittance_information(raw.get("remittance_information", []))
    except (KeyError, InvalidOperation, ValueError) as exc:
        logger.warning("Skipping transaction record with missing or invalid fields: %s", exc)
        return None

    if indicator == "DBIT":
        magnitude = -magnitude
    elif indicator != "CRDT":
        logger.warning(
            "Skipping transaction record with unknown credit/debit indicator: %s",
            indicator,
        )
        return None

    return Transaction(
        booking_date=booking_date, amount=magnitude, currency=currency, description=description
    )


def _check_session_usable(response: httpx.Response) -> None:
    """Raise ReauthorizationRequiredError if the PSD2 session is unusable.

    Triggers on HTTP 403, or on a 200 response whose body reports a session
    ``status`` of ``"expired"``.
    """
    if response.status_code == 403:
        raise ReauthorizationRequiredError(
            "Enable Banking rejected the PSD2 session (HTTP 403). Manual "
            "re-authorization via the bank's browser consent flow is required."
        )
    if response.status_code == 429:
        raise RateLimitExceededError(
            "Enable Banking PSD2 daily request limit exceeded (HTTP 429). Only 4 "
            "requests per account per day are allowed by regulation."
        )
    if response.status_code == 200:
        try:
            body = response.json()
        except ValueError:
            return
        if isinstance(body, dict) and body.get("status") == "expired":
            raise ReauthorizationRequiredError(
                "Enable Banking reports the PSD2 session as expired. Manual "
                "re-authorization via the bank's browser consent flow is required."
            )
        return
    raise EnableBankingAPIError(
        f"Enable Banking returned an unexpected HTTP status: {response.status_code}."
    )


class EnableBankingConnector:
    """Shared connector logic for any bank account reachable via the Enable
    Banking PSD2 API. Subclasses fix ``BANK_NAME`` and ``_SESSION_ID_KEY``.
    """

    BANK_NAME: str
    _SESSION_ID_KEY: str

    def __init__(
        self, http_client: httpx.Client | None = None, config_dir: Path | None = None
    ) -> None:
        self._http_client = http_client if http_client is not None else httpx.Client()
        self._config_dir = config_dir

    def _resolve_account_id(
        self, credential: _SigningCredential, session_id: str, start_date: date, end_date: date
    ) -> str:
        """Look up the session's linked account, translating unusable-session errors."""
        token = _build_jwt(credential)
        response = self._http_client.get(
            f"{_BASE_URL}/sessions/{session_id}", headers={"Authorization": f"Bearer {token}"}
        )
        try:
            _check_session_usable(response)
        except (
            ReauthorizationRequiredError,
            RateLimitExceededError,
            EnableBankingAPIError,
        ) as exc:
            logger.error(
                "Connector %s: range %s to %s, status=error, reason=%s",
                self.BANK_NAME,
                start_date.isoformat(),
                end_date.isoformat(),
                exc,
            )
            raise

        accounts = response.json().get("accounts") or []
        if not accounts:
            raise EnableBankingAPIError("Enable Banking session has no linked accounts.")
        return str(accounts[0])

    def fetch_transactions(self, start_date: date, end_date: date) -> list[Transaction]:
        """Return all settled (BOOK) transactions in [start_date, end_date]."""
        if start_date > end_date:
            raise InvalidDateRangeError(
                f"start_date ({start_date.isoformat()}) must not be after "
                f"end_date ({end_date.isoformat()})."
            )

        credential = _load_signing_credential(self._config_dir)
        session_id = SecretStore().get(self._SESSION_ID_KEY)
        account_id = self._resolve_account_id(credential, session_id, start_date, end_date)

        results: dict[tuple[date, Decimal, str], Transaction] = {}
        continuation_key: str | None = None
        url = f"{_BASE_URL}/accounts/{account_id}/transactions"

        for _page_number in range(_MAX_PAGES):
            token = _build_jwt(credential)
            params: dict[str, str] = {
                "date_from": start_date.isoformat(),
                "date_to": end_date.isoformat(),
            }
            if continuation_key:
                params["continuation_key"] = continuation_key

            response = self._http_client.get(
                url, params=params, headers={"Authorization": f"Bearer {token}"}
            )
            try:
                _check_session_usable(response)
            except (
                ReauthorizationRequiredError,
                RateLimitExceededError,
                EnableBankingAPIError,
            ) as exc:
                logger.error(
                    "Connector %s: range %s to %s, status=error, reason=%s",
                    self.BANK_NAME,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    exc,
                )
                raise

            body = response.json()

            for raw_tx in body.get("transactions", []):
                if raw_tx.get("status") != "BOOK":
                    continue
                tx = _parse_transaction(raw_tx)
                if tx is None:
                    continue
                if not (start_date <= tx.booking_date <= end_date):
                    continue
                key = (tx.booking_date, tx.amount, tx.description)
                results.setdefault(key, tx)

            continuation_key = body.get("continuation_key")
            if not continuation_key:
                break
        else:
            logger.error(
                "Connector %s: range %s to %s, status=error, reason=%s",
                self.BANK_NAME,
                start_date.isoformat(),
                end_date.isoformat(),
                f"pagination limit of {_MAX_PAGES} pages exceeded without exhausting "
                "continuation_key",
            )
            raise PaginationLimitExceededError(
                f"Enable Banking pagination did not stop after {_MAX_PAGES} pages "
                "(continuation_key kept being returned)."
            )

        transactions = list(results.values())
        logger.info(
            "Connector %s: range %s to %s, %d records retrieved, status=success",
            self.BANK_NAME,
            start_date.isoformat(),
            end_date.isoformat(),
            len(transactions),
        )
        return transactions
