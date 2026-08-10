"""Tests for the ING España Enable Banking connector."""

import json
import logging
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from banking.connectors.ing import (
    ConnectorConfigError,
    EnableBankingAPIError,
    IngConnector,
    InvalidDateRangeError,
    PaginationLimitExceededError,
    RateLimitExceededError,
    ReauthorizationRequiredError,
)


def _raw_tx(
    status: str = "BOOK",
    booking_date: str = "2026-08-15",
    amount: str = "42.50",
    currency: str = "EUR",
    indicator: str = "CRDT",
    description: str = "Test tx",
) -> dict:
    return {
        "status": status,
        "booking_date": booking_date,
        "transaction_amount": {"amount": amount, "currency": currency},
        "credit_debit_indicator": indicator,
        "remittance_information": [description] if description else [],
    }


# ---------------------------------------------------------------------------
# US1 — Recuperar movimientos liquidados en un rango de fechas (T005-T009)
# ---------------------------------------------------------------------------


def test_single_page_filters_and_normalizes(eb_config_dir, session_id_in_store, mock_http_client):
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

    connector = IngConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert len(result) == 2
    by_description = {tx.description: tx for tx in result}
    assert by_description["Nomina"].amount == Decimal("42.50")
    assert by_description["Compra"].amount == Decimal("-20.00")
    assert all(tx.currency == "EUR" for tx in result)


def test_multi_page_pagination_combines_results(
    eb_config_dir, session_id_in_store, mock_http_client
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

    connector = IngConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert {tx.description for tx in result} == {"Page1 Tx", "Page2 Tx"}
    assert call_count["n"] == 2


def test_date_range_inclusive_on_both_ends(eb_config_dir, session_id_in_store, mock_http_client):
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

    connector = IngConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert {tx.description for tx in result} == {"Start day", "End day"}


def test_empty_range_returns_empty_list(eb_config_dir, session_id_in_store, mock_http_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [], "continuation_key": None})

    connector = IngConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert result == []


def test_deduplicates_transaction_repeated_across_page_boundary(
    eb_config_dir, session_id_in_store, mock_http_client
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

    connector = IngConnector(http_client=mock_http_client(handler))
    result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    descriptions = [tx.description for tx in result]
    assert descriptions.count("Dup Tx") == 1
    assert "Unique Tx" in descriptions
    assert len(result) == 2


def test_success_logs_structured_record(
    caplog, eb_config_dir, session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [_raw_tx()], "continuation_key": None})

    connector = IngConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.INFO, logger="banking.connectors.ing"):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    message = info_records[0].getMessage()
    assert "ING" in message
    assert "2026-08-01" in message
    assert "2026-08-31" in message
    assert "1" in message


def test_start_after_end_raises_before_http_call(
    eb_config_dir, session_id_in_store, mock_http_client
):
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"transactions": [], "continuation_key": None})

    connector = IngConnector(http_client=mock_http_client(handler))
    with pytest.raises(InvalidDateRangeError):
        connector.fetch_transactions(date(2026, 8, 31), date(2026, 8, 1))

    assert called["n"] == 0


def test_malformed_record_skipped_with_warning(
    caplog, eb_config_dir, session_id_in_store, mock_http_client
):
    good = _raw_tx(description="Good Tx")
    bad = {"status": "BOOK", "booking_date": "2026-08-15"}  # missing amount/currency/indicator

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [bad, good], "continuation_key": None})

    connector = IngConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.WARNING, logger="banking.connectors.ing"):
        result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert len(result) == 1
    assert result[0].description == "Good Tx"
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_missing_eb_config_file_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_id_in_store, mock_http_client
):
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(tmp_path / "does-not-exist"))

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No debe realizarse ninguna llamada HTTP")

    connector = IngConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


def test_invalid_json_eb_config_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_id_in_store, mock_http_client
):
    config_dir = tmp_path / "banca-personal"
    config_dir.mkdir()
    (config_dir / "eb-config.json").write_text("not valid json{", encoding="utf-8")
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(config_dir))

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No debe realizarse ninguna llamada HTTP")

    connector = IngConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


def test_missing_required_fields_in_eb_config_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_id_in_store, mock_http_client
):
    config_dir = tmp_path / "banca-personal"
    config_dir.mkdir()
    (config_dir / "eb-config.json").write_text(json.dumps({"app_id": "x"}), encoding="utf-8")
    monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(config_dir))

    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("No debe realizarse ninguna llamada HTTP")

    connector = IngConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


def test_private_key_file_missing_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_id_in_store, mock_http_client
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

    connector = IngConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


# ---------------------------------------------------------------------------
# US2 — Detectar una sesión inutilizable y fallar con claridad (T014)
# ---------------------------------------------------------------------------


def test_http_403_raises_reauthorization_required(
    caplog, eb_config_dir, session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    connector = IngConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.ing"):
        with pytest.raises(ReauthorizationRequiredError, match="re-authoriz|browser"):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "ING" in message
    assert "2026-08-01" in message
    assert "2026-08-31" in message


def test_expired_session_status_raises_reauthorization_required(
    caplog, eb_config_dir, session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "expired"})

    connector = IngConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.ing"):
        with pytest.raises(ReauthorizationRequiredError, match="re-authoriz|browser"):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_session_expires_mid_pagination_returns_no_partial_data(
    caplog, eb_config_dir, session_id_in_store, mock_http_client
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

    connector = IngConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.ing"):
        with pytest.raises(ReauthorizationRequiredError):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert call_count["n"] == 2
    assert any(r.levelno == logging.ERROR for r in caplog.records)


# ---------------------------------------------------------------------------
# US3 — Respetar el límite de peticiones PSD2 e informar con claridad (T016)
# ---------------------------------------------------------------------------


def test_http_429_on_initial_request_raises_rate_limit_exceeded(
    caplog, eb_config_dir, session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "too many requests"})

    connector = IngConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.ing"):
        with pytest.raises(RateLimitExceededError, match="4|daily|PSD2"):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "ING" in message
    assert "2026-08-01" in message
    assert "2026-08-31" in message


def test_http_429_on_pagination_request_raises_rate_limit_exceeded(
    caplog, eb_config_dir, session_id_in_store, mock_http_client
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

    connector = IngConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.ing"):
        with pytest.raises(RateLimitExceededError):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    assert call_count["n"] == 2
    assert any(r.levelno == logging.ERROR for r in caplog.records)


def test_unexpected_http_error_raises_enable_banking_api_error(
    caplog, eb_config_dir, session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal server error"})

    connector = IngConnector(http_client=mock_http_client(handler))
    with caplog.at_level(logging.ERROR, logger="banking.connectors.ing"):
        with pytest.raises(EnableBankingAPIError):
            connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "ING" in message
    assert "2026-08-01" in message
    assert "2026-08-31" in message


# ---------------------------------------------------------------------------
# Polish — salvaguarda de paginación (T018)
# ---------------------------------------------------------------------------


def test_pagination_never_stopping_raises_pagination_limit_exceeded(
    eb_config_dir, session_id_in_store, mock_http_client
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"transactions": [], "continuation_key": "always-more"})

    connector = IngConnector(http_client=mock_http_client(handler))
    with pytest.raises(PaginationLimitExceededError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


# ---------------------------------------------------------------------------
# Polish — redacción de secretos en logs, FR-015 (T019)
# ---------------------------------------------------------------------------


def test_no_secrets_leak_into_logs_across_all_scenarios(
    caplog, eb_config_dir, session_id_in_store, mock_http_client, rsa_private_key_pem
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

    with caplog.at_level(logging.DEBUG, logger="banking.connectors.ing"):
        for build_response in scenario_responses:
            connector = IngConnector(http_client=mock_http_client(make_handler(build_response)))
            try:
                connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))
            except (ReauthorizationRequiredError, RateLimitExceededError, EnableBankingAPIError):
                pass

    all_log_text = "\n".join(r.getMessage() for r in caplog.records)

    pem_text = rsa_private_key_pem.decode("utf-8")
    assert pem_text not in all_log_text
    assert session_id_in_store not in all_log_text
    assert len(captured_auth_headers) >= len(scenario_responses)
    for header_value in captured_auth_headers:
        token = header_value.removeprefix("Bearer ")
        assert token, "expected a JWT to have been sent on every request"
        assert token not in all_log_text


def test_invalid_private_key_raises_connector_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, session_id_in_store, mock_http_client
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

    connector = IngConnector(http_client=mock_http_client(handler))
    with pytest.raises(ConnectorConfigError):
        connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))


def test_bank_name_is_a_public_class_attribute() -> None:
    assert IngConnector.BANK_NAME == "ING España"
