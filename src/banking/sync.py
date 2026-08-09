"""ING -> Google Sheets synchronization pipeline (IT4)."""

import logging
import time
from dataclasses import dataclass
from datetime import date

from banking.config.secret_store import SecretStore
from banking.connectors.ing import IngConnector, Transaction
from banking.sheets.writer import CellValue, SheetsWriter

logger = logging.getLogger(__name__)

_SHEET_ID_KEY = "GOOGLE_SHEET_ID"
_HEADERS: list[CellValue] = ["Fecha de liquidación", "Banco", "Descripción", "Importe", "Divisa"]


class IngSyncError(Exception):
    """Raised when obtaining ING movements fails; wraps the original connector error."""


class SheetsSyncError(Exception):
    """Raised when writing to Google Sheets fails; wraps the original writer error."""


@dataclass(frozen=True)
class SyncResult:
    """The outcome of a successful sync run."""

    bank_name: str
    rows_written: int
    tab_name: str
    duration_seconds: float


def _transform(bank_name: str, transactions: list[Transaction]) -> list[list[CellValue]]:
    """Convert ING transactions to rows matching `_HEADERS`, in fixed column order."""
    return [
        [tx.booking_date.isoformat(), bank_name, tx.description, float(tx.amount), tx.currency]
        for tx in transactions
    ]


def run_sync(
    connector: IngConnector | None = None,
    writer: SheetsWriter | None = None,
    document_id: str | None = None,
    today: date | None = None,
) -> SyncResult:
    """Fetch this month's ING movements and overwrite the YYYY-MM Sheets tab.

    Raises:
        IngSyncError: obtaining movements from ING failed.
        SheetsSyncError: writing to Google Sheets failed (including
            resolving the destination document ID).
    """
    start = time.monotonic()
    execution_date = today or date.today()
    range_start = execution_date.replace(day=1)
    tab_name = execution_date.strftime("%Y-%m")

    connector = connector or IngConnector()
    writer = writer or SheetsWriter()

    try:
        transactions = connector.fetch_transactions(range_start, execution_date)
    except Exception as exc:
        logger.error("Sync failed: bank=%s system=ing reason=%s", IngConnector.BANK_NAME, exc)
        raise IngSyncError(str(exc)) from exc

    rows = _transform(IngConnector.BANK_NAME, transactions)

    try:
        resolved_document_id = (
            document_id if document_id is not None else SecretStore().get(_SHEET_ID_KEY)
        )
        writer.write(
            document_id=resolved_document_id, tab_name=tab_name, headers=_HEADERS, rows=rows
        )
    except Exception as exc:
        logger.error(
            "Sync failed: bank=%s system=sheets tab=%s reason=%s",
            IngConnector.BANK_NAME,
            tab_name,
            exc,
        )
        raise SheetsSyncError(str(exc)) from exc

    duration = time.monotonic() - start
    logger.info(
        "Sync succeeded: bank=%s tab=%s rows_written=%d duration=%.3fs",
        IngConnector.BANK_NAME,
        tab_name,
        len(rows),
        duration,
    )
    return SyncResult(
        bank_name=IngConnector.BANK_NAME,
        rows_written=len(rows),
        tab_name=tab_name,
        duration_seconds=duration,
    )
