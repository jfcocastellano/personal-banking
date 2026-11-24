"""Monthly layout tab: a pure cell-grid builder plus a region-preserving writer.

The grid reproduces the reference accounting worksheet: individual expenses on
the left (B..E), the shared-expense catalogue in the middle (G..H) and the
income/summary/balances panel on the right (J..K). Column A stays empty as a
spacer.

``build_month_grid`` is a pure function of plain data, so the geometry is
testable without a network or a spreadsheet. ``LayoutWriter`` owns every
Google Sheets concern: it creates the tab once and afterwards rewrites only
the expense block and the summary/balances panel, which is what lets
hand-typed shared amounts survive a regeneration (FR-009).
"""

import logging
import math
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import gspread

from banking.connectors.enable_banking import Balance, Transaction
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


class RawTabCollisionError(Exception):
    """A tab still holding the raw movement grid was about to be written as layout.

    Raised on the refresh path when the target tab's ``B3:E`` headers are the raw
    pipeline's: with the layout tab renamed to the bare month, that tab is the
    one the owner is still migrating, and clearing it would destroy the raw rows.
    """


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

# The catalogue is a two-level list: a section header (``Alimentación``, ``Gatos``,
# ``Piso``, ``Streaming``, ``Transporte``...) followed by the concrete lines that hang
# from it. The owner asked for those lines to be tabulated (indented) under their
# header, as in the reference ledger, so this is the set that stays flush left.
SHARED_SECTION_HEADERS: tuple[str, ...] = (
    "Alimentación",
    "Entradas",
    "Farmacia",
    "Garaje Mossen Fenollar",
    "Recibos C.P",
    "Gatos",
    "Piso",
    "Regalos",
    "Restauración",
    "Streaming",
    "Tintorería",
    "Transporte",
    "Viajes",
    "*Otros",
)

# Indent of a tabulated line, in points, so it reads as hanging from its header. The
# ``Día`` lines go one step deeper: they are the day-to-day spend inside a section
# (``Gatos``, ``Piso``), and the owner asked for them a level further in.
SHARED_INDENT_POINTS = 24.0
SHARED_DEEP_INDENT_POINTS = 48.0
SHARED_DEEP_INDENT_LABELS: tuple[str, ...] = ("Día",)

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

# Content columns take their width from the widest rendered cell plus a margin
# (task 022: the owner asked for the widest element and a little slack). Columns A,
# F and I are spacers between the blocks and keep their default width.
_CONTENT_COLUMNS: tuple[int, ...] = (2, 3, 4, 5, 7, 8, 10, 11)  # B, C, D, E, G, H, J, K
_CHAR_PX = 7.8
_WIDTH_MARGIN = 28
_MIN_COLUMN_WIDTH = 90
# A single runaway description (a transfer memo can be 120 characters) must not push
# the table off the screen; the cell keeps the text, the column stops growing.
_MAX_COLUMN_WIDTH = 400
# Floors for the columns whose content arrives later as a formatted amount (``E``,
# ``H``, ``K``) or is typed by the owner (``K``): the panel keeps the room the owner
# just approved and every amount column fits a full ``#,##0.00 €`` figure.
_MIN_COLUMN_WIDTHS: dict[int, int] = {5: 130, 8: 130, 10: 200, 11: 130}

_TITLE_ROW = 2
_HEADER_ROW = 3
_EXPENSE_HEADERS: tuple[str, ...] = ("FECHA", "BANCO", "DESCRIPCIÓN", "IMPORTE")
_EXPENSE_FIRST_ROW = 4
_EXPENSE_LAST_ROW = _EXPENSE_FIRST_ROW + MAX_EXPENSE_ROWS - 1  # 403

# Catalogue length is the single source of truth for every offset below.
_CATEGORY_FIRST_ROW = 4
_CATEGORY_LAST_ROW = _CATEGORY_FIRST_ROW + len(CATEGORIES) - 1  # 52
_CATEGORY_TOTAL_ROW = _CATEGORY_LAST_ROW + 1  # 53

# Region the update path clears and rewrites: the header row plus the block. The
# header is inside on purpose — a tab created while 017/T4 was live carries
# `CATEGORÍA`/`TOTAL` on row 3, and rewriting the header heals it instead of
# leaving stale labels above the movement list until the month is recreated.
_EXPENSE_REGION = f"B{_HEADER_ROW}:E{_EXPENSE_LAST_ROW}"
_AMOUNT_RANGE = f"$E${_EXPENSE_FIRST_ROW}:$E${_EXPENSE_LAST_ROW}"

# Right-hand panel, top to bottom (task 022): the income table the owner fills by
# hand, the month summary computed from the expense block, then the balances
# snapshot. The income table reuses the J:K title and header rows, because it sits
# where the summary used to.
_INCOME_TITLE_ROW = _TITLE_ROW  # 2
_INCOME_HEADER_ROW = _HEADER_ROW  # 3
_INCOME_FIRST_ROW = _INCOME_HEADER_ROW + 1  # 4
INCOME_LABELS: tuple[str, ...] = (
    "Nómina",
    "Acciones IB",
    "Dividendos IB",
    "Opciones IB",
    "Intereses IB",
    "MyInvestor",
    "Parking",
)
_INCOME_LAST_ROW = _INCOME_FIRST_ROW + len(INCOME_LABELS) - 1  # 10
_INCOME_RANGE = f"K{_INCOME_FIRST_ROW}:K{_INCOME_LAST_ROW}"

# One blank row separates the income table from the summary and the summary from the
# balances block; inside the summary the outcome follows the three figures directly.
_SUMMARY_TITLE_ROW = _INCOME_LAST_ROW + 2  # 12
_SUMMARY_HEADER_ROW = _SUMMARY_TITLE_ROW + 1  # 13
_SUMMARY_INCOME_ROW = _SUMMARY_HEADER_ROW + 1  # 14
_SUMMARY_EXPENSE_ROW = _SUMMARY_INCOME_ROW + 1  # 15
_SUMMARY_SHARED_ROW = _SUMMARY_EXPENSE_ROW + 1  # 16
_SUMMARY_TOTAL_ROW = _SUMMARY_SHARED_ROW + 1  # 17

_BALANCE_TITLE_ROW = _SUMMARY_TOTAL_ROW + 2  # 19
_BALANCE_HEADER_ROW = _BALANCE_TITLE_ROW + 1  # 20
_BALANCE_FIRST_ROW = _BALANCE_HEADER_ROW + 1  # 21

_SUMMARY_TITLE = "RESUMEN MES"
_BALANCE_TITLE = "SALDO CUENTAS"
_INCOME_TITLE = "INGRESOS"
_PANEL_HEADERS: tuple[str, str] = ("CONCEPTO", "CANTIDAD")


def _summary_panel_last_row(balance_count: int) -> int:
    """Last row of the summary/balances panel: the balances total row."""
    return _BALANCE_FIRST_ROW + balance_count


# Panel height the update path clears. Deliberately larger than the four
# connectors, so a panel that shrank (an account removed, a bank offline)
# leaves no stale row behind.
_MAX_BALANCE_ROWS = 8
_SUMMARY_PANEL_LAST_ROW = _summary_panel_last_row(_MAX_BALANCE_ROWS)  # 29

_INCOME_TOTAL_FORMULA = f"=SUM({_INCOME_RANGE})"
# Expenses are shown positive and subtracted from the income, so the outcome reads
# like the owner's ledger: 368.39 - 1735.98 - 800.00 = -2167.59.
#
# The spreadsheet is in the ``es_ES`` locale, and there Sheets parses formulas with
# its own argument separator: ``SUMIF($E$4:$E$403,"<0",$E$4:$E$403)`` is stored as a
# formula but renders ``#ERROR!`` because a comma is a decimal mark there and the
# separator must be ``;``. ``SUMPRODUCT`` with one argument has no separator at all,
# so the same text works in any locale; blanks multiply to zero and drop out.
_OWN_EXPENSE_FORMULA = f"=-SUMPRODUCT({_AMOUNT_RANGE}*({_AMOUNT_RANGE}<0))"
_SHARED_TOTAL_FORMULA = f"=SUM(H{_CATEGORY_FIRST_ROW}:H{_CATEGORY_LAST_ROW})"
_SHARED_TOTAL_CELL_FORMULA = f"=H{_CATEGORY_TOTAL_ROW}"
_SUMMARY_TOTAL_FORMULA = f"=K{_SUMMARY_INCOME_ROW}-K{_SUMMARY_EXPENSE_ROW}-K{_SUMMARY_SHARED_ROW}"


def _summary_panel_range_last_row(balance_count: int) -> int:
    """Last row of the ``J:K`` panel every path clears, writes and formats.

    Creation and refresh both use this, so the money format covers the summary
    totals from the first run on and no path can format a different range.
    """
    return max(_summary_panel_last_row(balance_count), _SUMMARY_PANEL_LAST_ROW)


# Every title is a merged J:K band, so all five are merged at creation.
_TITLE_RANGES: tuple[str, ...] = (
    f"B{_TITLE_ROW}:E{_TITLE_ROW}",
    f"G{_TITLE_ROW}:H{_TITLE_ROW}",
    f"J{_INCOME_TITLE_ROW}:K{_INCOME_TITLE_ROW}",
    f"J{_SUMMARY_TITLE_ROW}:K{_SUMMARY_TITLE_ROW}",
    f"J{_BALANCE_TITLE_ROW}:K{_BALANCE_TITLE_ROW}",
)

# The raw pipeline's five columns (``banking.sync._HEADERS``). Duplicated on
# purpose: importing the sync pipeline from the sheet layer would invert the
# dependency, and a test pins the two lists equal so they cannot drift apart.
# Only the collision guard reads it — the layout writes four columns.
_RAW_HEADERS: tuple[str, ...] = (
    "Fecha de liquidación",
    "Banco",
    "Descripción",
    "Importe",
    "Divisa",
)

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


class BankSource(Protocol):
    """What the layout input mappers need from one bank's fetched data.

    Any per-bank result object that carries these three attributes can be
    mapped, whatever layer produced it; this keeps the mappers independent of
    whether the caller fetched one month for the layout or one pass for the
    daily job. The members are read-only properties so a frozen dataclass of
    the calling layer satisfies the protocol.
    """

    @property
    def bank_name(self) -> str: ...

    @property
    def transactions(self) -> Sequence[Transaction]: ...

    @property
    def balance(self) -> Balance | None: ...


def expense_rows_from_banks(banks: Sequence[BankSource]) -> list[ExpenseRow]:
    """The individual-expenses block: every transaction of every bank.

    Args:
        banks: The per-bank results, in the desired output order.

    Returns:
        One `ExpenseRow` per transaction, in bank order and then in the order
        each bank reported its transactions.
    """
    return [
        ExpenseRow(
            booking_date=transaction.booking_date,
            bank=bank.bank_name,
            description=transaction.description,
            amount=transaction.amount,
        )
        for bank in banks
        for transaction in bank.transactions
    ]


def balances_from_banks(banks: Sequence[BankSource]) -> list[AccountBalance]:
    """One balance row per bank, empty when the bank reported no balance.

    Args:
        banks: The per-bank results, in the desired output order.

    Returns:
        One `AccountBalance` per bank, in the same order as ``banks``. A bank
        without a balance yields ``amount=None``, ``currency="EUR"`` and
        ``reference_date=None``, so the cell stays empty instead of inventing
        a zero.
    """
    return [
        AccountBalance(
            bank=bank.bank_name,
            amount=bank.balance.amount if bank.balance is not None else None,
            currency=bank.balance.currency if bank.balance is not None else "EUR",
            reference_date=bank.balance.reference_date if bank.balance is not None else None,
        )
        for bank in banks
    ]


def layout_tab_name(month_start: date) -> str:
    """Return the layout tab name for the month starting on ``month_start``.

    Args:
        month_start: Any date of the target month; the day is ignored.

    Returns:
        ``<YYYY-MM>``, the bare month: since task 021 this is the only tab the
        month owns, so the `` Gastos`` suffix that told the two tabs apart is gone.
    """
    return month_start.strftime("%Y-%m")


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
    _place_income(place)
    _place_expenses(place, transactions)
    _place_shared_expenses(place)
    _place_summary(place)
    _place_balances(place, balances)

    return _materialize(cells, max(max(cells), _CATEGORY_TOTAL_ROW))


def _place_titles_and_headers(place: Place) -> None:
    # Titles: only the first cell of each merged range is filled.
    place(_TITLE_ROW, _COL_B, "GASTOS")
    place(_TITLE_ROW, _COL_G, "GASTOS COMUNES")

    for offset, header in enumerate(_EXPENSE_HEADERS):
        place(_HEADER_ROW, _COL_B + offset, header)

    for column, header in ((_COL_G, "CATEGORÍA"), (_COL_H, "TOTAL")):
        place(_HEADER_ROW, column, header)


def _place_income(place: Place) -> None:
    """The income table: fixed concept labels, amounts left for the owner.

    The amounts in ``K`` are typed by hand (there is no bank transaction that tells
    "Dividendos IB" from "Opciones IB"), so nothing here writes below the labels.
    """
    place(_INCOME_TITLE_ROW, _COL_J, _INCOME_TITLE)
    place(_INCOME_HEADER_ROW, _COL_J, _PANEL_HEADERS[0])
    place(_INCOME_HEADER_ROW, _COL_K, _PANEL_HEADERS[1])
    for offset, label in enumerate(INCOME_LABELS):
        place(_INCOME_FIRST_ROW + offset, _COL_J, label)


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
    """The month summary: income minus own and shared expenses, in that order."""
    place(_SUMMARY_TITLE_ROW, _COL_J, _SUMMARY_TITLE)
    place(_SUMMARY_HEADER_ROW, _COL_J, _PANEL_HEADERS[0])
    place(_SUMMARY_HEADER_ROW, _COL_K, _PANEL_HEADERS[1])
    place(_SUMMARY_INCOME_ROW, _COL_J, "Ingresos totales")
    place(_SUMMARY_INCOME_ROW, _COL_K, _INCOME_TOTAL_FORMULA)
    place(_SUMMARY_EXPENSE_ROW, _COL_J, "Gastos míos")
    place(_SUMMARY_EXPENSE_ROW, _COL_K, _OWN_EXPENSE_FORMULA)
    place(_SUMMARY_SHARED_ROW, _COL_J, "Gastos comunes")
    place(_SUMMARY_SHARED_ROW, _COL_K, _SHARED_TOTAL_CELL_FORMULA)
    place(_SUMMARY_TOTAL_ROW, _COL_J, "Total")
    place(_SUMMARY_TOTAL_ROW, _COL_K, _SUMMARY_TOTAL_FORMULA)


def _place_balances(place: Place, balances: Sequence[AccountBalance]) -> None:
    place(_BALANCE_TITLE_ROW, _COL_J, _BALANCE_TITLE)
    place(_BALANCE_HEADER_ROW, _COL_J, "CUENTA")
    place(_BALANCE_HEADER_ROW, _COL_K, _PANEL_HEADERS[1])

    for offset, balance in enumerate(balances):
        row = _BALANCE_FIRST_ROW + offset
        place(row, _COL_J, balance.bank)
        if balance.amount is not None:
            place(row, _COL_K, float(balance.amount))

    total_row = _BALANCE_FIRST_ROW + len(balances)
    # ``TOTAL`` in capitals, like the owner's capture; the summary keeps its ``Total``.
    place(total_row, _COL_J, "TOTAL")
    if balances:
        # SUM ignores the blank cells of accounts without a reported balance, so
        # the range stays stable when the user later types one in by hand.
        place(total_row, _COL_K, f"=SUM(K{_BALANCE_FIRST_ROW}:K{total_row - 1})")

    # The reference date used to sit under the total as its own row; the owner asked
    # for the total to be the last row of the block, so nothing is written below it.


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


def _ensure_not_raw_tab(worksheet: gspread.Worksheet) -> None:
    """Refuse a tab that still holds the raw grid instead of overwriting it.

    The refresh path clears ``B3:E403`` before writing, so a tab left in the raw
    shape would silently lose every row it holds. The tab that carried that shape
    is exactly the one the layout now targets (same bare month), which makes this
    the one collision the rename cannot prevent by ordering alone.

    Raises:
        RawTabCollisionError: the existing ``B3:E`` headers are the raw ones.
        SheetsAccessError: the header row could not be read.
    """
    try:
        existing = worksheet.row_values(_HEADER_ROW)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc

    # gspread returns the row from column A, so an empty A3 arrives as a leading
    # blank and the headers start at index 1. Compare from the first filled cell.
    while existing and not str(existing[0]).strip():
        existing = existing[1:]

    if [str(cell).strip() for cell in existing[: len(_RAW_HEADERS)]] == list(_RAW_HEADERS):
        raise RawTabCollisionError(
            f"tab {worksheet.title!r} still holds the raw movements grid, so writing "
            f"the layout would destroy those rows; delete that tab and rerun, the "
            f"layout tab is now the bare month"
        )


def _write_grid(worksheet: gspread.Worksheet, grid: list[list[CellValue]]) -> None:
    """Write the whole grid from A1 with USER_ENTERED, so formulas evaluate."""
    try:
        worksheet.update(values=grid, raw=False)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _write_expense_region(worksheet: gspread.Worksheet, transactions: Sequence[ExpenseRow]) -> None:
    """Clear and rewrite only B3:E403; every other cell keeps its value.

    The header row travels with the block, so a tab left in an older shape (the
    category layout of 017/T4) is corrected by the next run instead of keeping
    labels that no longer describe the columns.

    Always written with the default RAW input option, on the creation path too:
    bank descriptions are data, never formulas, and the expense block must end
    up in the same cell form whether this is the first run or the tenth.
    """
    rows: list[list[CellValue]] = [[*_EXPENSE_HEADERS], *_expense_rows(transactions)]
    try:
        worksheet.batch_clear([_EXPENSE_REGION])
        worksheet.update(values=rows, range_name=f"B{_HEADER_ROW}")
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _panel_is_current(worksheet: gspread.Worksheet) -> bool:
    """Whether the right-hand panel already holds the two-table geometry (022).

    The marker is the summary title. A tab written before the income table existed
    keeps the old summary in rows 4-6, exactly where the income rows are now; a
    refresh that only cleared from the summary down would leave those cells behind
    and read the old totals as hand-typed income. Reading the marker lets the first
    run after the change reset the whole panel once, and every later run clear only
    what it owns.

    Raises:
        SheetsAccessError: the marker row could not be read.
    """
    try:
        row = worksheet.row_values(_SUMMARY_TITLE_ROW)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc

    # gspread returns the row from column A, so index ``_COL_J`` is column J.
    value = row[_COL_J] if len(row) > _COL_J else ""
    return str(value).strip() == _SUMMARY_TITLE


def shared_sub_item_rows() -> tuple[int, ...]:
    """Sheet rows in ``G`` of the catalogue lines that hang from a section header."""
    return tuple(
        _CATEGORY_FIRST_ROW + offset
        for offset, category in enumerate(CATEGORIES)
        if category not in SHARED_SECTION_HEADERS
    )


def _shared_indent_points(category: str) -> float:
    return (
        SHARED_DEEP_INDENT_POINTS if category in SHARED_DEEP_INDENT_LABELS else SHARED_INDENT_POINTS
    )


def shared_indent_requests(sheet_id: int) -> list[dict[str, object]]:
    """``repeatCell`` requests that indent the tabulated shared-expense lines."""
    column = _COL_G + 1  # 1-based for the A1-style range shape below
    return [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": row - 1,
                    "endRowIndex": row,
                    "startColumnIndex": column - 1,
                    "endColumnIndex": column,
                },
                "cell": {
                    "userEnteredFormat": {
                        "padding": {
                            "left": _shared_indent_points(CATEGORIES[row - _CATEGORY_FIRST_ROW])
                        }
                    },
                },
                "fields": "userEnteredFormat.padding",
            }
        }
        for row in shared_sub_item_rows()
    ]


def _rendered_length(value: CellValue) -> int:
    """Characters a cell occupies; formulas count as zero, their value is not known."""
    if value is None:
        return 0
    text = str(value).strip()
    if not text or text.startswith("="):
        return 0
    return len(text)


def column_widths(rows: Iterable[Sequence[CellValue]]) -> dict[int, int]:
    """Width in pixels per content column: widest rendered cell plus a margin.

    Columns are 1-based, so ``B`` is 2. Strings starting with ``=`` are skipped: a
    formula's width is not its source text, and the writer reads the sheet with
    formulas already rendered.
    """
    longest: dict[int, int] = dict.fromkeys(_CONTENT_COLUMNS, 0)
    for row in rows:
        for column in _CONTENT_COLUMNS:
            index = column - 1
            if index < len(row):
                longest[column] = max(longest[column], _rendered_length(row[index]))
    widths: dict[int, int] = {}
    for column in _CONTENT_COLUMNS:
        needed = longest[column] * _CHAR_PX + _WIDTH_MARGIN
        floor = _MIN_COLUMN_WIDTHS.get(column, _MIN_COLUMN_WIDTH)
        widths[column] = min(_MAX_COLUMN_WIDTH, max(floor, math.ceil(needed / 5) * 5))
    return widths


def content_width_requests(
    sheet_id: int, rows: Iterable[Sequence[CellValue]]
) -> list[dict[str, object]]:
    """``updateDimensionProperties`` requests that size the content columns."""
    return [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": column - 1,
                    "endIndex": column,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        }
        for column, width in column_widths(rows).items()
    ]


def _apply_geometry(worksheet: gspread.Worksheet, spreadsheet: gspread.Spreadsheet) -> None:
    """Indent the tabulated lines and fit the columns, after the values are written.

    Both are derived from what the tab holds, so running them on every pass is
    idempotent: a column that grew keeps its width, and a line the owner un-indented
    by hand gets its padding back.
    """
    try:
        rows = worksheet.get_all_values()
        requests = [
            *shared_indent_requests(worksheet.id),
            *content_width_requests(worksheet.id, rows),
        ]
        spreadsheet.batch_update({"requests": requests})
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _write_summary_region(worksheet: gspread.Worksheet, balances: Sequence[AccountBalance]) -> None:
    """Clear and rewrite the ``J:K`` panel from the summary down to its floor.

    The same placement helpers as ``build_month_grid`` fill the region, so the
    creation path and the daily refresh cannot drift apart. Columns A-I are
    never addressed, which is what keeps ``G:H`` (hand-typed shared amounts) and
    ``B:E`` (expenses) intact.

    The income table above the summary is not cleared on refresh: its seven amounts
    are typed by hand and the summary reads them. Only a tab still in the pre-022
    geometry, where those rows hold the old summary, is reset once from the income
    title down, which is also what writes the fixed labels there.

    The write is USER_ENTERED because the summary cells are formulas and must
    evaluate. The clear always reaches ``_SUMMARY_PANEL_LAST_ROW`` even when the
    panel is shorter, so a dropped account leaves no stale row behind.
    """
    reset_income_table = not _panel_is_current(worksheet)
    first_row = _INCOME_TITLE_ROW if reset_income_table else _SUMMARY_TITLE_ROW
    last_row = _summary_panel_range_last_row(len(balances))

    cells: dict[int, list[CellValue]] = {}

    def place(row: int, column: int, value: CellValue) -> None:
        line = cells.setdefault(row, [])
        while len(line) <= column:
            line.append(None)
        line[column] = value

    if reset_income_table:
        _place_income(place)
    _place_summary(place)
    _place_balances(place, balances)

    grid: list[list[CellValue]] = []
    for row in range(first_row, last_row + 1):
        line = cells.get(row, [])
        grid.append([line[column] if column < len(line) else None for column in (_COL_J, _COL_K)])

    try:
        worksheet.batch_clear([f"J{first_row}:K{last_row}"])
        worksheet.update(values=grid, range_name=f"J{first_row}", raw=False)
        worksheet.format(f"K{_INCOME_FIRST_ROW}:K{last_row}", _MONEY_FORMAT)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _merge_titles(worksheet: gspread.Worksheet) -> None:
    """Merge the five title bands the layout contract declares.

    Creation only: a merge is a structural property of the tab, and neither the
    expense region nor the summary panel re-merges anything on update.
    """
    try:
        for title_range in _TITLE_RANGES:
            worksheet.merge_cells(title_range)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _apply_light_formatting(worksheet: gspread.Worksheet, balance_count: int) -> None:
    """Bold the titles and headers, and use a euro format for the money cells.

    The ``K`` range is the whole income/summary/balances panel, the same one
    ``_write_summary_region`` formats on every later run, so the summary totals
    look like money from the first run on.
    """
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
            f"K{_INCOME_FIRST_ROW}:K{_summary_panel_range_last_row(balance_count)}",
            _MONEY_FORMAT,
        )
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


class LayoutWriter:
    """Owns the ``<YYYY-MM>`` tab.

    The tab is created once with the full grid. Every later run clears and
    rewrites ``B3:E403`` (header included) and the ``J:K`` summary/balances panel
    (so the balances stay a fresh snapshot with the bank's reference date), and
    nothing else. The shared-expense block ``G:H`` and the hand-typed income
    amounts ``K4:K10`` are therefore never touched again, which is what keeps
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
                # expense block RAW so both paths leave B3:E403 in the same form.
                _write_expense_region(worksheet, transactions)
                _merge_titles(worksheet)
                _apply_light_formatting(worksheet, balance_count=len(balances))
            else:
                _ensure_not_raw_tab(worksheet)
                _write_expense_region(worksheet, transactions)
                _write_summary_region(worksheet, balances)
            # Both paths: widths follow the content the tab now holds, hand-typed
            # cells included, so a long description widens its column on its own.
            _apply_geometry(worksheet, spreadsheet)
        except (
            RawTabCollisionError,
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
