"""Tests for the multi-bank sync pipeline (banking.sync)."""

import logging
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest

from banking.connectors.enable_banking import (
    ConnectorConfigError,
    EnableBankingAPIError,
    PaginationLimitExceededError,
    RateLimitExceededError,
    ReauthorizationRequiredError,
    Transaction,
)
from banking.connectors.ing import IngConnector
from banking.connectors.myinvestor import MyInvestorConnector
from banking.connectors.revolut import RevolutConnector
from banking.connectors.sabadell import SabadellConnector
from banking.sheets.writer import (
    SheetsAccessError,
    SheetsAPIError,
    SheetsConfigError,
    SheetsQuotaExceededError,
    SheetsWriter,
)
from banking.sync import AllBanksFailedError, BankOutcome, OverallStatus, SheetsSyncError, run_sync

_HEADERS = ["Fecha de liquidación", "Banco", "Descripción", "Importe", "Divisa"]


def _mock_connector(spec: type, transactions: list[Transaction]) -> Mock:
    connector = Mock(spec=spec)
    connector.BANK_NAME = spec.BANK_NAME
    connector.fetch_transactions.return_value = transactions
    return connector


def _four_connectors(
    ing_txs: list[Transaction] | None = None,
    revolut_txs: list[Transaction] | None = None,
    myinvestor_txs: list[Transaction] | None = None,
    sabadell_txs: list[Transaction] | None = None,
) -> list[Mock]:
    return [
        _mock_connector(IngConnector, ing_txs if ing_txs is not None else []),
        _mock_connector(RevolutConnector, revolut_txs if revolut_txs is not None else []),
        _mock_connector(MyInvestorConnector, myinvestor_txs if myinvestor_txs is not None else []),
        _mock_connector(SabadellConnector, sabadell_txs if sabadell_txs is not None else []),
    ]


# --- US1: sincronizar los cuatro bancos en una sola ejecución ---------------


def test_run_sync_all_four_succeed_combines_and_writes() -> None:
    ing_txs = [Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    revolut_txs = [Transaction(date(2026, 8, 2), Decimal("-5.00"), "EUR", "Revolut tx")]
    myinvestor_txs = [Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")]
    sabadell_txs = [Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")]
    connectors = _four_connectors(ing_txs, revolut_txs, myinvestor_txs, sabadell_txs)
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    for connector in connectors:
        connector.fetch_transactions.assert_called_once_with(date(2026, 8, 1), date(2026, 8, 15))

    writer.write.assert_called_once_with(
        document_id="doc-id",
        tab_name="2026-08",
        headers=_HEADERS,
        rows=[
            ["2026-08-01", "ING España", "ING tx", 10.0, "EUR"],
            ["2026-08-02", "Revolut", "Revolut tx", -5.0, "EUR"],
            ["2026-08-03", "MyInvestor", "MyInvestor tx", 20.0, "EUR"],
            ["2026-08-04", "Banco Sabadell", "Sabadell tx", -2.5, "EUR"],
        ],
    )
    assert summary.overall_status == OverallStatus.FULL_SUCCESS
    assert summary.tab_name == "2026-08"
    assert summary.total_rows_written == 4
    assert summary.outcomes == [
        BankOutcome(bank_name="ING España", succeeded=True, rows_written=1, failure_reason=None),
        BankOutcome(bank_name="Revolut", succeeded=True, rows_written=1, failure_reason=None),
        BankOutcome(bank_name="MyInvestor", succeeded=True, rows_written=1, failure_reason=None),
        BankOutcome(
            bank_name="Banco Sabadell", succeeded=True, rows_written=1, failure_reason=None
        ),
    ]


def test_run_sync_bank_with_no_transactions_still_counts_as_success() -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        revolut_txs=[],
        myinvestor_txs=[Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    assert summary.overall_status == OverallStatus.FULL_SUCCESS
    revolut_outcome = next(o for o in summary.outcomes if o.bank_name == "Revolut")
    assert revolut_outcome == BankOutcome(
        bank_name="Revolut", succeeded=True, rows_written=0, failure_reason=None
    )
    written_rows = writer.write.call_args.kwargs["rows"]
    assert all(row[1] != "Revolut" for row in written_rows)
    assert len(written_rows) == 3


# --- US2: continuar cuando un banco falla, sin perder los datos de los demás -


@pytest.mark.parametrize(
    "exc_type",
    [
        ReauthorizationRequiredError,
        RateLimitExceededError,
        EnableBankingAPIError,
        ConnectorConfigError,
        PaginationLimitExceededError,
        httpx.TimeoutException,
    ],
)
def test_run_sync_one_bank_fails_others_continue(exc_type: type[Exception]) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        myinvestor_txs=[Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    connectors[1].fetch_transactions.side_effect = exc_type("boom")  # Revolut falla
    writer = Mock(spec=SheetsWriter)

    summary = run_sync(
        connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
    )

    for connector in connectors:
        connector.fetch_transactions.assert_called_once_with(date(2026, 8, 1), date(2026, 8, 15))

    assert summary.overall_status == OverallStatus.PARTIAL_FAILURE
    revolut_outcome = next(o for o in summary.outcomes if o.bank_name == "Revolut")
    assert revolut_outcome.succeeded is False
    assert revolut_outcome.rows_written is None
    assert "boom" in (revolut_outcome.failure_reason or "")
    other_outcomes = [o for o in summary.outcomes if o.bank_name != "Revolut"]
    assert all(o.succeeded for o in other_outcomes)

    writer.write.assert_called_once()
    written_rows = writer.write.call_args.kwargs["rows"]
    assert all(row[1] != "Revolut" for row in written_rows)
    assert len(written_rows) == 3
    assert summary.total_rows_written == 3


def test_run_sync_logs_error_for_failed_bank_without_leaking_document_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        myinvestor_txs=[Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    connectors[1].fetch_transactions.side_effect = ReauthorizationRequiredError("re-auth needed")
    writer = Mock(spec=SheetsWriter)

    with caplog.at_level(logging.ERROR, logger="banking.sync"):
        run_sync(
            connectors=connectors,
            writer=writer,
            document_id="secret-doc-id",
            today=date(2026, 8, 15),
        )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "Revolut" in message
    assert "re-auth needed" in message
    assert "secret-doc-id" not in message


def test_run_sync_second_execution_does_not_carry_over_previously_failed_bank() -> None:
    """FR-006 / US2 Escenario de Aceptación 5: una ejecución con un banco fallido
    no debe arrastrar datos de ese banco de una ejecución anterior del mismo día.
    """
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")],
        revolut_txs=[Transaction(date(2026, 8, 2), Decimal("-5.00"), "EUR", "Revolut tx")],
        myinvestor_txs=[Transaction(date(2026, 8, 3), Decimal("20.00"), "EUR", "MyInvestor tx")],
        sabadell_txs=[Transaction(date(2026, 8, 4), Decimal("-2.50"), "EUR", "Sabadell tx")],
    )
    writer = Mock(spec=SheetsWriter)

    run_sync(connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15))
    first_call_rows = writer.write.call_args.kwargs["rows"]
    assert any(row[1] == "Revolut" for row in first_call_rows)

    connectors[1].fetch_transactions.side_effect = ReauthorizationRequiredError("re-auth needed")
    run_sync(connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15))
    second_call_rows = writer.write.call_args.kwargs["rows"]

    assert writer.write.call_count == 2
    assert all(row[1] != "Revolut" for row in second_call_rows)
    assert len(second_call_rows) == 3


# --- US3: terminar de forma controlada cuando ningún banco responde --------


def test_run_sync_all_four_fail_raises_all_banks_failed_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connectors = _four_connectors()
    connectors[0].fetch_transactions.side_effect = ReauthorizationRequiredError("ing boom")
    connectors[1].fetch_transactions.side_effect = RateLimitExceededError("revolut boom")
    connectors[2].fetch_transactions.side_effect = EnableBankingAPIError("myinvestor boom")
    connectors[3].fetch_transactions.side_effect = RuntimeError("sabadell boom")
    writer = Mock(spec=SheetsWriter)

    with caplog.at_level(logging.ERROR, logger="banking.sync"):
        with pytest.raises(AllBanksFailedError):
            run_sync(
                connectors=connectors,
                writer=writer,
                document_id="doc-id",
                today=date(2026, 8, 15),
            )

    writer.write.assert_not_called()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    aggregate_messages = "\n".join(r.getMessage() for r in error_records)
    for bank, reason in [
        ("ING España", "ing boom"),
        ("Revolut", "revolut boom"),
        ("MyInvestor", "myinvestor boom"),
        ("Banco Sabadell", "sabadell boom"),
    ]:
        assert bank in aggregate_messages
        assert reason in aggregate_messages


@pytest.mark.parametrize(
    "exc_type",
    [SheetsConfigError, SheetsAccessError, SheetsQuotaExceededError, SheetsAPIError],
)
def test_run_sync_sheets_write_failure_raises_sheets_sync_error(
    exc_type: type[Exception],
) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    writer = Mock(spec=SheetsWriter)
    writer.write.side_effect = exc_type("boom")

    with pytest.raises(SheetsSyncError, match="boom"):
        run_sync(
            connectors=connectors, writer=writer, document_id="doc-id", today=date(2026, 8, 15)
        )


def test_run_sync_missing_document_id_secret_raises_sheets_sync_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    writer = Mock(spec=SheetsWriter)

    class _FailingSecretStore:
        def get(self, key: str) -> str:
            raise KeyError(key)

    monkeypatch.setattr("banking.sync.SecretStore", _FailingSecretStore)

    with pytest.raises(SheetsSyncError):
        run_sync(connectors=connectors, writer=writer, today=date(2026, 8, 15))

    writer.write.assert_not_called()


def test_run_sync_sheets_failure_logs_error_without_leaking_document_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connectors = _four_connectors(
        ing_txs=[Transaction(date(2026, 8, 1), Decimal("10.00"), "EUR", "ING tx")]
    )
    writer = Mock(spec=SheetsWriter)
    writer.write.side_effect = SheetsAccessError("no access")

    with caplog.at_level(logging.ERROR, logger="banking.sync"):
        with pytest.raises(SheetsSyncError):
            run_sync(
                connectors=connectors,
                writer=writer,
                document_id="secret-doc-id",
                today=date(2026, 8, 15),
            )

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) >= 1
    message = " ".join(r.getMessage() for r in error_records)
    assert "sheets" in message.lower()
    assert "secret-doc-id" not in message
