"""Monthly layout tab: a pure cell-grid builder plus a region-preserving writer.

The grid reproduces the reference accounting worksheet: individual expenses on
the left (B..E), the shared-expense catalogue in the middle (G..H) and the
income/summary/balances panel on the right (J..K). Column A stays empty as a
spacer.

``build_month_grid`` is a pure function of plain data, so the geometry is
testable without a network or a spreadsheet. ``LayoutWriter`` owns every
Google Sheets concern: it creates the tab once and afterwards rewrites only
the expense block, which is what lets hand-typed shared amounts survive a
regeneration (FR-009).
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import gspread

from banking.sheets.writer import (
    CellValue,
    SheetsAccessError,
    SheetsAPIError,
    SheetsConfigError,
    SheetsQuotaExceededError,
    _build_client,
    _open_spreadsheet,
    _translate_api_error,
)

logger = logging.getLogger(__name__)

# Writes one cell into the grid under construction: (row, column, value).
Place = Callable[[int, int, CellValue], None]

# Appendix of specs/008-monthly-sheet-layout/tasks.md, verbatim and whitespace-trimmed.
CATEGORIES: tuple[str, ...] = (
    "Alimentación",
    "Mercadona",
    "Consum",
    "Otros",
    "Entradas",
    "Farmacia",
    "Garaje Mossen Fenollar",
    "Recibos C.P",
    "Gatos",
    "Petsitter",
    "Día",
    "Día",
    "Día",
    "Veterinario",
    "Zooplus",
    "Piso",
    "Agua",
    "Gas",
    "Limpieza",
    "Día",
    "Día",
    "Día",
    "Día",
    "Luz",
    "Menaje",
    "Regalos",
    "Restauración",
    "Streaming",
    "HBO",
    "Spotify",
    "Tintorería",
    "Transporte",
    "AVE día",
    "AVE día",
    "AVE día",
    "Motos alquiler",
    "Taxi",
    "VTC",
    "Coche",
    "Gasolina día",
    "Gasolina día",
    "Gasolina día",
    "Gasolina día",
    "Lavado",
    "Parking",
    "Peajes",
    "Taller",
    "Viajes",
    "*Otros",
)

MAX_EXPENSE_ROWS = 400

# Grid invariant, relied on by the writer and by anything reading this module's
# geometry: the builder returns rows starting at sheet row 1, so ``grid[i]`` is
# sheet row ``i + 1``, and index 0 of every row is column A, the spacer.
# Creation therefore writes the grid from A1 in one call, while updates address
# the expense block at B4.
#
# Column indexes inside a grid row: index 0 is column A, the spacer.
_COLUMN_COUNT = 11
_COL_B = 1
_COL_C = 2
_COL_D = 3
_COL_E = 4
_COL_G = 6
_COL_H = 7
_COL_J = 9
_COL_K = 10

_TITLE_ROW = 2
_HEADER_ROW = 3
_EXPENSE_FIRST_ROW = 4
_EXPENSE_LAST_ROW = _EXPENSE_FIRST_ROW + MAX_EXPENSE_ROWS - 1  # 403

# Catalogue length is the single source of truth for every offset below.
_CATEGORY_FIRST_ROW = 4
_CATEGORY_LAST_ROW = _CATEGORY_FIRST_ROW + len(CATEGORIES) - 1  # 52
_CATEGORY_TOTAL_ROW = _CATEGORY_LAST_ROW + 1  # 53

_SUMMARY_FIRST_ROW = _CATEGORY_FIRST_ROW
_SUMMARY_EXPENSE_ROW = _SUMMARY_FIRST_ROW + 1
_SUMMARY_TOTAL_ROW = _SUMMARY_FIRST_ROW + 2

_BALANCE_TITLE_ROW = _SUMMARY_TOTAL_ROW + 2  # 8
_BALANCE_HEADER_ROW = _BALANCE_TITLE_ROW + 1
_BALANCE_FIRST_ROW = _BALANCE_HEADER_ROW + 1

_EXPENSE_REGION = f"B{_EXPENSE_FIRST_ROW}:E{_EXPENSE_LAST_ROW}"
_AMOUNT_RANGE = f"$E${_EXPENSE_FIRST_ROW}:$E${_EXPENSE_LAST_ROW}"
_INCOME_FORMULA = f'=SUMIF({_AMOUNT_RANGE},">0",{_AMOUNT_RANGE})'
_SPEND_FORMULA = f'=SUMIF({_AMOUNT_RANGE},"<0",{_AMOUNT_RANGE})'
_SHARED_TOTAL_FORMULA = f"=SUM(H{_CATEGORY_FIRST_ROW}:H{_CATEGORY_LAST_ROW})"

_TITLE_RANGES: tuple[str, ...] = (
    f"B{_TITLE_ROW}:E{_TITLE_ROW}",
    f"G{_TITLE_ROW}:H{_TITLE_ROW}",
    f"J{_TITLE_ROW}:K{_TITLE_ROW}",
)

_NO_REFERENCE_DATE = "sin dato de referencia"

_BOLD = {"textFormat": {"bold": True}}
_MONEY_FORMAT = {"numberFormat": {"type": "NUMBER", "pattern": '#,##0.00 "€"'}}


@dataclass(frozen=True)
class ExpenseRow:
    """One individual expense, as it appears in the left-hand block."""

    booking_date: date
    bank: str
    description: str
    amount: Decimal


@dataclass(frozen=True)
class AccountBalance:
    """One account's reported balance for the balances panel.

    ``amount`` is ``None`` when the bank reported no usable balance; the cell
    then stays empty instead of inventing a zero.
    """

    bank: str
    amount: Decimal | None
    currency: str = "EUR"
    reference_date: date | None = None


def _expense_row(transaction: ExpenseRow) -> list[CellValue]:
    """The four expense columns, in the order FR-003 requires (no currency)."""
    return [
        transaction.booking_date.isoformat(),
        transaction.bank,
        transaction.description,
        float(transaction.amount),
    ]


def _sort_key(transaction: ExpenseRow) -> tuple[date, str, str]:
    return (transaction.booking_date, transaction.bank, transaction.description)


def _expense_rows(transactions: Sequence[ExpenseRow]) -> list[list[CellValue]]:
    """Sorted, deterministic expense rows: date, then bank, then description."""
    return [_expense_row(transaction) for transaction in sorted(transactions, key=_sort_key)]


def _reference_label(balances: Sequence[AccountBalance]) -> str:
    dates = [balance.reference_date for balance in balances if balance.reference_date is not None]
    if not dates:
        return _NO_REFERENCE_DATE
    return max(dates).isoformat()


def _materialize(cells: dict[int, list[CellValue]], last_row: int) -> list[list[CellValue]]:
    grid: list[list[CellValue]] = []
    for row in range(1, last_row + 1):
        line = cells.get(row, [])
        grid.append(line + [None] * (_COLUMN_COUNT - len(line)))
    return grid


def build_month_grid(
    transactions: Sequence[ExpenseRow],
    balances: Sequence[AccountBalance],
) -> list[list[CellValue]]:
    """Return the whole layout grid, row 0 being sheet row 1 and column 0 column A.

    Formulas are plain strings starting with ``=``, exactly as Google Sheets
    expects them; the writer is what asks Sheets to interpret them.

    Raises:
        ValueError: when the month has more than ``MAX_EXPENSE_ROWS``
            transactions. The block is never truncated silently.
    """
    if len(transactions) > MAX_EXPENSE_ROWS:
        raise ValueError(
            f"The expense block holds at most {MAX_EXPENSE_ROWS} transactions per month, "
            f"got {len(transactions)}. Narrow the month or raise the ceiling."
        )

    cells: dict[int, list[CellValue]] = {}

    def place(row: int, column: int, value: CellValue) -> None:
        line = cells.setdefault(row, [])
        while len(line) <= column:
            line.append(None)
        line[column] = value

    _place_titles_and_headers(place)
    _place_expenses(place, transactions)
    _place_shared_expenses(place)
    _place_summary(place)
    _place_balances(place, balances)

    return _materialize(cells, max(max(cells), _CATEGORY_TOTAL_ROW))


def _place_titles_and_headers(place: Place) -> None:
    # Titles: only the first cell of each merged range is filled.
    place(_TITLE_ROW, _COL_B, "GASTOS")
    place(_TITLE_ROW, _COL_G, "GASTOS COMUNES")
    place(_TITLE_ROW, _COL_J, "INGRESOS")

    for column, header in (
        (_COL_B, "FECHA"),
        (_COL_C, "BANCO"),
        (_COL_D, "DESCRIPCIÓN"),
        (_COL_E, "IMPORTE"),
        (_COL_G, "CATEGORÍA"),
        (_COL_H, "TOTAL"),
        (_COL_J, "CONCEPTO"),
        (_COL_K, "IMPORTE"),
    ):
        place(_HEADER_ROW, column, header)


def _place_expenses(place: Place, transactions: Sequence[ExpenseRow]) -> None:
    for offset, values in enumerate(_expense_rows(transactions)):
        for column_offset, value in enumerate(values):
            place(_EXPENSE_FIRST_ROW + offset, _COL_B + column_offset, value)


def _place_shared_expenses(place: Place) -> None:
    """Catalogue labels, hand-typed totals left empty, then the total row."""
    for offset, category in enumerate(CATEGORIES):
        place(_CATEGORY_FIRST_ROW + offset, _COL_G, category)
    place(_CATEGORY_TOTAL_ROW, _COL_G, "Total")
    place(_CATEGORY_TOTAL_ROW, _COL_H, _SHARED_TOTAL_FORMULA)


def _place_summary(place: Place) -> None:
    """Formulas over the expense amount column; signed amounts are kept as-is."""
    place(_SUMMARY_FIRST_ROW, _COL_J, "Ingresos")
    place(_SUMMARY_FIRST_ROW, _COL_K, _INCOME_FORMULA)
    place(_SUMMARY_EXPENSE_ROW, _COL_J, "Gastos")
    place(_SUMMARY_EXPENSE_ROW, _COL_K, _SPEND_FORMULA)
    place(_SUMMARY_TOTAL_ROW, _COL_J, "Total")
    place(_SUMMARY_TOTAL_ROW, _COL_K, f"=K{_SUMMARY_FIRST_ROW}+K{_SUMMARY_EXPENSE_ROW}")


def _place_balances(place: Place, balances: Sequence[AccountBalance]) -> None:
    place(_BALANCE_TITLE_ROW, _COL_J, "SALDO CUENTAS")
    place(_BALANCE_HEADER_ROW, _COL_J, "CUENTA")
    place(_BALANCE_HEADER_ROW, _COL_K, "SALDO")

    for offset, balance in enumerate(balances):
        row = _BALANCE_FIRST_ROW + offset
        place(row, _COL_J, balance.bank)
        if balance.amount is not None:
            place(row, _COL_K, float(balance.amount))

    total_row = _BALANCE_FIRST_ROW + len(balances)
    place(total_row, _COL_J, "Total")
    if balances:
        # SUM ignores the blank cells of accounts without a reported balance, so
        # the range stays stable when the user later types one in by hand.
        place(total_row, _COL_K, f"=SUM(K{_BALANCE_FIRST_ROW}:K{total_row - 1})")

    reference_row = total_row + 1
    place(reference_row, _COL_J, "Saldos al")
    place(reference_row, _COL_K, _reference_label(balances))


def _resolve_layout_worksheet(
    spreadsheet: gspread.Spreadsheet, tab_name: str, rows: int
) -> tuple[gspread.Worksheet, bool]:
    """Return the target worksheet and whether it had to be created."""
    try:
        return spreadsheet.worksheet(tab_name), False
    except gspread.exceptions.WorksheetNotFound:
        pass
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc

    try:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=rows, cols=_COLUMN_COUNT)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc
    return worksheet, True


def _write_grid(worksheet: gspread.Worksheet, grid: list[list[CellValue]]) -> None:
    """Write the whole grid from A1 with USER_ENTERED, so formulas evaluate."""
    try:
        worksheet.update(values=grid, raw=False)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _write_expense_region(worksheet: gspread.Worksheet, transactions: Sequence[ExpenseRow]) -> None:
    """Clear and rewrite only B4:E403; every other cell keeps its value.

    Always written with the default RAW input option, on the creation path too:
    bank descriptions are data, never formulas, and the expense block must end
    up in the same cell form whether this is the first run or the tenth.
    """
    rows = _expense_rows(transactions)
    try:
        worksheet.batch_clear([_EXPENSE_REGION])
        if rows:
            worksheet.update(values=rows, range_name=f"B{_EXPENSE_FIRST_ROW}")
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _merge_titles(worksheet: gspread.Worksheet) -> None:
    """Merge the three title ranges the layout contract declares.

    Creation only: a merge is a structural property of the tab, and the update
    path must not touch anything outside the expense region.
    """
    try:
        for title_range in _TITLE_RANGES:
            worksheet.merge_cells(title_range)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _balance_total_row(balance_count: int) -> int:
    return _BALANCE_FIRST_ROW + balance_count


def _apply_light_formatting(worksheet: gspread.Worksheet, balance_count: int) -> None:
    """Bold the titles and headers, and use a euro format for the money cells."""
    try:
        worksheet.format(f"B{_TITLE_ROW}:K{_TITLE_ROW}", _BOLD)
        worksheet.format(f"B{_HEADER_ROW}:K{_HEADER_ROW}", _BOLD)
        worksheet.format(
            f"E{_EXPENSE_FIRST_ROW}:E{_EXPENSE_LAST_ROW}",
            _MONEY_FORMAT,
        )
        worksheet.format(
            f"H{_CATEGORY_FIRST_ROW}:H{_CATEGORY_TOTAL_ROW}",
            _MONEY_FORMAT,
        )
        worksheet.format(
            f"K{_BALANCE_FIRST_ROW}:K{_balance_total_row(balance_count)}",
            _MONEY_FORMAT,
        )
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


class LayoutWriter:
    """Owns the ``<YYYY-MM> Gastos`` tab.

    The tab is created once with the full grid; every later run clears and
    rewrites only ``B4:E403``. The shared-expense catalogue, the summary and
    the balances panel are therefore never touched again, which is what keeps
    hand-typed amounts safe (FR-009).
    """

    def __init__(self, client: gspread.Client | None = None) -> None:
        self._client = client

    def write(
        self,
        document_id: str,
        tab_name: str,
        transactions: Sequence[ExpenseRow],
        balances: Sequence[AccountBalance],
    ) -> None:
        """Create the layout tab, or rewrite its expense block if it exists.

        Raises:
            ValueError: more transactions than the block holds; raised before
                the document is touched.
            SheetsConfigError: invalid/missing service account credentials.
            SheetsAccessError: document or tab inaccessible.
            SheetsQuotaExceededError: Google Sheets API quota exceeded.
            SheetsAPIError: any other unexpected API error.
        """
        start = time.monotonic()
        # Pure and validating: a too-large month fails before any API call.
        grid = build_month_grid(transactions, balances)

        try:
            client = self._client or _build_client()
            spreadsheet = _open_spreadsheet(client, document_id)
            worksheet, created = _resolve_layout_worksheet(
                spreadsheet, tab_name, rows=max(len(grid), _EXPENSE_LAST_ROW)
            )
            if created:
                _write_grid(worksheet, grid)
                # USER_ENTERED above turns ISO dates into date values; rewrite the
                # expense block RAW so both paths leave B4:E403 in the same form.
                _write_expense_region(worksheet, transactions)
                _merge_titles(worksheet)
                _apply_light_formatting(worksheet, balance_count=len(balances))
            else:
                _write_expense_region(worksheet, transactions)
        except (
            SheetsConfigError,
            SheetsAccessError,
            SheetsQuotaExceededError,
            SheetsAPIError,
        ) as exc:
            logger.error(
                "Sheets write failed: tab=%s category=%s reason=%s",
                tab_name,
                type(exc).__name__,
                exc,
            )
            raise

        duration = time.monotonic() - start
        logger.info(
            "Sheets write succeeded: tab=%s rows_written=%d created=%s duration=%.3fs",
            tab_name,
            len(transactions),
            created,
            duration,
        )
