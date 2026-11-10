"""Shared Enable Banking PSD2 connector logic: RS256 JWT auth, session lifecycle,
pagination, normalization."""

import json
import logging
import os
import time
from collections.abc import Sequence
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

# Closing booked (CLBD) is the most trustworthy: it is the settled end-of-period
# balance, unlike interim (ITBD) or available (CLAV/ITAV) figures.
_BALANCE_PREFERENCE: tuple[str, ...] = (
    "CLBD",
    "ITBD",
    "CLAV",
    "ITAV",
    "OPBD",
    "OPAV",
    "FWAV",
    "XPCD",
)


_MAX_ERROR_DETAIL_CHARS = 300

#: Inert value documented in docs/credentials-setup.md section 6 for a bank whose
#: PSD2 consent does not exist yet. It keeps the workflow's secret check satisfied;
#: it is not a session id and must never be sent to the provider.
_UNCONFIGURED_SESSION_ID = "unconfigured"


class ConnectorConfigError(Exception):
    """Raised when the connector configuration is missing or unusable.

    Covers a missing or invalid eb-config.json, its private key, and a session id
    still holding the inert ``unconfigured`` placeholder.
    """


class BankNotOnboardedError(ConnectorConfigError):
    """Raised when a bank has no PSD2 session yet; a normal state, not a failure.

    The bank's authorization is still pending, so there is nothing to fetch and
    nothing to fix on every run. It subclasses `ConnectorConfigError` so every
    existing ``except ConnectorConfigError`` keeps working, and it exists as its
    own type so callers can tell "not onboarded" apart from a real configuration
    break (a missing or empty secret), which must stay loud.
    """


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
    merchant_category_code: str | None = None


@dataclass(frozen=True)
class Balance:
    """A single account balance reported by Enable Banking."""

    amount: Decimal
    currency: str
    balance_type: str
    reference_date: date | None


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


def _log_seen_transaction_fields(bank_name: str, record_count: int, field_names: set[str]) -> None:
    """Log which transaction fields a bank actually returned, names only.

    Deliberately INFO: the Actions run log is where the answer has to be
    readable, and a scheduled run cannot raise ``LOG_LEVEL``. Only field names
    reach the log — never values, so no amount, date, remittance text or
    reference can leak.

    Args:
        bank_name: The bank the records belong to.
        record_count: How many transaction records the fetch saw.
        field_names: The union of the key names present in those records.
    """
    if record_count == 0:
        return
    logger.info(
        "Connector %s: transaction fields, records=%d, keys=%s",
        bank_name,
        record_count,
        ",".join(sorted(field_names)),
    )


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
        booking_date=booking_date,
        amount=magnitude,
        currency=currency,
        description=description,
        merchant_category_code=_optional_text(raw, "merchant_category_code"),
    )


def _optional_text(raw: dict[str, Any], key: str) -> str | None:
    """An optional string record member: present non-blank text, else None.

    Optional provider data must never abort the whole record: any non-string
    value a provider sends anyway is logged at debug and treated as missing.
    """
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        logger.debug("Ignoring non-string optional field %s: %r", key, value)
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _parse_balance(raw: dict[str, Any]) -> Balance | None:
    """Parse one API balance record into a Balance, or None if unusable.

    Never raises on malformed provider data: an entry that is not a mapping, has
    no usable ``balance_amount``, or whose amount is not a finite decimal is
    skipped. A missing or unparseable ``reference_date`` is tolerated (None).
    """
    if not isinstance(raw, dict):
        logger.warning("Skipping balance record that is not a mapping: %r", raw)
        return None

    try:
        amount_block = raw["balance_amount"]
        if not isinstance(amount_block, dict):
            raise KeyError("balance_amount")
        amount = Decimal(str(amount_block["amount"]))
        currency = str(amount_block["currency"])
    except (KeyError, InvalidOperation, ValueError, TypeError) as exc:
        logger.warning("Skipping balance record with missing or invalid fields: %s", exc)
        return None

    if not amount.is_finite():
        logger.warning("Skipping balance record with a non-finite amount: %s", amount)
        return None

    balance_type = raw.get("balance_type")
    reference_date: date | None = None
    raw_reference_date = raw.get("reference_date")
    if raw_reference_date is not None:
        try:
            reference_date = date.fromisoformat(str(raw_reference_date))
        except ValueError:
            logger.warning("Balance record has an invalid reference_date: %r", raw_reference_date)

    return Balance(
        amount=amount,
        currency=currency,
        balance_type=str(balance_type) if balance_type else "",
        reference_date=reference_date,
    )


def _select_balance(balances: Sequence[Balance]) -> Balance | None:
    """Pick one balance by the documented preference order, first match wins.

    Unknown or absent types degrade to the first entry in provider order so an
    unexpected vocabulary yields a value instead of an empty cell.
    """
    if not balances:
        return None

    by_type: dict[str, Balance] = {}
    for balance in balances:
        by_type.setdefault(balance.balance_type.upper(), balance)

    for preferred_type in _BALANCE_PREFERENCE:
        match = by_type.get(preferred_type)
        if match is not None:
            return match

    return balances[0]


def _provider_detail(response: httpx.Response) -> str:
    """Return a compact, single-line excerpt of the provider's error detail.

    Enable Banking answers with a structured JSON error body; whatever sits in
    front of it (a proxy, a CDN) may answer with HTML instead. Either way the
    excerpt is informational and ends up in a log line, so it must never raise,
    never span multiple lines, and never grow past a bounded length.

    Returns an empty string when the body carries nothing usable.
    """
    try:
        body: object = response.json()
    except ValueError:
        body = None

    text = ""
    if isinstance(body, dict):
        parts = [
            str(body[key]).strip()
            for key in ("error", "message", "detail", "error_description", "title")
            if isinstance(body.get(key), (str, int, float)) and str(body[key]).strip()
        ]
        text = ": ".join(dict.fromkeys(parts))
    if not text:
        try:
            text = response.text
        except (UnicodeDecodeError, ValueError):
            text = ""

    collapsed = " ".join(text.split())
    if len(collapsed) > _MAX_ERROR_DETAIL_CHARS:
        return collapsed[:_MAX_ERROR_DETAIL_CHARS] + "..."
    return collapsed


def _detail_suffix(response: httpx.Response) -> str:
    """Return the provider detail prefixed for a message, or an empty string."""
    detail = _provider_detail(response)
    return f" Provider detail: {detail}." if detail else ""


def _is_unconfigured_session(session_id: str) -> bool:
    """Return True when the session id is still the inert documented placeholder."""
    return session_id.strip().lower() == _UNCONFIGURED_SESSION_ID


def _describe_session_id(session_id: str) -> str:
    """Describe the shape of a session id without revealing its value.

    A 422 on the session lookup means the provider rejected the parameters, and
    the session id is the parameter in question. These four facts are enough to
    tell a truncated value, a stray newline, or an empty secret apart from a
    genuinely stale consent, and none of them exposes the secret itself.
    """
    stripped = session_id.strip()
    return (
        "Session id shape: "
        f"length={len(session_id)}, "
        f"empty={not stripped}, "
        f"surrounding-whitespace={session_id != stripped}, "
        f"non-ascii={not session_id.isascii()}."
    )


def _check_session_usable(response: httpx.Response, *, context: str = "") -> None:
    """Raise ReauthorizationRequiredError if the PSD2 session is unusable.

    Triggers on HTTP 403, or on a 200 response whose body reports a session
    ``status`` of ``"expired"``. ``context`` is appended to the 422 message,
    where the caller can describe which parameters the provider rejected.
    """
    if response.status_code == 403:
        raise ReauthorizationRequiredError(
            "Enable Banking rejected the PSD2 session (HTTP 403). Manual "
            "re-authorization via the bank's browser consent flow is required."
            f"{_detail_suffix(response)}"
        )
    if response.status_code == 429:
        raise RateLimitExceededError(
            "Enable Banking PSD2 daily request limit exceeded (HTTP 429). Only 4 "
            f"requests per account per day are allowed by regulation.{_detail_suffix(response)}"
        )
    if response.status_code == 422:
        note = f" {context}" if context else ""
        raise EnableBankingAPIError(
            "Enable Banking rejected the request parameters (HTTP 422)."
            f"{_detail_suffix(response)}{note} A 422 is not a credentials problem: "
            "the signature was accepted and the request understood, so a parameter "
            "is wrong. If the session is stale, re-authorize the bank through its "
            "browser consent flow (docs/credentials-setup.md, section 3)."
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
                f"{_detail_suffix(response)}"
            )
        return
    raise EnableBankingAPIError(
        f"Enable Banking returned an unexpected HTTP status: {response.status_code}."
        f"{_detail_suffix(response)}"
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
        # Session resolution cache. A daily pass calls ``fetch_transactions`` and
        # then ``fetch_balance`` on the same instance, and resolving the account
        # costs a ``GET /sessions/{id}`` against the PSD2 daily budget, so the
        # three inputs are resolved once and reused. A failed resolution leaves
        # the slot empty, so the next call retries from scratch.
        self._credential: _SigningCredential | None = None
        self._session_id: str | None = None
        self._account_id: str | None = None

    def _resolve_session(self, start_date: date, end_date: date) -> tuple[_SigningCredential, str]:
        """Return the signing credential and the linked account, resolved once per instance.

        Reusing the resolved values across the two stages of one run is what keeps
        a daily pass inside the PSD2 request budget. Only a successful resolution
        is cached: every exception leaves the slot untouched so the next call
        retries.

        Args:
            start_date: First date of the range; used only for error logging.
            end_date: Last date of the range; used only for error logging.

        Returns:
            The signing credential and the id of the session's linked account.
        """
        if self._credential is None:
            self._credential = _load_signing_credential(self._config_dir)
        if self._session_id is None:
            self._session_id = SecretStore().get(self._SESSION_ID_KEY)
        if self._account_id is None:
            self._account_id = self._resolve_account_id(
                self._credential, self._session_id, start_date, end_date
            )
        return self._credential, self._account_id

    def _resolve_account_id(
        self, credential: _SigningCredential, session_id: str, start_date: date, end_date: date
    ) -> str:
        """Look up the session's linked account, translating unusable-session errors."""
        if _is_unconfigured_session(session_id):
            raise BankNotOnboardedError(
                f"{self.BANK_NAME} has no PSD2 session configured: the secret still "
                "holds the inert placeholder documented in docs/credentials-setup.md "
                "section 6. Authorize the bank to read its data (section 3)."
            )
        token = _build_jwt(credential)
        response = self._http_client.get(
            f"{_BASE_URL}/sessions/{session_id}", headers={"Authorization": f"Bearer {token}"}
        )
        try:
            _check_session_usable(response, context=_describe_session_id(session_id))
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

    def fetch_balance(self) -> Balance | None:
        """Return the account's most trustworthy reported balance, or None.

        PSD2 reports the balance of the moment it is requested; there is no
        month-end historical balance. ``None`` means the provider reported no
        usable balance for this account.
        """
        # Balances are not date-ranged; the account lookup reuses the existing
        # machinery, which only needs a date pair for its error logging.
        today = date.today()
        credential, account_id = self._resolve_session(today, today)

        token = _build_jwt(credential)
        response = self._http_client.get(
            f"{_BASE_URL}/accounts/{account_id}/balances",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            _check_session_usable(response)
        except (
            ReauthorizationRequiredError,
            RateLimitExceededError,
            EnableBankingAPIError,
        ) as exc:
            logger.error(
                "Connector %s: balances, as of %s, status=error, reason=%s",
                self.BANK_NAME,
                today.isoformat(),
                exc,
            )
            raise

        payload = response.json()
        raw_balances = payload.get("balances") if isinstance(payload, dict) else None
        if not isinstance(raw_balances, list):
            raw_balances = []

        balances = [
            balance
            for balance in (_parse_balance(raw) for raw in raw_balances)
            if balance is not None
        ]
        selected = _select_balance(balances)

        if selected is None:
            logger.info(
                "Connector %s: balances, as of %s, no usable balance reported (raw entries: %d)",
                self.BANK_NAME,
                today.isoformat(),
                len(raw_balances),
            )
            return None

        logger.info(
            "Connector %s: balances, as of %s, %s %s (%s), status=success",
            self.BANK_NAME,
            today.isoformat(),
            selected.amount,
            selected.currency,
            selected.balance_type or "unknown type",
        )
        return selected

    def fetch_transactions(self, start_date: date, end_date: date) -> list[Transaction]:
        """Return all settled (BOOK) transactions in [start_date, end_date]."""
        if start_date > end_date:
            raise InvalidDateRangeError(
                f"start_date ({start_date.isoformat()}) must not be after "
                f"end_date ({end_date.isoformat()})."
            )

        credential, account_id = self._resolve_session(start_date, end_date)

        results: dict[tuple[date, Decimal, str], Transaction] = {}
        seen_field_names: set[str] = set()
        seen_record_count = 0
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
                seen_record_count += 1
                seen_field_names.update(raw_tx.keys())
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
        _log_seen_transaction_fields(self.BANK_NAME, seen_record_count, seen_field_names)
        logger.info(
            "Connector %s: range %s to %s, %d records retrieved, status=success",
            self.BANK_NAME,
            start_date.isoformat(),
            end_date.isoformat(),
            len(transactions),
        )
        return transactions
