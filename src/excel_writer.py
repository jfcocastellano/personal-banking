"""
ExcelWriter: persist NormalizedTransaction objects into monthly Excel workbooks.

Implements Requirements:
  4.1 — Insert each movement as a new row in movimientos_{YYYY_MM}.xlsx
  4.2 — Create file with Movimientos sheet + headers if it does not exist
  4.3 — Detect duplicates via (fecha, importe, concepto, banco) key; mark Estado
  4.4 — Preserve all existing rows (append-only, never overwrite)
  4.5 — Save and close only if writing completed without errors; raise ExcelWriteError otherwise
  5.1 — Create/replace Resumen sheet when enable_summary=True
  5.2 — Calculate total income and expenses per bank using exact Decimal arithmetic
  5.3 — Totals reflect all movements in the month (existing + new), not just the current batch
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import openpyxl
from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from src.exceptions import ExcelWriteError
from src.normalizer import NormalizedTransaction

# Column indices (1-based) for the Movimientos sheet
_COL_FECHA = 1
_COL_IMPORTE = 2
_COL_CONCEPTO = 3
_COL_BANCO = 4
_COL_ESTADO = 5

_HEADERS = ("Fecha", "Importe", "Concepto", "Banco", "Estado")

_STATUS_NORMAL = "NORMAL"
_STATUS_DUPLICATE = "DUPLICATE"

_SHEET_MOVIMIENTOS = "Movimientos"
_SHEET_RESUMEN = "Resumen"

_RESUMEN_HEADERS = ("Banco", "Total Ingresos", "Total Gastos")


class ExcelWriter:
    """Write normalized bank transactions to monthly Excel workbooks.

    Each workbook is named ``movimientos_{YYYY_MM}.xlsx`` and lives inside
    *output_dir*.  Transactions from different calendar months are stored in
    separate files.

    Usage::

        writer = ExcelWriter(Path("output"))
        writer.write(transactions, enable_summary=True)
    """

    def __init__(self, output_dir: Path) -> None:
        """Initialise the writer.

        Parameters
        ----------
        output_dir:
            Directory where ``.xlsx`` files are created.  The directory is
            created (including any missing parents) if it does not exist.
        """
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(
        self,
        transactions: list[NormalizedTransaction],
        enable_summary: bool = False,
    ) -> None:
        """Write *transactions* to the appropriate monthly workbooks.

        Transactions are grouped by their ``fecha`` month.  Each group is
        written to the corresponding ``movimientos_{YYYY_MM}.xlsx`` file.

        The file is created with headers if it does not exist.  Existing rows
        are never modified or deleted (append-only).  Duplicate detection is
        based on the ``(fecha, importe, concepto, banco)`` tuple.

        When *enable_summary* is ``True``, a ``Resumen`` sheet is
        created/replaced with per-bank income and expense totals computed from
        *all* rows in the month (existing + new), using exact ``Decimal``
        arithmetic.

        The workbook is saved only if every write operation completed without
        error.  If any exception occurs during writing, the workbook is *not*
        saved and an :exc:`~src.exceptions.ExcelWriteError` is raised.

        Parameters
        ----------
        transactions:
            List of normalized transactions to persist.
        enable_summary:
            When ``True``, create/replace the ``Resumen`` sheet with monthly
            totals per bank.

        Raises
        ------
        ExcelWriteError
            If an error occurs during row writing.  The workbook is not saved.
        """
        # Group transactions by month key (e.g., "2025_01")
        by_month: dict[str, list[NormalizedTransaction]] = defaultdict(list)
        for tx in transactions:
            month_key = tx.fecha.strftime("%Y_%m")
            by_month[month_key].append(tx)

        for month_key, month_txs in by_month.items():
            self._write_month(month_key, month_txs, enable_summary)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _workbook_path(self, month_key: str) -> Path:
        """Return the Path for ``movimientos_{month_key}.xlsx``."""
        return self._output_dir / f"movimientos_{month_key}.xlsx"

    def _load_or_create(self, path: Path) -> tuple[Workbook, Worksheet]:
        """Load an existing workbook or create a new one with headers.

        Returns
        -------
        (workbook, movimientos_sheet)
        """
        if path.exists():
            wb = openpyxl.load_workbook(str(path))
            if _SHEET_MOVIMIENTOS in wb.sheetnames:
                ws = wb[_SHEET_MOVIMIENTOS]
            else:
                # Sheet missing in an existing file — create it with headers
                ws = wb.create_sheet(_SHEET_MOVIMIENTOS)
                ws.append(list(_HEADERS))
        else:
            wb = Workbook()
            # openpyxl creates a default "Sheet" on a new Workbook; rename it.
            ws = wb.active
            ws.title = _SHEET_MOVIMIENTOS
            ws.append(list(_HEADERS))

        return wb, ws

    def _build_existing_keys(
        self, ws: Worksheet
    ) -> set[tuple]:
        """Build a deduplication set from the existing rows.

        Each element is a ``(fecha_str, importe_decimal, concepto, banco)``
        tuple, matching the representation stored in the Excel cells.

        The first row is assumed to be the header row and is skipped.

        Returns
        -------
        set of (fecha_str, Decimal, str, str)
        """
        keys: set[tuple] = set()
        for row in ws.iter_rows(min_row=2, values_only=True):
            fecha_cell, importe_cell, concepto_cell, banco_cell, *_ = row
            if fecha_cell is None:
                continue
            # fecha is stored as a date/datetime in the cell; normalise to str
            fecha_str = _cell_to_fecha_str(fecha_cell)
            importe_dec = _cell_to_decimal(importe_cell)
            concepto_str = str(concepto_cell) if concepto_cell is not None else ""
            banco_str = str(banco_cell) if banco_cell is not None else ""
            keys.add((fecha_str, importe_dec, concepto_str, banco_str))
        return keys

    def _write_month(
        self,
        month_key: str,
        transactions: list[NormalizedTransaction],
        enable_summary: bool,
    ) -> None:
        """Write a batch of same-month transactions to the monthly workbook.

        Raises
        ------
        ExcelWriteError
            If writing is interrupted; the workbook is not saved.
        """
        path = self._workbook_path(month_key)
        wb, ws = self._load_or_create(path)

        # Build existing deduplication keys *before* writing new rows (4.4)
        existing_keys = self._build_existing_keys(ws)

        try:
            # --- 9.2: write new rows with duplicate detection ---
            for tx in transactions:
                key = _tx_to_key(tx)
                estado = _STATUS_DUPLICATE if key in existing_keys else _STATUS_NORMAL
                # Importe stored as float-compatible number; use Decimal → str → float
                # conversion to preserve precision in the Excel cell (openpyxl stores
                # numbers; Decimal is not natively supported but str is lossless for display).
                ws.append([
                    tx.fecha,           # stored as date → Excel date cell
                    float(tx.importe),  # stored as numeric cell (Req 4 schema)
                    tx.concepto,
                    tx.banco,
                    estado,
                ])
                # Also add the new key to the set so within-batch dupes are caught
                existing_keys.add(key)

            # --- 9.4: optional Resumen sheet ---
            if enable_summary:
                self._write_resumen(wb, ws)

        except Exception as exc:
            # Writing was interrupted — do NOT save (Req 4.5)
            raise ExcelWriteError(
                f"movimientos_{month_key}.xlsx: write interrupted, file not saved. "
                f"Cause: {exc}"
            ) from exc

        # --- 9.3: save only if all writing succeeded ---
        wb.save(str(path))

    def _write_resumen(self, wb: Workbook, ws_mov: Worksheet) -> None:
        """Create or replace the Resumen sheet with per-bank monthly totals.

        Totals are calculated from ALL rows in the Movimientos sheet (existing
        + newly written), using exact ``Decimal`` arithmetic (Req 5.2, 5.3).

        Parameters
        ----------
        wb:
            The workbook to update.
        ws_mov:
            The Movimientos worksheet (source of all rows).
        """
        # Remove existing Resumen sheet if present (Req 5.1: create or replace)
        if _SHEET_RESUMEN in wb.sheetnames:
            del wb[_SHEET_RESUMEN]

        ws_res = wb.create_sheet(_SHEET_RESUMEN)
        ws_res.append(list(_RESUMEN_HEADERS))

        # Accumulate totals per bank using Decimal (Req 5.2)
        income: dict[str, Decimal] = defaultdict(Decimal)
        expenses: dict[str, Decimal] = defaultdict(Decimal)

        for row in ws_mov.iter_rows(min_row=2, values_only=True):
            _, importe_cell, _, banco_cell, *_ = row
            if importe_cell is None or banco_cell is None:
                continue
            banco_str = str(banco_cell)
            importe_dec = _cell_to_decimal(importe_cell)
            if importe_dec > Decimal("0"):
                income[banco_str] += importe_dec
            elif importe_dec < Decimal("0"):
                expenses[banco_str] += importe_dec

        # Collect all banks present in either dict
        all_banks = sorted(set(income.keys()) | set(expenses.keys()))
        for banco in all_banks:
            ws_res.append([
                banco,
                float(income.get(banco, Decimal("0"))),
                float(expenses.get(banco, Decimal("0"))),
            ])


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _tx_to_key(tx: NormalizedTransaction) -> tuple:
    """Build the deduplication key for a NormalizedTransaction.

    Returns
    -------
    (fecha_str, importe_decimal, concepto, banco)
    """
    return (tx.fecha.isoformat(), tx.importe, tx.concepto, tx.banco)


def _cell_to_fecha_str(cell_value: object) -> str:
    """Convert a cell value that represents a date to an ISO 8601 string.

    openpyxl may return datetime.date, datetime.datetime, or a plain string
    depending on how the cell was written.
    """
    from datetime import date, datetime
    if isinstance(cell_value, datetime):
        return cell_value.date().isoformat()
    if isinstance(cell_value, date):
        return cell_value.isoformat()
    return str(cell_value)


def _cell_to_decimal(cell_value: object) -> Decimal:
    """Convert a cell value (number or string) to Decimal.

    Falls back to ``Decimal("0")`` if the value cannot be converted.
    """
    if cell_value is None:
        return Decimal("0")
    try:
        return Decimal(str(cell_value))
    except Exception:
        return Decimal("0")
