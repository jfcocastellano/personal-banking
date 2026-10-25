"""Tests for banking.sheets.layout.build_month_grid — pure grid geometry.

Coordinates are asserted against the layout contract, not against the module's
own constants, so a drifting constant cannot silently redefine the contract.
Column A (index 0 of every row) is a spacer and stays empty.
"""

from datetime import date
from decimal import Decimal

import pytest

from banking.sheets.layout import (
    CATEGORIES,
    MAX_EXPENSE_ROWS,
    AccountBalance,
    ExpenseRow,
    build_month_grid,
)

# Sheet coordinates from spec.md "Layout contract".
B, C, D, E, G, H, J, K = 1, 2, 3, 4, 6, 7, 9, 10
COLUMN_COUNT = 11  # A..K
TITLE_ROW = 2
HEADER_ROW = 3
FIRST_EXPENSE_ROW = 4
CATEGORY_FIRST_ROW = 4
CATEGORY_LAST_ROW = 3 + len(CATEGORIES)  # 52
CATEGORY_TOTAL_ROW = CATEGORY_LAST_ROW + 1  # 53
SUMMARY_FIRST_ROW = 4
SUMMARY_TOTAL_ROW = 6
BALANCE_TITLE_ROW = 8


def _cell(grid: list[list[object]], sheet_row: int, column: int) -> object:
    return grid[sheet_row - 1][column]


def _expense(
    day: int = 1,
    bank: str = "ING España",
    description: str = "Compra",
    amount: str = "-10.00",
) -> ExpenseRow:
    return ExpenseRow(
        booking_date=date(2026, 8, day),
        bank=bank,
        description=description,
        amount=Decimal(amount),
    )


def test_column_a_is_an_empty_spacer_on_every_row() -> None:
    grid = build_month_grid([_expense()], [])

    assert all(len(row) == COLUMN_COUNT for row in grid)
    assert all(row[0] is None for row in grid)


def test_titles_and_headers_match_the_contract() -> None:
    grid = build_month_grid([], [])

    assert _cell(grid, TITLE_ROW, B) == "GASTOS"
    assert _cell(grid, TITLE_ROW, G) == "GASTOS COMUNES"
    assert _cell(grid, TITLE_ROW, J) == "INGRESOS"
    # The merge itself is the writer's job: only the first cell holds the text.
    assert _cell(grid, TITLE_ROW, C) is None
    assert _cell(grid, TITLE_ROW, H) is None
    assert _cell(grid, TITLE_ROW, K) is None

    assert [_cell(grid, HEADER_ROW, column) for column in (B, C, D, E)] == [
        "FECHA",
        "BANCO",
        "DESCRIPCIÓN",
        "IMPORTE",
    ]
    assert [_cell(grid, HEADER_ROW, column) for column in (G, H)] == ["CATEGORÍA", "TOTAL"]
    assert [_cell(grid, HEADER_ROW, column) for column in (J, K)] == ["CONCEPTO", "IMPORTE"]


def test_expense_rows_start_at_row_four_with_four_columns_and_no_currency() -> None:
    grid = build_month_grid([_expense(day=12, bank="Revolut", description="Café")], [])

    assert [_cell(grid, FIRST_EXPENSE_ROW, column) for column in (B, C, D, E)] == [
        "2026-08-12",
        "Revolut",
        "Café",
        -10.0,
    ]
    assert _cell(grid, FIRST_EXPENSE_ROW, E + 1) is None  # no currency column
    assert _cell(grid, HEADER_ROW, E + 1) is None


def test_transactions_are_sorted_by_date_then_bank_then_description() -> None:
    transactions = [
        _expense(day=20, bank="Sabadell", description="B"),
        _expense(day=2, bank="Revolut", description="Z"),
        _expense(day=2, bank="ING España", description="Y"),
        _expense(day=2, bank="ING España", description="A"),
    ]

    grid = build_month_grid(transactions, [])

    assert [_cell(grid, FIRST_EXPENSE_ROW + offset, C) for offset in range(4)] == [
        "ING España",
        "ING España",
        "Revolut",
        "Sabadell",
    ]
    assert [_cell(grid, FIRST_EXPENSE_ROW + offset, D) for offset in range(4)] == [
        "A",
        "Y",
        "Z",
        "B",
    ]


def test_identical_input_yields_identical_output_regardless_of_input_order() -> None:
    transactions = [
        _expense(day=9, bank="MyInvestor", description="Fondo", amount="-200.00"),
        _expense(day=1, bank="ING España", description="Nómina", amount="2000.00"),
        _expense(day=1, bank="ING España", description="Alquiler", amount="-800.00"),
    ]
    balances = [AccountBalance(bank="ING España", amount=Decimal("1.00"))]

    forward = build_month_grid(transactions, balances)
    reversed_input = build_month_grid(list(reversed(transactions)), balances)

    assert forward == reversed_input
    assert build_month_grid(transactions, balances) == forward


def test_catalogue_is_reproduced_in_order_with_empty_manual_totals() -> None:
    grid = build_month_grid([], [])

    assert len(CATEGORIES) == 49
    labels = [_cell(grid, CATEGORY_FIRST_ROW + offset, G) for offset in range(len(CATEGORIES))]
    assert labels == list(CATEGORIES)
    assert [_cell(grid, CATEGORY_FIRST_ROW + offset, H) for offset in range(len(CATEGORIES))] == [
        None
    ] * len(CATEGORIES)


def test_catalogue_starts_with_the_reference_rows() -> None:
    assert CATEGORIES[:4] == ("Alimentación", "Mercadona", "Consum", "Otros")
    assert CATEGORIES[-1] == "*Otros"
    # Whitespace is trimmed, not kept from the reference worksheet.
    assert all(category == category.strip() for category in CATEGORIES)
    assert CATEGORIES.count("Día") >= 1


def test_shared_expenses_total_row_follows_the_catalogue() -> None:
    grid = build_month_grid([], [])

    assert _cell(grid, CATEGORY_TOTAL_ROW, G) == "Total"
    assert _cell(grid, CATEGORY_TOTAL_ROW, H) == "=SUM(H4:H52)"
    # The grid ends at the last content row; no trailing filler is written.
    assert len(grid) == CATEGORY_TOTAL_ROW


def test_summary_block_uses_the_two_sumif_formulas_and_a_shared_total() -> None:
    grid = build_month_grid([_expense()], [])

    assert _cell(grid, SUMMARY_FIRST_ROW, J) == "Ingresos"
    assert _cell(grid, SUMMARY_FIRST_ROW, K) == '=SUMIF($E$4:$E$403,">0",$E$4:$E$403)'
    assert _cell(grid, SUMMARY_FIRST_ROW + 1, J) == "Gastos"
    assert _cell(grid, SUMMARY_FIRST_ROW + 1, K) == '=SUMIF($E$4:$E$403,"<0",$E$4:$E$403)'
    assert _cell(grid, SUMMARY_TOTAL_ROW, J) == "Total"
    assert _cell(grid, SUMMARY_TOTAL_ROW, K) == "=K4+K5"


def test_summary_is_positioned_independently_of_the_catalogue_length() -> None:
    grid = build_month_grid([], [])

    # The summary does not move when the catalogue grows; the panel below it does.
    assert _cell(grid, SUMMARY_FIRST_ROW, J) == "Ingresos"
    assert _cell(grid, CATEGORY_TOTAL_ROW, G) == "Total"
    assert _cell(grid, BALANCE_TITLE_ROW, J) == "SALDO CUENTAS"


def test_empty_month_still_yields_titles_headers_catalogue_and_formulas() -> None:
    grid = build_month_grid([], [])

    assert _cell(grid, TITLE_ROW, B) == "GASTOS"
    assert _cell(grid, HEADER_ROW, B) == "FECHA"
    assert _cell(grid, CATEGORY_FIRST_ROW, G) == "Alimentación"
    assert _cell(grid, CATEGORY_TOTAL_ROW, H) == "=SUM(H4:H52)"
    assert _cell(grid, SUMMARY_FIRST_ROW, K) == '=SUMIF($E$4:$E$403,">0",$E$4:$E$403)'
    assert _cell(grid, FIRST_EXPENSE_ROW, B) is None


def test_row_ceiling_is_enforced_instead_of_truncating() -> None:
    assert MAX_EXPENSE_ROWS == 400

    with pytest.raises(ValueError, match="400"):
        build_month_grid([_expense() for _ in range(MAX_EXPENSE_ROWS + 1)], [])


def test_exactly_the_row_ceiling_is_accepted_up_to_row_403() -> None:
    grid = build_month_grid([_expense(day=1) for _ in range(MAX_EXPENSE_ROWS)], [])

    assert len(grid) == 403
    assert _cell(grid, 403, B) == "2026-08-01"


def test_balance_rows_keep_the_supplied_order_and_end_with_total_and_reference() -> None:
    balances = [
        AccountBalance(
            bank="ING España", amount=Decimal("1234.50"), reference_date=date(2026, 8, 31)
        ),
        AccountBalance(bank="Revolut", amount=Decimal("99.99"), reference_date=date(2026, 8, 30)),
    ]

    grid = build_month_grid([], balances)

    assert _cell(grid, BALANCE_TITLE_ROW, J) == "SALDO CUENTAS"
    assert [_cell(grid, BALANCE_TITLE_ROW + 1, column) for column in (J, K)] == [
        "CUENTA",
        "SALDO",
    ]
    assert _cell(grid, BALANCE_TITLE_ROW + 2, J) == "ING España"
    assert _cell(grid, BALANCE_TITLE_ROW + 2, K) == 1234.5
    assert _cell(grid, BALANCE_TITLE_ROW + 3, J) == "Revolut"
    assert _cell(grid, BALANCE_TITLE_ROW + 3, K) == 99.99

    total_row = BALANCE_TITLE_ROW + 4
    assert _cell(grid, total_row, J) == "Total"
    assert _cell(grid, total_row, K) == "=SUM(K10:K11)"
    assert _cell(grid, total_row + 1, J) == "Saldos al"
    assert _cell(grid, total_row + 1, K) == "2026-08-31"
    assert len(grid) == CATEGORY_TOTAL_ROW


def test_balance_without_amount_leaves_the_cell_empty_and_out_of_the_total() -> None:
    balances = [
        AccountBalance(
            bank="ING España", amount=Decimal("10.00"), reference_date=date(2026, 8, 31)
        ),
        AccountBalance(bank="Sabadell", amount=None, reference_date=date(2026, 8, 31)),
        AccountBalance(bank="Revolut", amount=Decimal("20.00"), reference_date=date(2026, 8, 31)),
    ]

    grid = build_month_grid([], balances)

    assert _cell(grid, BALANCE_TITLE_ROW + 2, J) == "ING España"
    assert _cell(grid, BALANCE_TITLE_ROW + 3, J) == "Sabadell"
    assert _cell(grid, BALANCE_TITLE_ROW + 3, K) is None
    assert _cell(grid, BALANCE_TITLE_ROW + 4, J) == "Revolut"
    # The total is a range over every balance row: SUM skips the blank cell, so a
    # hand-typed balance in it would be picked up later.
    assert _cell(grid, BALANCE_TITLE_ROW + 5, K) == "=SUM(K10:K12)"


def test_all_balances_missing_leave_cells_empty_but_keep_the_total_range() -> None:
    balances = [AccountBalance(bank="Sabadell", amount=None)]

    grid = build_month_grid([], balances)

    total_row = BALANCE_TITLE_ROW + 2 + len(balances)
    assert _cell(grid, total_row, J) == "Total"
    assert _cell(grid, total_row, K) == "=SUM(K10:K10)"
    assert _cell(grid, BALANCE_TITLE_ROW + 2, K) is None


def test_reference_date_row_reports_the_most_recent_date() -> None:
    balances = [
        AccountBalance(bank="ING España", amount=Decimal("1.00"), reference_date=date(2026, 8, 29)),
        AccountBalance(bank="Revolut", amount=Decimal("2.00"), reference_date=date(2026, 8, 31)),
        AccountBalance(bank="Sabadell", amount=Decimal("3.00"), reference_date=None),
    ]

    grid = build_month_grid([], balances)

    reference_row = BALANCE_TITLE_ROW + 2 + len(balances) + 1
    assert _cell(grid, reference_row, J) == "Saldos al"
    assert _cell(grid, reference_row, K) == "2026-08-31"


def test_reference_date_row_without_any_date_says_so() -> None:
    balances = [
        AccountBalance(bank="ING España", amount=Decimal("1.00")),
        AccountBalance(bank="Revolut", amount=None, reference_date=None),
    ]

    grid = build_month_grid([], balances)

    reference_row = BALANCE_TITLE_ROW + 2 + len(balances) + 1
    assert _cell(grid, reference_row, J) == "Saldos al"
    assert _cell(grid, reference_row, K) == "sin dato de referencia"


def test_balance_panel_exists_even_without_balances() -> None:
    grid = build_month_grid([], [])

    assert _cell(grid, BALANCE_TITLE_ROW, J) == "SALDO CUENTAS"
    assert _cell(grid, BALANCE_TITLE_ROW + 1, J) == "CUENTA"
    assert _cell(grid, BALANCE_TITLE_ROW + 2, J) == "Total"
    assert _cell(grid, BALANCE_TITLE_ROW + 2, K) is None
    assert _cell(grid, BALANCE_TITLE_ROW + 3, J) == "Saldos al"
    assert _cell(grid, BALANCE_TITLE_ROW + 3, K) == "sin dato de referencia"


def test_every_formula_is_a_string_starting_with_equals() -> None:
    grid = build_month_grid([], [])

    formulas = [
        value for row in grid for value in row if isinstance(value, str) and value.startswith("=")
    ]
    assert len(formulas) == 4  # shared total, two SUMIF, net result
    assert all(isinstance(formula, str) for formula in formulas)
