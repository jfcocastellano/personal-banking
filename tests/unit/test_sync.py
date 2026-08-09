"""Tests for the ING -> Google Sheets sync pipeline (banking.sync)."""

import logging
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest

from banking.connectors.ing import (
    ConnectorConfigError,
    EnableBankingAPIError,
    IngConnector,
    PaginationLimitExceededError,
    RateLimitExceededError,
    ReauthorizationRequiredError,
    Transaction,
)
from banking.sheets.writer import (
    SheetsAccessError,
    SheetsAPIError,
    SheetsConfigError,
    SheetsQuotaExceededError,
    SheetsWriter,
)
from banking.sync import IngSyncError, SheetsSyncError, run_sync

_HEADERS = ["Fecha de liquidación", "Banco", "Descripción", "Importe", "Divisa"]


def _transactions() -> list[Transaction]:
    return [
        Transaction(date(2026, 8, 1), Decimal("42.50"), "EUR", "Nómina"),
        Transaction(date(2026, 8, 3), Decimal("-12.30"), "EUR", "Supermercado"),
    ]


# --- US1: run the sync with a single call -----------------------------------


def test_run_sync_transforms_and_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.return_value = _transactions()
    writer = Mock(spec=SheetsWriter)

    times = iter([100.0, 100.5])
    monkeypatch.setattr("banking.sync.time.monotonic", lambda: next(times))

    result = run_sync(
        connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    connector.fetch_transactions.assert_called_once_with(date(2026, 8, 1), date(2026, 8, 15))
    writer.write.assert_called_once_with(
        document_id="doc-id",
        tab_name="2026-08",
        headers=_HEADERS,
        rows=[
            ["2026-08-01", "ING España", "Nómina", 42.5, "EUR"],
            ["2026-08-03", "ING España", "Supermercado", -12.3, "EUR"],
        ],
    )
    assert result.bank_name == IngConnector.BANK_NAME
    assert result.tab_name == "2026-08"
    assert result.rows_written == 2
    assert result.duration_seconds == 0.5


def test_run_sync_with_no_transactions_writes_only_headers() -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.return_value = []
    writer = Mock(spec=SheetsWriter)

    result = run_sync(
        connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    writer.write.assert_called_once_with(
        document_id="doc-id", tab_name="2026-08", headers=_HEADERS, rows=[]
    )
    assert result.rows_written == 0


# --- US2: running twice the same day is idempotent --------------------------


def test_run_sync_twice_same_day_writes_identical_rows() -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.return_value = _transactions()
    writer = Mock(spec=SheetsWriter)

    run_sync(connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15))
    run_sync(connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15))

    first_call, second_call = writer.write.call_args_list
    assert first_call == second_call


def test_run_sync_second_call_reflects_new_transaction() -> None:
    connector = Mock(spec=IngConnector)
    writer = Mock(spec=SheetsWriter)

    connector.fetch_transactions.return_value = _transactions()
    run_sync(connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15))

    grown = [*_transactions(), Transaction(date(2026, 8, 15), Decimal("5.00"), "EUR", "Café")]
    connector.fetch_transactions.return_value = grown
    run_sync(connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15))

    second_call_rows = writer.write.call_args_list[1].kwargs["rows"]
    assert len(second_call_rows) == 3
    assert second_call_rows[-1] == ["2026-08-15", "ING España", "Café", 5.0, "EUR"]


# --- US3: diagnosable failures, categorized by responsible system -----------


@pytest.mark.parametrize(
    "exc_type",
    [
        ConnectorConfigError,
        ReauthorizationRequiredError,
        RateLimitExceededError,
        PaginationLimitExceededError,
        EnableBankingAPIError,
    ],
)
def test_ing_failure_raises_ing_sync_error_without_writing(exc_type: type[Exception]) -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.side_effect = exc_type("boom")
    writer = Mock(spec=SheetsWriter)

    with pytest.raises(IngSyncError, match="boom"):
        run_sync(connector=connector, writer=writer, document_id="doc-id")

    writer.write.assert_not_called()


@pytest.mark.parametrize(
    "exc_type",
    [SheetsConfigError, SheetsAccessError, SheetsQuotaExceededError, SheetsAPIError],
)
def test_sheets_failure_raises_sheets_sync_error(exc_type: type[Exception]) -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.return_value = _transactions()
    writer = Mock(spec=SheetsWriter)
    writer.write.side_effect = exc_type("boom")

    with pytest.raises(SheetsSyncError, match="boom"):
        run_sync(connector=connector, writer=writer, document_id="doc-id")


def test_missing_document_id_secret_raises_sheets_sync_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.return_value = _transactions()
    writer = Mock(spec=SheetsWriter)

    class _FailingSecretStore:
        def get(self, key: str) -> str:
            raise KeyError(key)

    monkeypatch.setattr("banking.sync.SecretStore", _FailingSecretStore)

    with pytest.raises(SheetsSyncError):
        run_sync(connector=connector, writer=writer)  # document_id omitido a propósito

    writer.write.assert_not_called()


def test_ing_failure_logs_error_without_leaking_document_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.side_effect = ReauthorizationRequiredError("re-auth needed")
    writer = Mock(spec=SheetsWriter)

    with caplog.at_level(logging.ERROR, logger="banking.sync"):
        with pytest.raises(IngSyncError):
            run_sync(connector=connector, writer=writer, document_id="secret-doc-id")

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "ing" in message.lower()
    assert "secret-doc-id" not in message


def test_sheets_failure_logs_error_without_leaking_document_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.return_value = _transactions()
    writer = Mock(spec=SheetsWriter)
    writer.write.side_effect = SheetsAccessError("no access")

    with caplog.at_level(logging.ERROR, logger="banking.sync"):
        with pytest.raises(SheetsSyncError):
            run_sync(connector=connector, writer=writer, document_id="secret-doc-id")

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "sheets" in message.lower()
    assert "secret-doc-id" not in message


def test_success_logs_info_with_bank_tab_rows_duration(caplog: pytest.LogCaptureFixture) -> None:
    connector = Mock(spec=IngConnector)
    connector.fetch_transactions.return_value = _transactions()
    writer = Mock(spec=SheetsWriter)

    with caplog.at_level(logging.INFO, logger="banking.sync"):
        run_sync(connector=connector, writer=writer, document_id="doc-id", today=date(2026, 8, 15))

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    message = info_records[0].getMessage()
    assert "ING España" in message
    assert "2026-08" in message
    assert "2" in message
