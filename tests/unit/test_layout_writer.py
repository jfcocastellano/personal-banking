"""Tests for banking.sheets.layout.LayoutWriter — fake worksheet/client only.

The fake worksheet is a guard as much as a recorder: on an existing tab it
refuses any write or clear outside ``B4:E403`` and refuses a second full-sheet
write, which is exactly the property that protects hand-typed shared amounts
(spec FR-009).
"""

import logging
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


class FakeWorksheet:
    """Records gspread calls and enforces the region contract."""

    def __init__(self, title: str) -> None:
        self.title = title
        self.cells: dict[tuple[int, int], Any] = {}
        self.full_updates: list[list[list[Any]]] = []
        self.region_updates: list[list[list[Any]]] = []
        self.region_raw_flags: list[bool] = []
        self.cleared: list[str] = []
        self.formats: list[tuple[str, dict[str, Any]]] = []
        self.merged: list[str] = []
        self.raw_flags: list[bool] = []
        self._full_update_used = False
        self.update_error: Exception | None = None

    def _store(self, start_row: int, start_col: int, rows: list[list[Any]]) -> None:
        for row_offset, row in enumerate(rows):
            for col_offset, value in enumerate(row):
                self.cells[(start_row + row_offset, start_col + col_offset)] = value

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

        if not range_name.startswith("B4"):
            raise AssertionError(f"write outside the expense region: {range_name!r}")
        if len(rows) > 400 or any(len(row) > 4 for row in rows):
            raise AssertionError(f"write escapes B4:E403: {range_name!r} {len(rows)} rows")
        self.region_updates.append(rows)
        self.region_raw_flags.append(raw)
        self._store(4, 2, rows)

    def batch_clear(self, ranges: Any) -> None:
        for range_name in ranges:
            if range_name != EXPENSE_REGION:
                raise AssertionError(f"clear outside the expense region: {range_name!r}")
            self.cleared.append(range_name)
            for cell in [key for key in self.cells if 2 <= key[1] <= 5 and 4 <= key[0] <= 403]:
                del self.cells[cell]

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
    assert ("B2:K2", BOLD) in sheet.formats
    assert ("B3:K3", BOLD) in sheet.formats
    assert ("E4:E403", MONEY_FORMAT) in sheet.formats
    assert ("H4:H53", MONEY_FORMAT) in sheet.formats
    formatted_ranges = [name for name, _format in sheet.formats]
    assert any(name.startswith("K10:K") for name in formatted_ranges)
    assert all(
        fmt == MONEY_FORMAT
        for name, fmt in sheet.formats
        if name.startswith("K") and name != "K4:K6"
    )
    # Only formatting ranges are used, never a whole-sheet clear/format.
    assert "A1:K403" not in formatted_ranges


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
    """A merge is structural: the update path touches nothing outside B4:E403."""
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense(day=1)], [_balance()])
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    creation_merges = list(sheet.merged)

    writer.write("doc-1", "2026-08 Gastos", [_expense(day=2)], [_balance()])

    assert creation_merges == ["B2:E2", "G2:H2", "J2:K2"]
    assert sheet.merged == creation_merges
    assert sheet.cleared == [EXPENSE_REGION, EXPENSE_REGION]


def test_second_run_clears_only_the_expense_region_and_writes_only_expense_rows() -> None:
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
    assert sheet.cleared == [EXPENSE_REGION, EXPENSE_REGION]
    assert len(sheet.region_updates) == 2
    region_rows = sheet.region_updates[-1]
    assert region_rows[0] == ["2026-08-02", "ING España", "Compra", -10.0]
    assert region_rows[1] == ["2026-08-03", "ING España", "Compra", -10.0]
    assert sheet.cells[(4, 2)] == "2026-08-02"
    assert sheet.cells[(5, 2)] == "2026-08-03"

    # Everything outside B4:E403 keeps its value.
    assert sheet.cells[(2, 2)] == "GASTOS"
    assert sheet.cells[(3, 2)] == "FECHA"
    assert sheet.cells[(4, 7)] == "Alimentación"
    assert sheet.cells[(53, 8)] == "=SUM(H4:H52)"
    assert sheet.cells[(4, 10)] == "Ingresos"
    assert sheet.cells[(6, 11)] == "=K4+K5"
    assert sheet.cells[(BALANCE_TITLE_ROW, 10)] == "SALDO CUENTAS"
    assert len(sheet.formats) == 5  # formatting happens on creation only


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
    assert sheet.raw_flags == [False, True, True]  # the full grid is USER_ENTERED


def test_hand_typed_shared_amount_survives_a_second_run() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense()], [])
    sheet = spreadsheet.sheets["2026-08 Gastos"]
    sheet.cells[(20, 7)] = "Mercadona"  # user-corrected category label
    sheet.cells[(20, 8)] = 42.5  # hand-typed shared amount
    sheet.cells[(5, 11)] = 1234.0  # hand-typed income cell

    writer.write("doc-1", "2026-08 Gastos", [_expense(day=9)], [])

    assert sheet.cells[(20, 7)] == "Mercadona"
    assert sheet.cells[(20, 8)] == 42.5
    assert sheet.cells[(5, 11)] == 1234.0
    assert sheet.cells[(4, 2)] == "2026-08-09"


def test_second_run_drops_stale_expense_rows_and_handles_an_empty_month() -> None:
    spreadsheet = FakeSpreadsheet()
    writer, _client = _writer(spreadsheet)
    writer.write("doc-1", "2026-08 Gastos", [_expense(day=1), _expense(day=2)], [])
    sheet = spreadsheet.sheets["2026-08 Gastos"]

    writer.write("doc-1", "2026-08 Gastos", [], [])

    assert sheet.cleared == [EXPENSE_REGION, EXPENSE_REGION]
    # No region write on the empty run; only the creation-time one is recorded.
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
