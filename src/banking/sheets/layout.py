"""Monthly layout tab: a pure cell-grid builder plus a region-preserving writer.

The grid reproduces the reference accounting worksheet: the category-sums block
on the left (B..C), the shared-expense catalogue in the middle (G..H) and the
income/summary/balances panel on the right (J..K). Column A stays empty as a
spacer.

``build_month_grid`` is a pure function of plain data, so the geometry is
testable without a network or a spreadsheet. ``LayoutWriter`` owns every
Google Sheets concern: it creates the tab once and afterwards rewrites only
the category-sums block and the summary/balances panel, which is what lets
hand-typed shared amounts survive a regeneration (FR-009).
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

import gspread

from banking.categories import category_cell
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

# Category-sums block ceiling: one row per distinct category (50 data rows,
# sheet rows 4..53). Exceeding it fails loudly instead of truncating silently.
MAX_CATEGORY_ROWS = 50

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


def _summary_panel_last_row(balance_count: int) -> int:
    """Last row of the summary/balances panel for ``balance_count`` accounts."""
    return _BALANCE_FIRST_ROW + balance_count + 1


_CATEGORY_SUM_FIRST_ROW = 4
_CATEGORY_SUM_LAST_ROW = _CATEGORY_SUM_FIRST_ROW + MAX_CATEGORY_ROWS - 1  # 53

# Panel height the update path clears. Deliberately larger than the four
# connectors, so a panel that shrank (an account removed, a bank offline)
# leaves no stale row behind.
_MAX_BALANCE_ROWS = 8
_SUMMARY_PANEL_LAST_ROW = _summary_panel_last_row(_MAX_BALANCE_ROWS)  # 19


def _summary_panel_range_last_row(balance_count: int) -> int:
    """Last row of the ``J:K`` panel every path clears, writes and formats.

    Creation and refresh both use this, so the money format covers the summary
    totals from the first run on and no path can format a different range.
    """
    return max(_summary_panel_last_row(balance_count), _SUMMARY_PANEL_LAST_ROW)


_SPEND_FORMULA = f"=SUM(C{_CATEGORY_SUM_FIRST_ROW}:C{_CATEGORY_SUM_LAST_ROW})"  # 50 negative sums

# The movements tab the income formula reads: column E holds the signed Importe
# of every raw movement, down to a fixed deep row so late arrivals are included.
_MOVEMENTS_FIRST_ROW = 4
_MOVEMENTS_LAST_ROW = 10000


def _income_formula(movements_tab: str) -> str:
    """The cross-tab ``SUMIF`` over the movements tab's Importe column E."""
    amount_range = f"'{movements_tab}'!$E${_MOVEMENTS_FIRST_ROW}:$E${_MOVEMENTS_LAST_ROW}"
    return f'=SUMIF({amount_range},">0",{amount_range})'


_SHARED_TOTAL_FORMULA = f"=SUM(H{_CATEGORY_FIRST_ROW}:H{_CATEGORY_LAST_ROW})"

# Legacy region the refresh clears: the old four-column expense block's headers
# and rows (sheet rows 3..403), so pre-T4 tabs are cleaned on the first run
# against this code.
_LEGACY_EXPENSE_REGION = "B3:E403"

_TITLE_RANGES: tuple[str, ...] = (
    f"B{_TITLE_ROW}:E{_TITLE_ROW}",
    f"G{_TITLE_ROW}:H{_TITLE_ROW}",
    f"J{_TITLE_ROW}:K{_TITLE_ROW}",
)

_NO_REFERENCE_DATE = "sin dato de referencia"

# Tab-name suffix shared by every layout tab. ``banking.cli.layout`` builds its
# tab names through ``layout_tab_name``, so the format lives here only.
_LAYOUT_TAB_SUFFIX = " Gastos"

_BOLD = {"textFormat": {"bold": True}}
_MONEY_FORMAT = {"numberFormat": {"type": "NUMBER", "pattern": '#,##0.00 "€"'}}


_SIN_CATEGORIA = "SIN CATEGORÍA"

_CATEGORY_HEADER = "CATEGORÍA"
_TOTAL_HEADER = "TOTAL GASTOS"


@dataclass(frozen=True)
class ExpenseRow:
    """One transaction carried into the layout, with its resolved category.

    ``category`` is the display cell ``category_cell`` produced: a Spanish
    label when the code is mapped, the raw code otherwise, or an empty string
    when the bank sent no code. The sums block groups empty cells under
    ``SIN CATEGORÍA`` so the totals still add up.
    """

    booking_date: date
    bank: str
    description: str
    amount: Decimal
    category: str = ""


@dataclass(frozen=True)
class CategoryTotal:
    """One category's expense total, as one sums-block row."""

    category: str
    total: Decimal


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
    """Every transaction of every bank, with its resolved category cell.

    Args:
        banks: The per-bank results, in the desired output order.

    Returns:
        One `ExpenseRow` per transaction, in bank order and then in the order
        each bank reported its transactions. ``category`` is filled through
        ``banking.categories.category_cell``: mapped label, raw code, or empty.
    """
    return [
        ExpenseRow(
            booking_date=transaction.booking_date,
            bank=bank.bank_name,
            description=transaction.description,
            amount=transaction.amount,
            category=category_cell(transaction.merchant_category_code),
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
        ``<YYYY-MM> Gastos``, the single tab-name format the layout owns.
    """
    return f"{month_start.strftime('%Y-%m')}{_LAYOUT_TAB_SUFFIX}"


def expense_category_totals(rows: Sequence[ExpenseRow]) -> list[CategoryTotal]:
    """Group the expense rows by category and sum their signed amounts.

    Only expenses (``amount < 0``) are grouped: incomes never inflate the
    sums block. Rows without a category code share the ``SIN CATEGORÍA``
    group so the totals still add up. The result is deterministic: totals
    ascending (most negative first), then category ascending.
    """
    totals: dict[str, Decimal] = {}
    for row in rows:
        if row.amount >= Decimal("0"):
            continue
        label = row.category if row.category else _SIN_CATEGORIA
        totals[label] = totals.get(label, Decimal("0")) + row.amount
    return [
        CategoryTotal(category=label, total=total)
        for label, total in sorted(totals.items(), key=lambda item: (item[1], item[0]))
    ]


def movements_tab_name(layout_tab: str) -> str:
    """The movements tab a layout tab belongs to.

    ``layout_tab_name`` composes ``<YYYY-MM> Gastos`` and ``banking.daily``
    composes ``<YYYY-MM>``; the pairing is suffix-based, so an already-plain
    tab name falls back to itself.
    """
    if layout_tab.endswith(_LAYOUT_TAB_SUFFIX):
        return layout_tab[: -len(_LAYOUT_TAB_SUFFIX)]
    return layout_tab


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
    movements_tab_name: str,
) -> list[list[CellValue]]:
    """Return the whole layout grid, row 0 being sheet row 1 and column 0 column A.

    ``movements_tab_name`` is the raw tab the income formula reads its Importe
    column from.

    Formulas are plain strings starting with ``=``, exactly as Google Sheets
    expects them; the writer is what asks Sheets to interpret them.

    Raises:
        ValueError: when the month has more than ``MAX_CATEGORY_ROWS``
            distinct category totals. The block is never truncated silently.
    """
    totals = expense_category_totals(transactions)
    if len(totals) > MAX_CATEGORY_ROWS:
        raise ValueError(
            f"The category sums block holds at most {MAX_CATEGORY_ROWS} categories per month, "
            f"got {len(totals)}. Narrow the month or raise the ceiling."
        )

    cells: dict[int, list[CellValue]] = {}

    def place(row: int, column: int, value: CellValue) -> None:
        line = cells.setdefault(row, [])
        while len(line) <= column:
            line.append(None)
        line[column] = value

    _place_titles_and_headers(place)
    _place_category_totals(place, totals)
    _place_shared_expenses(place)
    _place_summary(place, movements_tab_name)
    _place_balances(place, balances)

    return _materialize(cells, max(max(cells), _CATEGORY_TOTAL_ROW))


def _place_titles_and_headers(place: Place) -> None:
    # Titles: only the first cell of each merged range is filled.
    place(_TITLE_ROW, _COL_B, "GASTOS")
    place(_TITLE_ROW, _COL_G, "GASTOS COMUNES")
    place(_TITLE_ROW, _COL_J, "INGRESOS")

    for column, header in (
        (_COL_B, _CATEGORY_HEADER),
        (_COL_C, _TOTAL_HEADER),
        (_COL_G, "CATEGORÍA"),
        (_COL_H, "TOTAL"),
        (_COL_J, "CONCEPTO"),
        (_COL_K, "IMPORTE"),
    ):
        place(_HEADER_ROW, column, header)


def _place_category_totals(place: Place, totals: Sequence[CategoryTotal]) -> None:
    """One row per category: label in B, signed total in C, most negative first."""
    for offset, total in enumerate(totals):
        place(_CATEGORY_SUM_FIRST_ROW + offset, _COL_B, total.category)
        place(_CATEGORY_SUM_FIRST_ROW + offset, _COL_C, float(total.total))


def _place_shared_expenses(place: Place) -> None:
    """Catalogue labels, hand-typed totals left empty, then the total row."""
    for offset, category in enumerate(CATEGORIES):
        place(_CATEGORY_FIRST_ROW + offset, _COL_G, category)
    place(_CATEGORY_TOTAL_ROW, _COL_G, "Total")
    place(_CATEGORY_TOTAL_ROW, _COL_H, _SHARED_TOTAL_FORMULA)


def _place_summary(place: Place, movements_tab_name: str) -> None:
    """Formulas over the sums block and the movements tab; signed amounts kept.

    Every sums-block row is a negative total, so ``Gastos`` is a plain ``SUM``
    over the block; ``Ingresos`` reads the movements tab's Importe column.
    """
    place(_SUMMARY_FIRST_ROW, _COL_J, "Ingresos")
    place(_SUMMARY_FIRST_ROW, _COL_K, _income_formula(movements_tab_name))
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


def _write_category_region(worksheet: gspread.Worksheet, totals: Sequence[CategoryTotal]) -> None:
    """Clear and rewrite the sums block, headers included, from B3.

    The clear reaches the legacy ``B3:E403`` region — the old four-column
    expense headers and rows — so pre-T4 tabs are cleaned instead of keeping
    ghost movements next to the new block. The write (headers plus one row per
    category) is always RAW, on the creation path too: categories and totals
    are data, never formulas, and the block must end up in the same cell form
    whether this is the first run or the tenth.
    """
    values: list[list[CellValue]] = [[_CATEGORY_HEADER, _TOTAL_HEADER]]
    values.extend([total.category, float(total.total)] for total in totals)
    try:
        worksheet.batch_clear([_LEGACY_EXPENSE_REGION])
        worksheet.update(values=values, range_name=f"B{_HEADER_ROW}")
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _write_summary_region(
    worksheet: gspread.Worksheet,
    balances: Sequence[AccountBalance],
    movements_tab_name: str,
) -> None:
    """Clear and rewrite only J:K, from the summary down to the reference date.

    The same placement helpers as ``build_month_grid`` fill the region, so the
    creation path and the daily refresh cannot drift apart. Columns A-I are
    never addressed, which is what keeps ``G:H`` (hand-typed shared amounts)
    and ``B:C`` (category sums) intact.

    The write is USER_ENTERED because the summary cells are formulas and must
    evaluate. The clear always reaches ``_SUMMARY_PANEL_LAST_ROW`` even when the
    panel is shorter, so a dropped account leaves no stale row behind.
    """
    first_row = _SUMMARY_FIRST_ROW
    last_row = _summary_panel_range_last_row(len(balances))

    cells: dict[int, list[CellValue]] = {}

    def place(row: int, column: int, value: CellValue) -> None:
        line = cells.setdefault(row, [])
        while len(line) <= column:
            line.append(None)
        line[column] = value

    _place_summary(place, movements_tab_name)
    _place_balances(place, balances)

    grid: list[list[CellValue]] = []
    for row in range(first_row, last_row + 1):
        line = cells.get(row, [])
        grid.append([line[column] if column < len(line) else None for column in (_COL_J, _COL_K)])

    try:
        worksheet.batch_clear([f"J{first_row}:K{last_row}"])
        worksheet.update(values=grid, range_name=f"J{first_row}", raw=False)
        worksheet.format(f"K{first_row}:K{last_row}", _MONEY_FORMAT)
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


def _merge_titles(worksheet: gspread.Worksheet) -> None:
    """Merge the three title ranges the layout contract declares.

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

    The ``K`` range is the whole summary/balances panel, the same one
    ``_write_summary_region`` formats on every later run, so the summary totals
    look like money from the first run on.
    """
    try:
        worksheet.format(f"B{_TITLE_ROW}:K{_TITLE_ROW}", _BOLD)
        worksheet.format(f"B{_HEADER_ROW}:K{_HEADER_ROW}", _BOLD)
        worksheet.format(
            f"C{_CATEGORY_SUM_FIRST_ROW}:C{_CATEGORY_SUM_LAST_ROW}",
            _MONEY_FORMAT,
        )
        worksheet.format(
            f"H{_CATEGORY_FIRST_ROW}:H{_CATEGORY_TOTAL_ROW}",
            _MONEY_FORMAT,
        )
        worksheet.format(
            f"K{_SUMMARY_FIRST_ROW}:K{_summary_panel_range_last_row(balance_count)}",
            _MONEY_FORMAT,
        )
    except gspread.exceptions.APIError as exc:
        raise _translate_api_error(exc) from exc


class LayoutWriter:
    """Owns the ``<YYYY-MM> Gastos`` tab.

    The tab is created once with the full grid. Every later run clears and
    rewrites the sums block (after clearing the legacy ``B3:E403`` region, so
    pre-T4 tabs are cleaned) and the ``J:K`` summary/balances panel (so the
    balances stay a fresh snapshot with the bank's reference date), and nothing
    else. The shared-expense block ``G:H`` is therefore never touched again,
    which is what keeps hand-typed amounts safe (FR-009).
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
        """Create the layout tab, or rewrite its sums block if it exists.

        The movements tab name (the raw tab the income formula reads) is
        derived from ``tab_name`` itself, so callers never pass it twice.

        Raises:
            ValueError: more category totals than the block holds; raised
                before the document is touched.
            SheetsConfigError: invalid/missing service account credentials.
            SheetsAccessError: document or tab inaccessible.
            SheetsQuotaExceededError: Google Sheets API quota exceeded.
            SheetsAPIError: any other unexpected API error.
        """
        start = time.monotonic()
        movements_tab = movements_tab_name(tab_name)
        # Pure and validating: a too-large month fails before any API call.
        grid = build_month_grid(transactions, balances, movements_tab)
        totals = expense_category_totals(transactions)

        try:
            client = self._client or _build_client()
            spreadsheet = _open_spreadsheet(client, document_id)
            worksheet, created = _resolve_layout_worksheet(
                spreadsheet, tab_name, rows=max(len(grid), _CATEGORY_SUM_LAST_ROW)
            )
            if created:
                _write_grid(worksheet, grid)
                # USER_ENTERED above evaluates every formula in the grid; rewrite
                # the sums block RAW so both paths leave B3:C in the same form.
                _write_category_region(worksheet, totals)
                _merge_titles(worksheet)
                _apply_light_formatting(worksheet, balance_count=len(balances))
            else:
                _write_category_region(worksheet, totals)
                _write_summary_region(worksheet, balances, movements_tab)
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
