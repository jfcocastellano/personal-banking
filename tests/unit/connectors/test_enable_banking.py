"""Tests for the shared Enable Banking PSD2 connector logic (base class)."""

import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from banking.config.secret_store import SecretStore
from banking.connectors.enable_banking import (
    BankNotOnboardedError,
    ConnectorConfigError,
    EnableBankingAPIError,
    EnableBankingConnector,
    InvalidDateRangeError,
    PaginationLimitExceededError,
    RateLimitExceededError,
    ReauthorizationRequiredError,
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


def _raw_tx(
    status: str = "BOOK",
    booking_date: str = "2026-08-15",
    amount: str = "42.50",
    currency: str = "EUR",
    indicator: str = "CRDT",
    description: str = "Test tx",
    merchant_category_code: str | None = None,
) -> dict:
    raw = {
        "status": status,
        "booking_date": booking_date,
        "transaction_amount": {"amount": amount, "currency": currency},
        "credit_debit_indicator": indicator,
        "remittance_information": [description] if description else [],
    }
    if merchant_category_code is not None:
        raw["merchant_category_code"] = merchant_category_code
    return raw


# ---------------------------------------------------------------------------
# Obtener movimientos liquidados en un rango de fechas
# ---------------------------------------------------------------------------


def test_single_page_filters_and_normalizes(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transactions": [
                    _raw_tx(status="BOOK", indicator="CRDT", amount="42.50", description="Nomina"),
                    _raw_tx(
                        status="PDNG", indicator="DBIT", amount="10.00", description="Pendiente"
                    ),
                    _raw_tx(status="INFO", indicator="DBIT", amount="5.00", description="Info"),
                    _raw_tx(status="BOOK", indicator="DBIT", amount="20.00", description="Compra"),
                ],
                "continuation_key": None,
            },
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert len(result) == 2
    by_description = {tx.description: tx for tx in result}
    assert by_description["Nomina"].amount == Decimal("42.50")
    assert by_description["Compra"].amount == Decimal("-20.00")
    assert all(tx.currency == "EUR" for tx in result)


def test_multi_page_pagination_combines_results(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            assert request.url.params.get("continuation_key") is None
            return httpx.Response(
                200,
                json={
                    "transactions": [_raw_tx(description="Page1 Tx")],
                    "continuation_key": "abc123",
                },
            )
        assert request.url.params.get("continuation_key") == "abc123"
        return httpx.Response(
            200,
            json={"transactions": [_raw_tx(description="Page2 Tx")], "continuation_key": None},
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert {tx.description for tx in result} == {"Page1 Tx", "Page2 Tx"}
    assert call_count["n"] == 2


def test_date_range_inclusive_on_both_ends(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transactions": [
                    _raw_tx(booking_date="2026-07-31", description="Before range"),
                    _raw_tx(booking_date="2026-08-01", description="Start day"),
                    _raw_tx(booking_date="2026-08-31", description="End day"),
                    _raw_tx(booking_date="2026-09-01", description="After range"),
                ],
                "continuation_key": None,
            },
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert {tx.description for tx in result} == {"Start day", "End day"}


def test_empty_range_returns_empty_list(eb_config_dir, fake_session_id_in_store, mock_http_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [], "continuation_key": None})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert result == []


def test_merchant_category_code_is_kept_as_a_field(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transactions": [
                    _raw_tx(description="Supermercado", merchant_category_code="5411")
                ],
                "continuation_key": None,
            },
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert [tx.merchant_category_code for tx in result] == ["5411"]


def test_absent_merchant_category_code_parses_as_none(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"transactions": [_raw_tx(description="Sin codigo")], "continuation_key": None},
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert [tx.merchant_category_code for tx in result] == [None]


def test_malformed_merchant_category_code_does_not_drop_the_record(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        raw = _raw_tx(description="Compra con categoria rota")
        raw["merchant_category_code"] = 5411
        return httpx.Response(
            200,
            json={"transactions": [raw], "continuation_key": None},
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    # The malformed category degrades to None; the record itself survives.
    assert [tx.description for tx in result] == ["Compra con categoria rota"]
    assert [tx.merchant_category_code for tx in result] == [None]


def test_deduplicates_transaction_repeated_across_page_boundary(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    call_count = {"n": 0}
    dup = _raw_tx(booking_date="2026-08-15", amount="42.50", description="Dup Tx")

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(200, json={"transactions": [dup], "continuation_key": "page2"})
        return httpx.Response(
            200,
            json={
                "transactions": [dup, _raw_tx(description="Unique Tx", booking_date="2026-08-16")],
                "continuation_key": None,
            },
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    descriptions = [tx.description for tx in result]
    assert descriptions.count("Dup Tx") == 1
    assert "Unique Tx" in descriptions
    assert len(result) == 2


def test_success_logs_structured_record(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [_raw_tx()], "continuation_key": None})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.INFO, logger="banking.connectors.enable_banking"):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    success_records = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO and "records retrieved" in record.getMessage()
    ]
    assert len(success_records) == 1
    message = success_records[0]
    assert "Fake Bank" in message
    assert "2026-08-01" in message
    assert "2026-08-31" in message
    assert "1" in message


# ---------------------------------------------------------------------------
# Registrar qué campos devuelve cada banco, sin filtrar valores
# ---------------------------------------------------------------------------


def _field_probe_lines(caplog) -> list[str]:
    """Only the field-name probe lines, so value assertions cannot hit other logs."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.INFO and "keys=" in record.getMessage()
    ]


def test_fetch_logs_the_field_names_each_record_carries(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    record_payload = {
        "status": "BOOK",
        "booking_date": "2026-08-15",
        "transaction_amount": {"amount": "42.50", "currency": "EUR"},
        "credit_debit_indicator": "DBIT",
        "remittance_information": ["NOMINA CONFIDENCIAL SL"],
        "merchant_category_code": "5411",
        "entry_reference": "REF-UNICA-0001",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"transactions": [record_payload], "continuation_key": None}
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.INFO, logger="banking.connectors.enable_banking"):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    probe_lines = _field_probe_lines(caplog)
    assert len(probe_lines) == 1
    line = probe_lines[0]
    assert "Fake Bank" in line
    assert "records=1" in line
    for field_name in ("status", "merchant_category_code", "entry_reference"):
        assert field_name in line, f"the probe must name {field_name}: {line}"
    for value in (
        "5411",
        "REF-UNICA-0001",
        "NOMINA CONFIDENCIAL SL",
        "42.50",
        "2026-08-15",
    ):
        assert value not in line, f"the probe must never log values, leaked {value}: {line}"


def test_fetch_logs_no_field_probe_when_the_account_returns_no_records(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [], "continuation_key": None})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.INFO, logger="banking.connectors.enable_banking"):
        result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert result == []
    assert _field_probe_lines(caplog) == []


def test_fetch_logs_the_field_probe_even_when_every_record_is_filtered_out(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "transactions": [_raw_tx(status="PDNG", description="Pendiente")],
                "continuation_key": None,
            },
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.INFO, logger="banking.connectors.enable_banking"):
        result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert result == []
    probe_lines = _field_probe_lines(caplog)
    assert len(probe_lines) == 1
    assert "records=1" in probe_lines[0]
    assert "status" in probe_lines[0]


def test_fetch_logs_the_field_probe_once_per_fetch_not_once_per_page(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "transactions": [_raw_tx(description="Page1 Tx")],
                    "continuation_key": "page2",
                },
            )
        return httpx.Response(
            200,
            json={"transactions": [_raw_tx(description="Page2 Tx")], "continuation_key": None},
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.INFO, logger="banking.connectors.enable_banking"):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    probe_lines = _field_probe_lines(caplog)
    assert len(probe_lines) == 1
    assert "records=2" in probe_lines[0]


def test_start_after_end_raises_before_http_call(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"transactions": [], "continuation_key": None})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(InvalidDateRangeError):
        connector.fetch_transactions(date(2026, 8, 31), date(2026, 8, 1))

    assert called["n"] == 0


def test_malformed_record_skipped_with_warning(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    good = _raw_tx(description="Good Tx")
    bad = {"status": "BOOK", "booking_date": "2026-08-15"}  # missing amount/currency/indicator

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [bad, good], "continuation_key": None})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.WARNING, logger="banking.connectors.enable_banking"):
        result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert len(result) == 1
    assert result[0].description == "Good Tx"
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_missing_eb_config_file_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_session_id_in_store, mock_http_client
):
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(tmp_path / "does-not-exist"))

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No debe realizarse ninguna llamada HTTP")

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


def test_invalid_json_eb_config_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_session_id_in_store, mock_http_client
):
    config_dir = tmp_path / "banca-personal"
    config_dir.mkdir()
    (config_dir / "eb-config.json").write_text("not valid json{", encoding="utf-8")
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(config_dir))

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No debe realizarse ninguna llamada HTTP")

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


def test_missing_required_fields_in_eb_config_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_session_id_in_store, mock_http_client
):
    config_dir = tmp_path / "banca-personal"
    config_dir.mkdir()
    (config_dir / "eb-config.json").write_text(json.dumps({"app_id": "x"}), encoding="utf-8")
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(config_dir))

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No debe realizarse ninguna llamada HTTP")

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


def test_private_key_file_missing_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_session_id_in_store, mock_http_client
):
    config_dir = tmp_path / "banca-personal"
    config_dir.mkdir()
    (config_dir / "eb-config.json").write_text(
        json.dumps({"app_id": "x", "private_key_path": str(config_dir / "missing.pem")}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(config_dir))

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No debe realizarse ninguna llamada HTTP")

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


def test_invalid_private_key_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_session_id_in_store, mock_http_client
):
    config_dir = tmp_path / "banca-personal"
    config_dir.mkdir()
    bad_key_path = config_dir / "private.pem"
    bad_key_path.write_text("not a real key", encoding="utf-8")
    (config_dir / "eb-config.json").write_text(
        json.dumps({"app_id": "x", "private_key_path": str(bad_key_path)}), encoding="utf-8"
    )
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(config_dir))

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No debe realizarse ninguna llamada HTTP")

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


# ---------------------------------------------------------------------------
# Detectar una sesión inutilizable y fallar con claridad
# ---------------------------------------------------------------------------


def test_http_403_raises_reauthorization_required(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(ReauthorizationRequiredError, match="re-authoriz|browser"):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "Fake Bank" in message
    assert "2026-08-01" in message
    assert "2026-08-31" in message


def test_expired_session_status_raises_reauthorization_required(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "expired"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(ReauthorizationRequiredError, match="re-authoriz|browser"):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_session_expires_mid_pagination_returns_no_partial_data(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "transactions": [_raw_tx(description="Page1 Tx")],
                    "continuation_key": "abc123",
                },
            )
        return httpx.Response(403, json={"error": "forbidden"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(ReauthorizationRequiredError):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert call_count["n"] == 2
    assert any(r.levelno == logging.ERROR for r in caplog.records)


# ---------------------------------------------------------------------------
# Respetar el límite de peticiones PSD2 e informar con claridad
# ---------------------------------------------------------------------------


def test_http_429_on_initial_request_raises_rate_limit_exceeded(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "too many requests"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(RateLimitExceededError, match="4|daily|PSD2"):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "Fake Bank" in message
    assert "2026-08-01" in message
    assert "2026-08-31" in message


def test_http_429_on_pagination_request_raises_rate_limit_exceeded(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return httpx.Response(
                200,
                json={
                    "transactions": [_raw_tx(description="Page1 Tx")],
                    "continuation_key": "abc123",
                },
            )
        return httpx.Response(429, json={"error": "too many requests"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(RateLimitExceededError):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert call_count["n"] == 2
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_unexpected_http_error_raises_enable_banking_api_error(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal server error"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(EnableBankingAPIError):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "Fake Bank" in message
    assert "2026-08-01" in message
    assert "2026-08-31" in message


# ---------------------------------------------------------------------------
# Salvaguarda de paginación
# ---------------------------------------------------------------------------


def test_pagination_never_stopping_raises_pagination_limit_exceeded(
    eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [], "continuation_key": "always-more"})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(PaginationLimitExceededError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


# ---------------------------------------------------------------------------
# Redacción de secretos en logs
# ---------------------------------------------------------------------------


def test_no_secrets_leak_into_logs_across_all_scenarios(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client, rsa_private_key_pem
):
    captured_auth_headers: list[str] = []

    def make_handler(build_response):
        def handler(request: httpx.Request) -> httpx.Response:
            captured_auth_headers.append(request.headers.get("Authorization", ""))
            return build_response(request)

        return handler

    scenario_responses = [
        lambda request: httpx.Response(
            200, json={"transactions": [_raw_tx()], "continuation_key": None}
        ),
        lambda request: httpx.Response(403, json={"error": "forbidden"}),
        lambda request: httpx.Response(200, json={"status": "expired"}),
        lambda request: httpx.Response(429, json={"error": "too many requests"}),
        lambda request: httpx.Response(500, json={"error": "internal server error"}),
    ]

    with caplog.at_level(logging.DEBUG, logger="banking.connectors.enable_banking"):
        for build_response in scenario_responses:
            connector = _FakeConnector(http_client=mock_http_client(make_handler(build_response)))
            try:
                connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))
            except (ReauthorizationRequiredError, RateLimitExceededError, EnableBankingAPIError):
                pass

    all_log_text = "\n".join(r.getMessage() for r in caplog.records)

    pem_text = rsa_private_key_pem.decode("utf-8")
    assert pem_text not in all_log_text
    assert fake_session_id_in_store not in all_log_text
    assert len(captured_auth_headers) >= len(scenario_responses)
    for header_value in captured_auth_headers:
        token = header_value.removeprefix("Bearer ")
        assert token, "expected a JWT to have been sent on every request"
        assert token not in all_log_text


# ---------------------------------------------------------------------------
# Reportar el detalle del proveedor cuando la API falla
# ---------------------------------------------------------------------------


def _ok_handler(request: httpx.Request) -> httpx.Response:
    """Answer the transactions endpoint so only the session lookup can fail."""
    return httpx.Response(200, json={"transactions": [], "continuation_key": None})


def _message_of(excinfo: pytest.ExceptionInfo[Exception]) -> str:
    return str(excinfo.value)


def test_http_403_includes_provider_detail(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"error": "SESSION_REVOKED", "message": "Consent revoked by the bank"}
        )

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(ReauthorizationRequiredError) as excinfo:
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    message = _message_of(excinfo)
    assert "SESSION_REVOKED" in message
    assert "Consent revoked by the bank" in message


def test_http_422_on_session_lookup_includes_detail_and_reauthorization_hint(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    session_response = httpx.Response(
        422,
        json={
            "error": "SESSION_EXPIRED",
            "message": "Consent expired on 2026-10-16",
        },
    )

    connector = _FakeConnector(http_client=mock_http_client(_ok_handler, session_response))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(EnableBankingAPIError) as excinfo:
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    message = _message_of(excinfo)
    assert "422" in message
    assert "SESSION_EXPIRED" in message
    assert "Consent expired on 2026-10-16" in message
    assert "re-authoriz" in message
    assert "credentials-setup" in message


def test_error_detail_survives_a_non_json_body(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    session_response = httpx.Response(
        502, text="<html><body>Bad Gateway\n  from edge</body></html>"
    )

    connector = _FakeConnector(http_client=mock_http_client(_ok_handler, session_response))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(EnableBankingAPIError) as excinfo:
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    message = _message_of(excinfo)
    assert "Bad Gateway" in message
    assert "\n" not in message


def test_error_detail_is_truncated(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    session_response = httpx.Response(500, text="x" * 2000)

    connector = _FakeConnector(http_client=mock_http_client(_ok_handler, session_response))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(EnableBankingAPIError) as excinfo:
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    message = _message_of(excinfo)
    assert "x" * 301 not in message
    assert "x" * 200 in message


def test_empty_error_body_adds_no_detail_suffix(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    session_response = httpx.Response(500, content=b"")

    connector = _FakeConnector(http_client=mock_http_client(_ok_handler, session_response))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(EnableBankingAPIError) as excinfo:
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    message = _message_of(excinfo)
    assert "Provider detail" not in message
    assert "unexpected HTTP status: 500" in message


def test_422_describes_the_session_id_shape_without_revealing_it(
    caplog,
    eb_config_dir,
    fake_session_id_in_store,
    mock_http_client,
    tmp_env_file: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))
    # A trailing newline never reaches the request: httpx rejects control
    # characters in a URL with InvalidURL. Spaces do reach it.
    padded_session_id = " 6f1c2f5a-0f0e-4a4c-9d1f-2f5a0f0e4a4c "
    SecretStore(tmp_env_file).set("FAKE_SESSION_ID", padded_session_id)
    session_response = httpx.Response(
        422, json={"error": "WRONG_REQUEST_PARAMETERS", "message": "Wrong request parameters"}
    )

    connector = _FakeConnector(http_client=mock_http_client(_ok_handler, session_response))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(EnableBankingAPIError) as excinfo:
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    message = _message_of(excinfo)
    assert "Session id shape:" in message
    assert "length=38" in message
    assert "surrounding-whitespace=True" in message
    assert "empty=False" in message
    assert "6f1c2f5a" not in message
    assert padded_session_id.strip() not in message


def test_422_reports_a_clean_session_id_as_clean(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    session_response = httpx.Response(
        422, json={"error": "WRONG_REQUEST_PARAMETERS", "message": "Wrong request parameters"}
    )

    connector = _FakeConnector(http_client=mock_http_client(_ok_handler, session_response))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.enable_banking"):
        with pytest.raises(EnableBankingAPIError) as excinfo:
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    message = _message_of(excinfo)
    assert f"length={len(fake_session_id_in_store)}" in message
    assert "surrounding-whitespace=False" in message
    assert fake_session_id_in_store not in message


# ---------------------------------------------------------------------------
# Reconocer el valor inerte de una sesión sin configurar
# ---------------------------------------------------------------------------


def test_unconfigured_session_fails_locally_without_calling_the_api(
    eb_config_dir, fake_session_id_in_store, mock_http_client, tmp_env_file, monkeypatch
):
    monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))
    SecretStore(tmp_env_file).set("FAKE_SESSION_ID", "unconfigured")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"transactions": [], "continuation_key": None})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(BankNotOnboardedError) as excinfo:
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    message = str(excinfo.value)
    assert "no PSD2 session configured" in message
    assert "placeholder" in message
    assert "credentials-setup.md" in message
    # The literal placeholder is the secret's own value: quoting it makes
    # GitHub Actions mask it as *** in the run summary.
    assert "unconfigured" not in message
    assert calls["n"] == 0
    # A bank without a session is a normal state, not a failure: the dedicated
    # exception keeps it distinguishable without matching on message text.
    assert isinstance(excinfo.value, BankNotOnboardedError)


def test_unconfigured_placeholder_is_recognized_regardless_of_case_and_spaces(
    eb_config_dir, fake_session_id_in_store, mock_http_client, tmp_env_file, monkeypatch
):
    monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))
    SecretStore(tmp_env_file).set("FAKE_SESSION_ID", "  Unconfigured ")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request should reach the API")

    connector = _FakeConnector(http_client=mock_http_client(handler))
    with pytest.raises(BankNotOnboardedError):
        connector.fetch_balance()


def test_bank_not_onboarded_error_is_still_a_connector_config_error() -> None:
    """The new state must keep every existing ``except ConnectorConfigError`` working."""
    assert issubclass(BankNotOnboardedError, ConnectorConfigError)

    with pytest.raises(ConnectorConfigError):
        raise BankNotOnboardedError("no PSD2 session yet")


def test_a_real_session_id_is_still_sent_to_the_api(
    caplog, eb_config_dir, fake_session_id_in_store, mock_http_client
):
    # The fixture answers GET /sessions/{id}, so reaching the transactions
    # endpoint at all proves the session lookup was not short-circuited.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [], "continuation_key": None})

    connector = _FakeConnector(http_client=mock_http_client(handler))
    assert connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31)) == []


# ---------------------------------------------------------------------------
# Resolver la sesión PSD2 una sola vez por instancia del conector
# ---------------------------------------------------------------------------


def _raw_balance(amount: str = "1234.56") -> dict:
    return {
        "name": "Closing booked balance",
        "balance_amount": {"amount": amount, "currency": "EUR"},
        "balance_type": "CLBD",
        "reference_date": "2026-08-31",
    }


def _transactions_page(request: httpx.Request) -> dict:
    """One transactions page, queueing a second page on the first request."""
    if "continuation_key" in request.url.params:
        return {"transactions": [_raw_tx(description="Page2 Tx")], "continuation_key": None}
    return {"transactions": [_raw_tx(description="Page1 Tx")], "continuation_key": "abc123"}


def test_session_lookup_happens_once_per_connector_instance(
    eb_config_dir, fake_session_id_in_store
) -> None:
    """The daily pass queries both stages on one instance: resolve the session once."""
    request_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_paths.append(request.url.path)
        segments = request.url.path.strip("/").split("/")
        if segments[:1] == ["sessions"] and len(segments) == 2:
            return httpx.Response(
                200, json={"status": "AUTHORIZED", "accounts": ["test-account-id"]}
            )
        if request.url.path.endswith("/transactions"):
            return httpx.Response(200, json=_transactions_page(request))
        return httpx.Response(200, json={"balances": [_raw_balance()]})

    connector = _FakeConnector(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    transactions = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))
    balance = connector.fetch_balance()

    assert {tx.description for tx in transactions} == {"Page1 Tx", "Page2 Tx"}
    assert balance is not None
    assert balance.amount == Decimal("1234.56")
    assert request_paths.count(f"/sessions/{fake_session_id_in_store}") == 1
    assert request_paths.count("/accounts/test-account-id/transactions") == 2
    assert request_paths.count("/accounts/test-account-id/balances") == 1


def test_failed_session_resolution_is_not_cached(eb_config_dir, fake_session_id_in_store) -> None:
    """A rejected session is retried on the next call instead of being remembered."""
    responses = [
        httpx.Response(403, json={"error": "forbidden"}),
        httpx.Response(200, json={"status": "AUTHORIZED", "accounts": ["test-account-id"]}),
        httpx.Response(200, json={"transactions": [], "continuation_key": None}),
        httpx.Response(200, json={"balances": [_raw_balance()]}),
    ]
    request_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_paths.append(request.url.path)
        return responses.pop(0)

    connector = _FakeConnector(http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    with pytest.raises(ReauthorizationRequiredError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31)) == []
    assert connector.fetch_balance() is not None

    assert request_paths == [
        f"/sessions/{fake_session_id_in_store}",
        f"/sessions/{fake_session_id_in_store}",
        "/accounts/test-account-id/transactions",
        "/accounts/test-account-id/balances",
    ]
