"""Multi-bank -> Google Sheets synchronization pipeline (IT5)."""

import logging
import time
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Sequence

from banking.config.secret_store import SecretStore
from banking.connectors.enable_banking import EnableBankingConnector, Transaction
from banking.connectors.ing import IngConnector
from banking.connectors.myinvestor import MyInvestorConnector
from banking.connectors.revolut import RevolutConnector
from banking.connectors.sabadell import SabadellConnector
from banking.sheets.writer import CellValue, SheetsWriter

logger = logging.getLogger(__name__)

_SHEET_ID_KEY = "GOOGLE_SHEET_ID"
_HEADERS: list[CellValue] = ["Fecha de liquidación", "Banco", "Descripción", "Importe", "Divisa"]
_CONNECTOR_CLASSES: tuple[type[EnableBankingConnector], ...] = (
    IngConnector,
    RevolutConnector,
    MyInvestorConnector,
    SabadellConnector,
)


class AllBanksFailedError(Exception):
    """Raised when every bank connector fails; nothing is written to Sheets."""


class SheetsSyncError(Exception):
    """Raised when writing to Google Sheets fails; wraps the original writer error."""


class OverallStatus(Enum):
    """The three possible outcomes of a sync run."""

    FULL_SUCCESS = "full_success"
    PARTIAL_FAILURE = "partial_failure"
    TOTAL_FAILURE = "total_failure"


@dataclass(frozen=True)
class BankOutcome:
    """The outcome of running one bank's connector in a sync run."""

    bank_name: str
    succeeded: bool
    rows_written: int | None
    failure_reason: str | None


@dataclass(frozen=True)
class SyncSummary:
    """The aggregate outcome of a sync run across all bank connectors."""

    outcomes: list[BankOutcome]
    overall_status: OverallStatus
    tab_name: str
    total_rows_written: int
    duration_seconds: float


def _transform(bank_name: str, transactions: list[Transaction]) -> list[list[CellValue]]:
    """Convert transactions to rows matching `_HEADERS`, in fixed column order."""
    return [
        [tx.booking_date.isoformat(), bank_name, tx.description, float(tx.amount), tx.currency]
        for tx in transactions
    ]


def _classify(outcomes: list[BankOutcome]) -> OverallStatus:
    """Classify the aggregate result of a sync run from its per-bank outcomes."""
    if all(o.succeeded for o in outcomes):
        return OverallStatus.FULL_SUCCESS
    if any(o.succeeded for o in outcomes):
        return OverallStatus.PARTIAL_FAILURE
    return OverallStatus.TOTAL_FAILURE


def _sync_one_bank(
    connector: EnableBankingConnector, start_date: date, end_date: date
) -> tuple[BankOutcome, list[Transaction]]:
    """Run one bank's connector, translating any failure into a `BankOutcome`."""
    try:
        transactions = connector.fetch_transactions(start_date, end_date)
    except Exception as exc:
        logger.error(
            "Sync failed: bank=%s reason=%s",
            connector.BANK_NAME,
            exc,
        )
        return (
            BankOutcome(
                bank_name=connector.BANK_NAME,
                succeeded=False,
                rows_written=None,
                failure_reason=str(exc),
            ),
            [],
        )
    return (
        BankOutcome(
            bank_name=connector.BANK_NAME,
            succeeded=True,
            rows_written=len(transactions),
            failure_reason=None,
        ),
        transactions,
    )


def run_sync(
    connectors: Sequence[EnableBankingConnector] | None = None,
    writer: SheetsWriter | None = None,
    document_id: str | None = None,
    today: date | None = None,
) -> SyncSummary:
    """Fetch this month's movements from all four banks and write the successful ones.

    Runs each bank connector independently, in the fixed ING/Revolut/MyInvestor/
    Sabadell order. A single connector's failure does not abort the run.

    Raises:
        SheetsSyncError: writing the combined rows to Google Sheets failed
            (including resolving the destination document ID), after at
            least one bank succeeded.
    """
    start = time.monotonic()
    execution_date = today or date.today()
    range_start = execution_date.replace(day=1)
    tab_name = execution_date.strftime("%Y-%m")

    resolved_connectors: Sequence[EnableBankingConnector] = (
        connectors if connectors is not None else [cls() for cls in _CONNECTOR_CLASSES]
    )
    writer = writer or SheetsWriter()

    outcomes: list[BankOutcome] = []
    rows: list[list[CellValue]] = []
    for connector in resolved_connectors:
        outcome, transactions = _sync_one_bank(connector, range_start, execution_date)
        outcomes.append(outcome)
        rows.extend(_transform(outcome.bank_name, transactions))

    overall_status = _classify(outcomes)

    if overall_status == OverallStatus.TOTAL_FAILURE:
        aggregate = "; ".join(f"{o.bank_name}: {o.failure_reason}" for o in outcomes)
        logger.error("Sync failed: all four banks failed: %s", aggregate)
        raise AllBanksFailedError(f"All four banks failed: {aggregate}")

    try:
        resolved_document_id = (
            document_id if document_id is not None else SecretStore().get(_SHEET_ID_KEY)
        )
        writer.write(
            document_id=resolved_document_id, tab_name=tab_name, headers=_HEADERS, rows=rows
        )
    except Exception as exc:
        logger.error("Sync failed: system=sheets tab=%s reason=%s", tab_name, exc)
        raise SheetsSyncError(str(exc)) from exc

    duration = time.monotonic() - start
    total_rows_written = sum(o.rows_written or 0 for o in outcomes)
    logger.info(
        "Sync succeeded: status=%s tab=%s rows_written=%d duration=%.3fs",
        overall_status.value,
        tab_name,
        total_rows_written,
        duration,
    )
    return SyncSummary(
        outcomes=outcomes,
        overall_status=overall_status,
        tab_name=tab_name,
        total_rows_written=total_rows_written,
        duration_seconds=duration,
    )
