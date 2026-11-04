"""Tests for banking.sheets.layout.LayoutWriter — fake worksheet/client only.

The fake worksheet is a guard as much as a recorder: on an existing tab it
refuses any write or clear outside the expense block ``B4:E403`` and the
summary/balances panel ``J4:K19``, and it refuses a second full-sheet write.
Those are exactly the properties that protect hand-typed shared amounts in
``G:H`` (spec FR-009) while letting the panel refresh (FR-004).
"""

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Any, cast
from unittest.mock import Mock

import gspread
import pytest

from banking.sheets.layout import AccountBalance, ExpenseRow, LayoutWriter
from banking.sheets.writer import SheetsAccessError, SheetsQuotaExceededError

EXPENSE_REGION = "B4:E403"
MONEY_FORMAT = {"numberFormat": {"type": "NUMBER", "pattern": '#,##0.00 "€"'}}
BOLD = {"textFormat": {"bold": True}}
BALANCE_TITLE_ROW = 8
BALANCE_FIRST_ROW = 10
SUMMARY_FIRST_ROW = 4
# Fixed floor the update path clears: four connectors today, eight slots in the
# panel, so a panel that shrank never leaves a stale row behind.
SUMMARY_LAST_ROW = 19
SUMMARY_CLEAR = f"J{SUMMARY_FIRST_ROW}:K{SUMMARY_LAST_ROW}"
SUMMARY_WRITE = f"J{SUMMARY_FIRST_ROW}"
INCOME_FORMULA = '=SUMIF($E$4:$E$403,">0",$E$4:$E$403)'
SPEND_FORMULA = '=SUMIF($E$4:$E$403,"<0",$E$4:$E$403)'


class FakeWorksheet:
    """Records gspread calls and enforces the region contract."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.cells: dict[tuple[int, int], Any] = {}
        self.full_updates: list[list[list[Any]]] = []
        self.region_updates: list[list[list[Any]]] = []
        self.region_ranges: list[str] = []
        self.region_raw_flags: list[bool] = []
        self.panel_updates: list[list[list[Any]]] = []
        self.panel_ranges: list[str] = []
        self.panel_raw_flags: list[bool] = []
        self.cleared: list[str] = []
        self.formats: list[tuple[str, dict[str, Any]]] = []
        self.merged: list[str] = []
        self.raw_flags: list[bool] = []
        self._full_update_used = False
        self.update_error: Exception | None = None

    def _store(self, start_row: int, start_col: int, rows: list[list[Any]]) -> None:
        for row_offset, row in enumerate(rows):
            for col_offset, value in enumerate(row):
                key = (start_row + row_offset, start_col + col_offset)
                if value is None:
                    # A blank cell is an absent cell, exactly like the real sheet.
                    self.cells.pop(key, None)
                else:
                    self.cells[key] = value

    def _delete(self, first_row: int, last_row: int, first_col: int, last_col: int) -> None:
        for cell in [
            key
            for key in self.cells
            if first_col <= key[1] <= last_col and first_row <= key[0] <= last_row
        ]:
            del self.cells[cell]

    def update(
        self,
        values: Any,
        range_name: str | None = None,
        raw: bool = True,
        **kwargs: Any,
    ) -> None:
        if self.update_error is not None:
            raise self.update_error
        rows = [list(row) for row in values]
        self.raw_flags.append(raw)
        if range_name in (None, "A1"):
            if self._full_update_used:
                raise AssertionError("a second full-sheet update would wipe hand edits")
            self._full_update_used = True
            self.full_updates.append(rows)
            self._store(1, 1, rows)
            return

        if range_name == SUMMARY_WRITE:
            if any(len(row) != 2 for row in rows):
                raise AssertionError(
                    f"summary write must be exactly columns J and K: {range_name!r}"
                )
            self.panel_updates.append(rows)
            self.panel_ranges.append(range_name)
            self.panel_raw_flags.append(raw)
            self._store(SUMMARY_FIRST_ROW, 10, rows)
            return

        if not range_name.startswith("B4"):
            raise AssertionError(f"write outside the writable regions: {range_name!r}")
        if len(rows) > 400 or any(len(row) > 4 for row in rows):
            raise AssertionError(f"write escapes B4:E403: {range_name!r} {len(rows)} rows")
        self.region_updates.append(rows)
        self.region_ranges.append(range_name)
        self.region_raw_flags.append(raw)
        self._store(4, 2, rows)

    def batch_clear(self, ranges: Any) -> None:
        names = ranges if isinstance(ranges, list) else [str(ranges)]
        for range_name in names:
            if range_name == EXPENSE_REGION:
                self.cleared.append(range_name)
                self._delete(4, 403, 2, 5)
                continue
            panel = re.fullmatch(r"J(\d+):K(\d+)", range_name)
            if panel is None:
                raise AssertionError(f"clear outside the writable regions: {range_name!r}")
            first_row, last_row = int(panel.group(1)), int(panel.group(2))
            if first_row != SUMMARY_FIRST_ROW:
                raise AssertionError(f"summary clear must start at J4: {range_name!r}")
            self.cleared.append(range_name)
            self._delete(first_row, last_row, 10, 11)

    def clear(self) -> None:
        raise AssertionError("clear() would wipe the whole tab, including hand edits")

    def format(self, ranges: Any, format: dict[str, Any]) -> None:
        names = ranges if isinstance(ranges, list) else [str(ranges)]
        for name in names:
            self.formats.append((name, format))

    def merge_cells(self, ranges: Any, merge_type: Any = None) -> None:
        if not self._full_update_used:
            raise AssertionError("merging before the grid write could drop the title text")
        names = ranges if isinstance(ranges, list) else [str(ranges)]
        for name in names:
            self.merged.append(name)


class FakeSpreadsheet:
    def __init__(self) -> None:
        self.sheets: dict[str, FakeWorksheet] = {}
        self.added: list[tuple[str, int, int]] = []

    def worksheet(self, title: str) -> FakeWorksheet:
        try:
            return self.sheets[title]
        except KeyError:
            raise gspread.exceptions.WorksheetNotFound

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWorksheet:
        sheet = FakeWorksheet(title)
        self.sheets[title] = sheet
        self.added.append((title, rows, cols))
        return sheet


class FakeClient:
    def __init__(self, spreadsheet: FakeSpreadsheet | None = None) -> None:
        self._spreadsheet = spreadsheet
        self.opened: list[str] = []

    def open_by_key(self, document_id: str) -> FakeSpreadsheet:
        self.opened.append(document_id)
        if self._spreadsheet is None:
            raise gspread.exceptions.SpreadsheetNotFound
        return self._spreadsheet


def _writer(spreadsheet: FakeSpreadsheet | None) -> tuple[LayoutWriter, FakeClient]:
    client = FakeClient(spreadsheet)
    return LayoutWriter(client=cast(gspread.Client, client)), client


def _expense(day: int = 1, bank: str = "ING España", description: str = "Compra") -> ExpenseRow:
    return ExpenseRow(
        booking_date=date(2026, 8, day),
        bank=bank,
        description=description,
        amount=Decimal("-10.00"),
    )


def _api_error(status_code: int) -> gspread.exceptions.APIError:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = {
        "error": {"code": status_code, "message": "boom", "status": "ERROR"}
    }
    return gspread.exceptions.APIError(response)


def _balance(bank: str = "ING España", amount: str | None = "1234.50") -> AccountBalance:
    return AccountBalance(
        bank=bank,
        amount=None if amount is None else Decimal(amount),
        reference_date=date(2026, 8, 31),
    )


# --- creation path ----------------------------------------------------------


def test_creation_writes_every_block_and_applies_formatting() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, client = _writer(spreadsheet)
    balances = [_balance(), _balance(bank="Revolut", amount="99.99")]

    writer.write("doc-1", "2026-08 Gastos", [_expense()], balances)

    assert client.opened == ["doc-1"]
    title, rows, cols = spreadsheet.added[0]
    assert title == "2026-08 Gastos"
    assert rows >= 403  # the expense block must fit
    assert cols >= 11  # A..K

    sheet = spreadsheet.sheets["2026-08 Gastos"]
    assert len(sheet.full_updates) == 1
    # The expense block is rewritten RAW right after the full USER_ENTERED grid.
    assert sheet.region_updates == [[["2026-08-01", "ING España", "Compra", -10.0]]]
    assert sheet.cleared == [EXPENSE_REGION]
    assert sheet.raw_flags == [False, True]  # grid interpreted, expenses verbatim

    assert sheet.cells[(2, 2)] == "GASTOS"
    assert sheet.cells[(2, 7)] == "GASTOS COMUNES"
    assert sheet.cells[(2, 10)] == "INGRESOS"
    assert sheet.cells[(3, 2)] == "FECHA"
    assert sheet.cells[(3, 4)] == "DESCRIPCIÓN"
    assert sheet.cells[(3, 8)] == "TOTAL"
    assert sheet.cells[(3, 11)] == "IMPORTE"

    assert sheet.cells[(4, 2)] == "2026-08-01"
    assert sheet.cells[(4, 3)] == "ING España"
    assert sheet.cells[(4, 4)] == "Compra"
    assert sheet.cells[(4, 5)] == -10.0

    assert sheet.cells[(4, 7)] == "Alimentación"
    assert sheet.cells[(52, 7)] == "*Otros"
    assert sheet.cells[(53, 7)] == "Total"
    assert sheet.cells[(53, 8)] == "=SUM(H4:H52)"

    assert sheet.cells[(4, 10)] == "Ingresos"
    assert sheet.cells[(4, 11)] == '=SUMIF($E$4:$E$403,">0",$E$4:$E$403)'
    assert sheet.cells[(6, 11)] == "=K4+K5"

    assert sheet.cells[(BALANCE_TITLE_ROW, 10)] == "SALDO CUENTAS"
    assert sheet.cells[(BALANCE_FIRST_ROW, 10)] == "ING España"
    assert sheet.cells[(BALANCE_FIRST_ROW, 11)] == 1234.5
    assert sheet.cells[(BALANCE_FIRST_ROW + 1, 11)] == 99.99


def test_creation_applies_bold_titles_headers_and_money_formats() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)

    writer.write("doc-1", "2026-08 Gastos", [_expense()], [_balance()])

    sheet = spreadsheet.sheets["2026-08 Gastos"]
    # The exact creation-time ranges, in the order they are applied. The money
    # format over the panel is the one the refresh uses (J4:K19 floor), so the
    # summary totals K4:K6 look like money from the first run on.
    assert sheet.formats == [
        ("B2:K2", BOLD),
        ("B3:K3", BOLD),
        ("E4:E403", MONEY_FORMAT),
        ("H4:H53", MONEY_FORMAT),
        (f"K{SUMMARY_FIRST_ROW}:K{SUMMARY_LAST_ROW}", MONEY_FORMAT),
    ]
    formatted_ranges = [name for name, _format in sheet.formats]
    # The balances-only range creation used to format (K10:K11 here) left the
    # summary cells unformatted until a refresh; it must not come back.
    assert not any(name.startswith("K10:K") for name in formatted_ranges)
    # Only formatting ranges are used, never a whole-sheet clear/format.
    assert "A1:K403" not in formatted_ranges


def test_creation_formats_a_panel_taller_than_the_fixed_floor() -> None:
    """The creation range follows the same helper the refresh computes with."""
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    balances = [_balance(bank=f"Banco {index}") for index in range(1, 10)]

    writer.write("doc-1", "2026-08 Gastos", [_expense()], balances)

    sheet = spreadsheet.sheets["2026-08 Gastos"]
    # Nine balances put the reference date on row 20, past the fixed floor of
    # 19, so the range has to grow with the panel instead of being hardcoded.
    assert (f"K{SUMMARY_FIRST_ROW}:K{SUMMARY_LAST_ROW + 1}", MONEY_FORMAT) in sheet.formats


def test_creation_merges_the_three_title_ranges() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)

    writer.write("doc-1", "2026-08 Gastos", [_expense()], [_balance()])

    sheet = spreadsheet.sheets["2026-08 Gastos"]
    assert sheet.merged == ["B2:E2", "G2:H2", "J2:K2"]


def test_creation_with_an_empty_month_also_merges_the_titles() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)

    writer.write("doc-1", "2026-08 Gastos", [], [])

    assert spreadsheet.sheets["2026-08 Gastos"].merged == ["B2:E2", "G2:H2", "J2:K2"]


def test_creation_merges_after_the_grid_write_and_keeps_the_title_text() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)

    writer.write("doc-1", "2026-08 Gastos", [], [])

    sheet = spreadsheet.sheets["2026-08 Gastos"]
    assert sheet.merged == ["B2:E2", "G2:H2", "J2:K2"]
    assert sheet.cells[(2, 2)] == "GASTOS"
    assert sheet.cells[(2, 7)] == "GASTOS COMUNES"
    assert sheet.cells[(2, 10)] == "INGRESOS"


# --- update path ------------------------------------------------------------


def test_update_never_merges_again() -> None:
    """A merge is structural: the update path only clears the two content regions."""
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense(day=1)], [_balance()])
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    creation_merges = list(sheet.merged)

    writer.write("doc-1", "2026-08 Gastos", [_expense(day=2)], [_balance()])

    assert creation_merges == ["B2:E2", "G2:H2", "J2:K2"]
    assert sheet.merged == creation_merges
    assert sheet.cleared == [EXPENSE_REGION, EXPENSE_REGION, SUMMARY_CLEAR]


def test_second_run_clears_and_rewrites_the_expense_region_and_the_panel() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense(day=1)], [_balance()])
    sheet = spreadsheet.sheets["2026-08 Gastos"]

    writer.write(
        "doc-1",
        "2026-08 Gastos",
        [_expense(day=2), _expense(day=3)],
        [_balance()],
    )

    assert len(sheet.full_updates) == 1  # never a second full-sheet write
    assert sheet.cleared == [EXPENSE_REGION, EXPENSE_REGION, SUMMARY_CLEAR]
    assert len(sheet.region_updates) == 2
    region_rows = sheet.region_updates[-1]
    assert region_rows[0] == ["2026-08-02", "ING España", "Compra", -10.0]
    assert region_rows[1] == ["2026-08-03", "ING España", "Compra", -10.0]
    assert sheet.cells[(4, 2)] == "2026-08-02"
    assert sheet.cells[(5, 2)] == "2026-08-03"

    # The panel is refreshed on the update path too, with at least one update.
    assert sheet.panel_ranges == [SUMMARY_WRITE]

    # Everything outside B4:E403 and J:K keeps its value.
    assert sheet.cells[(2, 2)] == "GASTOS"
    assert sheet.cells[(3, 2)] == "FECHA"
    assert sheet.cells[(4, 7)] == "Alimentación"
    assert sheet.cells[(53, 8)] == "=SUM(H4:H52)"
    assert sheet.cells[(4, 10)] == "Ingresos"
    assert sheet.cells[(6, 11)] == "=K4+K5"
    assert sheet.cells[(BALANCE_TITLE_ROW, 10)] == "SALDO CUENTAS"
    # The creation-time formatting survives; the panel adds one money format.
    assert len(sheet.formats) == 6
    assert (f"K{SUMMARY_FIRST_ROW}:K{SUMMARY_LAST_ROW}", MONEY_FORMAT) in sheet.formats


def test_second_run_rewrites_the_panel_with_user_entered_so_formulas_evaluate() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense()], [_balance()])
    sheet = spreadsheet.sheets["2026-08 Gastos"]

    writer.write("doc-1", "2026-08 Gastos", [_expense(day=2)], [_balance()])

    assert sheet.panel_ranges == [SUMMARY_WRITE]
    assert sheet.panel_raw_flags == [False]
    rows = sheet.panel_updates[-1]
    # One row per sheet row from J4 to the fixed panel floor, two columns wide.
    assert len(rows) == SUMMARY_LAST_ROW - SUMMARY_FIRST_ROW + 1
    assert all(len(row) == 2 for row in rows)
    assert rows[0] == ["Ingresos", INCOME_FORMULA]
    assert rows[1] == ["Gastos", SPEND_FORMULA]
    assert rows[2] == ["Total", "=K4+K5"]
    assert rows[BALANCE_TITLE_ROW - SUMMARY_FIRST_ROW] == ["SALDO CUENTAS", None]
    assert rows[BALANCE_FIRST_ROW - SUMMARY_FIRST_ROW] == ["ING España", 1234.5]
    assert rows[BALANCE_FIRST_ROW - SUMMARY_FIRST_ROW + 1] == ["Total", "=SUM(K10:K10)"]
    assert rows[BALANCE_FIRST_ROW - SUMMARY_FIRST_ROW + 2] == ["Saldos al", "2026-08-31"]
    assert rows[-1] == [None, None]


def test_second_run_with_different_balances_changes_the_panel_values() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense()], [_balance()])
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    assert sheet.cells[(BALANCE_FIRST_ROW, 11)] == 1234.5

    writer.write(
        "doc-1",
        "2026-08 Gastos",
        [_expense(day=2)],
        [_balance(amount="77.25"), _balance(bank="Revolut", amount="5.00")],
    )

    assert sheet.cells[(BALANCE_FIRST_ROW, 10)] == "ING España"
    assert sheet.cells[(BALANCE_FIRST_ROW, 11)] == 77.25
    assert sheet.cells[(BALANCE_FIRST_ROW + 1, 10)] == "Revolut"
    assert sheet.cells[(BALANCE_FIRST_ROW + 1, 11)] == 5.0
    assert sheet.cells[(BALANCE_FIRST_ROW + 2, 11)] == "=SUM(K10:K11)"


def test_panel_that_shrank_clears_the_rows_of_dropped_accounts() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    full_panel = [_balance(bank=f"Banco {index}", amount=f"{index}0.00") for index in range(1, 9)]
    writer.write("doc-1", "2026-08 Gastos", [_expense()], full_panel)
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    old_last_balance_row = BALANCE_FIRST_ROW + len(full_panel) - 1
    old_last_panel_row = old_last_balance_row + 2  # total, then reference date
    assert old_last_panel_row == SUMMARY_LAST_ROW  # the panel filled the floor
    assert sheet.cells[(old_last_balance_row, 10)] == "Banco 8"

    writer.write(
        "doc-1",
        "2026-08 Gastos",
        [_expense(day=2)],
        [_balance(bank="ING España", amount="11.00"), _balance(bank="Revolut", amount="21.00")],
    )

    # The clear range still covers every row the previous panel occupied.
    assert sheet.cleared[-1] == SUMMARY_CLEAR
    panel_clear = re.fullmatch(r"J4:K(\d+)", sheet.cleared[-1])
    assert panel_clear is not None
    assert int(panel_clear.group(1)) >= old_last_panel_row
    # Every dropped account is gone, not just the last one.
    assert all(
        not (isinstance(value, str) and value.startswith("Banco "))
        for value in sheet.cells.values()
    )
    # The new panel ends at its own reference date; the rest is blank.
    new_reference_row = BALANCE_FIRST_ROW + 2 + 1
    assert sheet.cells[(new_reference_row, 10)] == "Saldos al"
    assert all(
        (row, column) not in sheet.cells
        for row in range(new_reference_row + 1, SUMMARY_LAST_ROW + 1)
        for column in (10, 11)
    )
    assert sheet.cells[(BALANCE_FIRST_ROW, 10)] == "ING España"
    assert sheet.cells[(BALANCE_FIRST_ROW, 11)] == 11.0
    assert sheet.cells[(BALANCE_FIRST_ROW + 1, 10)] == "Revolut"
    assert sheet.cells[(BALANCE_FIRST_ROW + 2, 10)] == "Total"


def test_empty_month_still_refreshes_the_panel() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense()], [_balance()])
    sheet = spreadsheet.sheets["2026-08 Gastos"]

    writer.write("doc-1", "2026-08 Gastos", [], [_balance(bank="Revolut", amount="9.99")])

    assert sheet.panel_ranges == [SUMMARY_WRITE]
    assert sheet.cells[(BALANCE_FIRST_ROW, 10)] == "Revolut"
    assert sheet.cells[(BALANCE_FIRST_ROW, 11)] == 9.99
    assert sheet.cells.get((4, 2)) is None  # the expense block really is empty


def test_expense_region_is_written_the_same_way_on_creation_and_update() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    transactions = [_expense(day=1), _expense(day=2)]

    writer.write("doc-1", "2026-08 Gastos", transactions, [_balance()])
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    creation_rows = sheet.region_updates[-1]

    writer.write("doc-1", "2026-08 Gastos", transactions, [_balance()])

    # Same input option (RAW) and same values on both paths, so a month never
    # changes cell type between the first run and a later one.
    assert sheet.region_raw_flags == [True, True]
    assert sheet.region_updates[1] == creation_rows
    assert sheet.cells[(4, 2)] == "2026-08-01"
    assert sheet.raw_flags == [False, True, True, False]  # grid, expenses, panel
    assert sheet.panel_raw_flags == [False]


def test_hand_typed_shared_amount_survives_a_second_run() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense()], [])
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    sheet.cells[(20, 7)] = "Mercadona"  # user-corrected category label
    sheet.cells[(20, 8)] = 42.5  # hand-typed shared amount

    writer.write("doc-1", "2026-08 Gastos", [_expense(day=9)], [_balance()])

    assert sheet.cells[(20, 7)] == "Mercadona"
    assert sheet.cells[(20, 8)] == 42.5
    assert sheet.cells[(53, 7)] == "Total"
    assert sheet.cells[(53, 8)] == "=SUM(H4:H52)"
    assert sheet.cells[(4, 2)] == "2026-08-09"
    # No clear or write recorded on the second run mentions the manual block.
    touched = {
        match.group(1)
        for name in [*sheet.cleared, *sheet.region_ranges, *sheet.panel_ranges]
        for match in re.finditer(r"([A-Z]+)\d", name)
    }
    assert "G" not in touched
    assert "H" not in touched


def test_hand_typed_cell_inside_the_panel_is_replaced_by_the_refresh() -> None:
    """J:K belongs to the sheet: a hand edit there is not preserved (FR-004)."""
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense()], [])
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    sheet.cells[(5, 10)] = "Gastos corregido a mano"

    writer.write("doc-1", "2026-08 Gastos", [_expense(day=9)], [_balance()])

    assert sheet.cells[(5, 10)] == "Gastos"


def test_second_run_drops_stale_expense_rows_and_handles_an_empty_month() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense(day=1), _expense(day=2)], [])
    sheet = spreadsheet.sheets["2026-08 Gastos"]

    writer.write("doc-1", "2026-08 Gastos", [], [])

    assert sheet.cleared == [EXPENSE_REGION, EXPENSE_REGION, SUMMARY_CLEAR]
    # No expense write on the empty run; only the creation-time one is recorded.
    assert len(sheet.region_updates) == 1
    assert (4, 2) not in sheet.cells
    assert (5, 2) not in sheet.cells
    assert sheet.cells[(4, 7)] == "Alimentación"


def test_creation_with_an_empty_month_writes_the_skeleton() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)

    writer.write("doc-1", "2026-08 Gastos", [], [])

    sheet = spreadsheet.sheets["2026-08 Gastos"]
    assert sheet.cells[(2, 2)] == "GASTOS"
    assert sheet.cells[(3, 2)] == "FECHA"
    assert sheet.cells[(4, 7)] == "Alimentación"
    assert sheet.cells[(53, 8)] == "=SUM(H4:H52)"
    assert sheet.cells.get((4, 2)) is None


def test_boundary_month_fills_the_region_exactly() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [], [])
    sheet = spreadsheet.sheets["2026-08 Gastos"]

    writer.write("doc-1", "2026-08 Gastos", [_expense() for _ in range(400)], [])

    assert len(sheet.region_updates[-1]) == 400
    assert sheet.cells[(403, 2)] == "2026-08-01"


# --- failure paths ----------------------------------------------------------


def test_quota_error_on_update_is_translated_with_a_failure_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense()], [])
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    sheet.update_error = _api_error(429)

    with caplog.at_level(logging.ERROR, logger="banking.sheets.layout"):
        with pytest.raises(SheetsQuotaExceededError, match="quota"):
            writer.write("doc-1", "2026-08 Gastos", [_expense(day=2)], [])

    errors = [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "SheetsQuotaExceededError" in errors[0]


def test_unreachable_document_propagates_access_error() -> None:
    writer, client = _writer(None)

    with pytest.raises(SheetsAccessError, match="doc-1"):
        writer.write("doc-1", "2026-08 Gastos", [_expense()], [])

    assert client.opened == ["doc-1"]


def test_unreachable_document_logs_the_failure(caplog: pytest.LogCaptureFixture) -> None:
    writer, _client = _writer(None)

    with caplog.at_level(logging.ERROR, logger="banking.sheets.layout"):
        with pytest.raises(SheetsAccessError):
            writer.write("doc-1", "2026-08 Gastos", [], [])

    errors = [record.getMessage() for record in caplog.records if record.levelno == logging.ERROR]
    assert len(errors) == 1
    assert "tab=2026-08 Gastos" in errors[0]
    assert "SheetsAccessError" in errors[0]


def test_row_ceiling_aborts_before_touching_the_document() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, client = _writer(spreadsheet)

    with pytest.raises(ValueError, match="400"):
        writer.write("doc-1", "2026-08 Gastos", [_expense() for _ in range(401)], [])

    assert client.opened == []
    assert spreadsheet.added == []


def test_success_logs_tab_and_row_count(caplog: pytest.LogCaptureFixture) -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)

    with caplog.at_level(logging.INFO, logger="banking.sheets.layout"):
        writer.write("doc-1", "2026-08 Gastos", [_expense(), _expense(day=2)], [])

    infos = [record.getMessage() for record in caplog.records if record.levelno == logging.INFO]
    assert len(infos) == 1
    assert "Sheets write succeeded" in infos[0]
    assert "tab=2026-08 Gastos" in infos[0]
    assert "rows_written=2" in infos[0]
