"""Tests for account-balance retrieval in the shared Enable Banking connector."""

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from banking.config.secret_store import SecretStore
from banking.connectors.enable_banking import (
    Balance,
    EnableBankingAPIError,
    EnableBankingConnector,
    RateLimitExceededError,
    _parse_balance,
    _select_balance,
)


class _FakeConnector(EnableBankingConnector):
    """Minimal concrete connector used to exercise the shared base class."""

    BANK_NAME = "Fake Bank"
    _SESSION_ID_KEY = "FAKE_SESSION_ID"


@pytest.fixture
def fake_session_id_in_store(
    mock_master_key: str, tmp_env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Store an encrypted ``FAKE_SESSION_ID`` secret ``_FakeConnector`` can read."""
    monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))
    session_id = "test-session-id"
    SecretStore(tmp_env_file).set("FAKE_SESSION_ID", session_id)
    return session_id


def _raw_balance(
    balance_type: str = "CLBD",
    amount: str | float = "1234.56",
    currency: str = "EUR",
    reference_date: str | None = "2026-10-24",
    name: str = "Closing booked balance",
) -> dict:
    raw: dict = {
        "name": name,
        "balance_amount": {"amount": amount, "currency": currency},
        "balance_type": balance_type,
        "last_change_date_time": "2026-10-24T10:00:00Z",
    }
    if reference_date is not None:
        raw["reference_date"] = reference_date
    return raw


def _parse_all(raws: list[dict]) -> list[Balance]:
    parsed = []
    for raw in raws:
        balance = _parse_balance(raw)
        if balance is not None:
            parsed.append(balance)
    return parsed


def _balances_handler(raws: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"balances": raws})


# ---------------------------------------------------------------------------
# Preferir el saldo contable de cierre y degradar con orden documentado
# ---------------------------------------------------------------------------


def test_preference_order_prefers_closing_booked_over_interim_booked():
    balances = _parse_all(
        [
            _raw_balance(balance_type="ITBD", amount="10.00"),
            _raw_balance(balance_type="CLBD", amount="99.00"),
        ]
    )

    selected = _select_balance(balances)

    assert selected is not None
    assert selected.balance_type == "CLBD"
    assert selected.amount == Decimal("99.00")


def test_preference_order_prefers_interim_booked_over_closing_available():
    balances = _parse_all(
        [
            _raw_balance(balance_type="CLAV", amount="10.00"),
            _raw_balance(balance_type="ITBD", amount="99.00"),
        ]
    )

    selected = _select_balance(balances)

    assert selected is not None
    assert selected.balance_type == "ITBD"
    assert selected.amount == Decimal("99.00")


def test_preference_order_prefers_closing_available_over_interim_available():
    balances = _parse_all(
        [
            _raw_balance(balance_type="ITAV", amount="10.00"),
            _raw_balance(balance_type="CLAV", amount="99.00"),
        ]
    )

    selected = _select_balance(balances)

    assert selected is not None
    assert selected.balance_type == "CLAV"
    assert selected.amount == Decimal("99.00")


def test_unknown_types_fall_back_to_first_provider_entry():
    balances = _parse_all(
        [
            _raw_balance(balance_type="ZZZZ", amount="1.00"),
            _raw_balance(balance_type="YYYY", amount="2.00"),
        ]
    )

    selected = _select_balance(balances)

    assert selected is not None
    assert selected.balance_type == "ZZZZ"
    assert selected.amount == Decimal("1.00")


def test_empty_balance_list_selects_nothing():
    assert _select_balance([]) is None


# ---------------------------------------------------------------------------
# Tolerar datos del proveedor malformados sin lanzar excepciones
# ---------------------------------------------------------------------------


def test_malformed_amount_is_skipped_and_next_valid_entry_selected():
    raws = [
        _raw_balance(balance_type="CLBD", amount="not-a-number"),
        _raw_balance(balance_type="CLBD", amount="77.50"),
    ]

    balances = _parse_all(raws)
    selected = _select_balance(balances)

    assert len(balances) == 1
    assert selected is not None
    assert selected.amount == Decimal("77.50")


def test_entry_without_balance_amount_is_skipped():
    raw: dict = {"balance_type": "CLBD", "reference_date": "2026-10-24"}

    assert _parse_balance(raw) is None


def test_non_mapping_entry_is_skipped():
    assert _parse_balance("not-a-dict") is None  # type: ignore[arg-type]


def test_missing_reference_date_yields_none_and_still_parses_amount():
    balance = _parse_balance(_raw_balance(reference_date=None, amount="42.10"))

    assert balance is not None
    assert balance.amount == Decimal("42.10")
    assert balance.currency == "EUR"
    assert balance.balance_type == "CLBD"
    assert balance.reference_date is None


def test_reference_date_is_parsed_when_present():
    balance = _parse_balance(_raw_balance(reference_date="2026-10-24"))

    assert balance is not None
    assert balance.reference_date == date(2026, 10, 24)


def test_numeric_non_string_amount_is_accepted():
    balance = _parse_balance(_raw_balance(amount=1234.56))

    assert balance is not None
    assert balance.amount == Decimal("1234.56")


def test_invalid_reference_date_is_tolerated():
    balance = _parse_balance(_raw_balance(reference_date="24/10/2026"))

    assert balance is not None
    assert balance.amount == Decimal("1234.56")
    assert balance.reference_date is None


def test_non_finite_amount_is_skipped():
    assert _parse_balance(_raw_balance(amount="NaN")) is None


# ---------------------------------------------------------------------------
# Consultar el saldo de la cuenta de la sesión
# ---------------------------------------------------------------------------


def test_fetch_balance_returns_selected_balance(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return _balances_handler(
            [
                _raw_balance(balance_type="ITBD", amount="10.00"),
                _raw_balance(balance_type="CLBD", amount="1234.56"),
            ]
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    balance = connector.fetch_balance()

    assert balance is not None
    assert balance.balance_type == "CLBD"
    assert balance.amount == Decimal("1234.56")
    assert balance.currency == "EUR"
    assert balance.reference_date == date(2026, 10, 24)
    assert seen_paths == ["/accounts/test-account-id/balances"]


def test_fetch_balance_returns_none_when_provider_reports_no_balances(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    connector = _FakeConnector(http_client=mock_http_client(lambda request: _balances_handler([])))

    assert connector.fetch_balance() is None


def test_fetch_balance_returns_none_when_response_has_no_balances_key(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    connector = _FakeConnector(
        http_client=mock_http_client(lambda request: httpx.Response(200, json={}))
    )

    assert connector.fetch_balance() is None


def test_fetch_balance_returns_none_when_all_entries_are_malformed(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return _balances_handler([_raw_balance(amount="nope")])

    connector = _FakeConnector(http_client=mock_http_client(handler))

    assert connector.fetch_balance() is None


def test_fetch_balance_http_error_raises_enable_banking_api_error(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal server error"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(EnableBankingAPIError):
            connector.fetch_balance()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    assert "Fake Bank" in error_records[0].getMessage()


def test_fetch_balance_rate_limited_raises_rate_limit_exceeded(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "too many requests"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(RateLimitExceededError):
        connector.fetch_balance()
