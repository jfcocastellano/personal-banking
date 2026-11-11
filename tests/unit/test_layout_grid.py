"""Tests for banking.sheets.layout.build_month_grid — pure grid geometry.

Coordinates are asserted against the layout contract, not against the module's
own constants, so a drifting constant cannot silently redefine the contract.
Column A (index 0 of every row) is a spacer and stays empty.

Since T4 the expenses tab is a category-sums block: headers at B3/C3, then one
row per category with the label in B and the signed total in C. The movements
tab name feeds the cross-tab income formula, so it is an explicit argument.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from banking.connectors.enable_banking import Transaction
from banking.sheets.layout import (
    CATEGORIES,
    MAX_CATEGORY_ROWS,
    AccountBalance,
    ExpenseRow,
    build_month_grid,
    expense_category_totals,
    expense_rows_from_banks,
    movements_tab_name,
)

# Sheet coordinates from spec.md "Layout contract".
B, C, D, E, G, H, J, K = 1, 2, 3, 4, 6, 7, 9, 10
COLUMN_COUNT = 11  # A..K
TITLE_ROW = 2
HEADER_ROW = 3
FIRST_CATEGORY_ROW = 4
CATEGORY_LAST_ROW = 3 + len(CATEGORIES)  # 52
CATEGORY_TOTAL_ROW = CATEGORY_LAST_ROW + 1  # 53
SUMMARY_FIRST_ROW = 4
SUMMARY_TOTAL_ROW = 6
BALANCE_TITLE_ROW = 8

_SPEND_FORMULA = "=SUM(C4:C53)"


def _income_formula(movements_tab: str) -> str:
    amount_range = f"'{movements_tab}'!$E$4:$E$10000"
    return f'=SUMIF({amount_range},">0",{amount_range})'


def _cell(grid: list[list[object]], sheet_row: int, column: int) -> object:
    return grid[sheet_row - 1][column]


def _expense(
    day: int = 1,
    bank: str = "ING España",
    description: str = "Compra",
    amount: str = "-10.00",
    category: str = "",
) -> ExpenseRow:
    return ExpenseRow(
        booking_date=date(2026, 8, day),
        bank=bank,
        description=description,
        amount=Decimal(amount),
        category=category,
    )


def test_column_a_is_an_empty_spacer_on_every_row() -> None:
    grid = build_month_grid([_expense()], [], "2026-08")

    assert all(len(row) == COLUMN_COUNT for row in grid)
    assert all(row[0] is None for row in grid)


def test_titles_and_headers_match_the_contract() -> None:
    grid = build_month_grid([], [], "2026-08")

    assert _cell(grid, TITLE_ROW, B) == "GASTOS"
    assert _cell(grid, TITLE_ROW, G) == "GASTOS COMUNES"
    assert _cell(grid, TITLE_ROW, J) == "INGRESOS"
    # The merge itself is the writer's job: only the first cell holds the text.
    assert _cell(grid, TITLE_ROW, C) is None
    assert _cell(grid, TITLE_ROW, H) is None
    assert _cell(grid, TITLE_ROW, K) is None

    # B:C is now the category-sums block; D:E are gone from this tab.
    assert [_cell(grid, HEADER_ROW, column) for column in (B, C)] == [
        "CATEGORÍA",
        "TOTAL GASTOS",
    ]
    assert _cell(grid, HEADER_ROW, D) is None
    assert _cell(grid, HEADER_ROW, E) is None
    assert [_cell(grid, HEADER_ROW, column) for column in (G, H)] == ["CATEGORÍA", "TOTAL"]
    assert [_cell(grid, HEADER_ROW, column) for column in (J, K)] == ["CONCEPTO", "IMPORTE"]


def test_category_sums_block_groups_expenses_only_with_labels_and_signed_totals() -> None:
    transactions = [
        _expense(day=1, amount="-58.00", category="ALIMENTACIÓN"),
        _expense(day=2, amount="-5.00", category="ALIMENTACIÓN"),
        _expense(day=3, amount="-23.00", category="ROPA"),
        _expense(day=4, amount="2000.00", category="NÓMINA"),  # income: never grouped
    ]

    grid = build_month_grid(transactions, [], "2026-08")

    assert [_cell(grid, FIRST_CATEGORY_ROW, B), _cell(grid, FIRST_CATEGORY_ROW, C)] == [
        "ALIMENTACIÓN",
        -63.0,
    ]
    assert [_cell(grid, FIRST_CATEGORY_ROW + 1, B), _cell(grid, FIRST_CATEGORY_ROW + 1, C)] == [
        "ROPA",
        -23.0,
    ]
    assert _cell(grid, HEADER_ROW, E) is None  # no currency column
    # The date, bank and description columns are gone from this tab.
    assert _cell(grid, FIRST_CATEGORY_ROW, D) is None


def test_uncoded_transactions_group_under_sin_categoria() -> None:
    transactions = [
        _expense(day=1, amount="-5.00", category=""),
        _expense(day=2, amount="-4.00", category=""),
        _expense(day=3, amount="-1.00", category="ROPA"),
    ]

    grid = build_month_grid(transactions, [], "2026-08")

    assert [_cell(grid, FIRST_CATEGORY_ROW + offset, B) for offset in range(2)] == [
        "SIN CATEGORÍA",
        "ROPA",
    ]
    assert _cell(grid, FIRST_CATEGORY_ROW, C) == -9.0


def test_totals_are_ordered_most_negative_first_then_category_ascending() -> None:
    transactions = [
        _expense(day=1, amount="-10.00", category="BETA"),
        _expense(day=2, amount="-10.00", category="ALPHA"),
        _expense(day=3, amount="-100.00", category="ZETA"),
        _expense(day=4, amount="-2.00", category="OMEGA"),
    ]

    grid = build_month_grid(transactions, [], "2026-08")

    assert [_cell(grid, FIRST_CATEGORY_ROW + offset, B) for offset in range(4)] == [
        "ZETA",
        "ALPHA",
        "BETA",
        "OMEGA",
    ]
    assert [_cell(grid, FIRST_CATEGORY_ROW + offset, C) for offset in range(4)] == [
        -100.0,
        -10.0,
        -10.0,
        -2.0,
    ]


def test_expense_category_totals_is_pure_over_the_rows() -> None:
    rows = [
        _expense(amount="-10.00", category="ROPA"),
        _expense(amount="-10.00", category="ALPHA"),
        _expense(amount="-30.00", category=""),
        _expense(amount="99.00", category="NÓMINA"),
    ]

    totals = expense_category_totals(rows)
    assert [(t.category, t.total) for t in totals] == [
        ("SIN CATEGORÍA", Decimal("-30.00")),
        ("ALPHA", Decimal("-10.00")),
        ("ROPA", Decimal("-10.00")),
    ]


def test_same_input_yields_identical_output_regardless_of_input_order() -> None:
    transactions = [
        _expense(day=9, category="ROPA", amount="-200.00"),
        _expense(day=1, amount="2000.00", category="NÓMINA"),
        _expense(day=1, category="ALIMENTACIÓN", amount="-800.00"),
    ]
    balances = [AccountBalance(bank="ING España", amount=Decimal("1.00"))]

    forward = build_month_grid(transactions, balances, "2026-08")
    reversed_input = build_month_grid(list(reversed(transactions)), balances, "2026-08")

    assert forward == reversed_input
    assert build_month_grid(transactions, balances, "2026-08") == forward


def test_expense_rows_from_banks_fills_the_category_cell() -> None:
    banks = [
        SimpleNamespace(
            bank_name="ING España",
            transactions=[
                Transaction(
                    booking_date=date(2026, 8, 1),
                    amount=Decimal("-9.50"),
                    currency="EUR",
                    description="Café",
                    merchant_category_code="5411",
                ),
                Transaction(
                    booking_date=date(2026, 8, 2),
                    amount=Decimal("-1.00"),
                    currency="EUR",
                    description="Kiosco",
                    merchant_category_code="9999",
                ),
            ],
            balance=None,
        ),
        SimpleNamespace(
            bank_name="Revolut",
            transactions=[
                Transaction(
                    booking_date=date(2026, 8, 3),
                    amount=Decimal("-2.00"),
                    currency="EUR",
                    description="Taxi",
                ),
            ],
            balance=None,
        ),
    ]

    rows = expense_rows_from_banks(banks)  # type: ignore[arg-type]

    assert [row.category for row in rows] == ["ALIMENTACIÓN", "9999", ""]


def test_catalogue_is_reproduced_in_order_with_empty_manual_totals() -> None:
    grid = build_month_grid([], [], "2026-08")

    assert len(CATEGORIES) == 49
    assert [_cell(grid, 4 + offset, G) for offset in range(len(CATEGORIES))] == list(CATEGORIES)
    assert [_cell(grid, 4 + offset, H) for offset in range(len(CATEGORIES))] == [None] * len(
        CATEGORIES
    )


def test_catalogue_starts_with_the_reference_rows() -> None:
    assert CATEGORIES[:4] == ("Alimentación", "Mercadona", "Consum", "Otros")
    assert CATEGORIES[-1] == "*Otros"
    # Whitespace is trimmed, not kept from the reference worksheet.
    assert all(category == category.strip() for category in CATEGORIES)
    assert CATEGORIES.count("Día") >= 1


def test_shared_expenses_total_row_follows_the_catalogue() -> None:
    grid = build_month_grid([], [], "2026-08")

    assert _cell(grid, CATEGORY_TOTAL_ROW, G) == "Total"
    assert _cell(grid, CATEGORY_TOTAL_ROW, H) == "=SUM(H4:H52)"
    # The grid ends at the last content row; no trailing filler is written.
    assert len(grid) == CATEGORY_TOTAL_ROW


def test_summary_block_uses_the_cross_tab_sumif_and_the_sums_block() -> None:
    grid = build_month_grid([_expense()], [], "2026-08")

    assert _cell(grid, SUMMARY_FIRST_ROW, J) == "Ingresos"
    assert _cell(grid, SUMMARY_FIRST_ROW, K) == _income_formula("2026-08")
    assert _cell(grid, SUMMARY_FIRST_ROW + 1, J) == "Gastos"
    assert _cell(grid, SUMMARY_FIRST_ROW + 1, K) == _SPEND_FORMULA
    assert _cell(grid, SUMMARY_TOTAL_ROW, J) == "Total"
    assert _cell(grid, SUMMARY_TOTAL_ROW, K) == "=K4+K5"


def test_summary_is_positioned_independently_of_the_catalogue_length() -> None:
    grid = build_month_grid([], [], "2026-08")

    # The summary does not move when the catalogue grows; the panel below it does.
    assert _cell(grid, SUMMARY_FIRST_ROW, J) == "Ingresos"
    assert _cell(grid, CATEGORY_TOTAL_ROW, G) == "Total"
    assert _cell(grid, BALANCE_TITLE_ROW, J) == "SALDO CUENTAS"


def test_movements_tab_name_strips_the_gastos_suffix_and_falls_back_to_the_tab() -> None:
    assert movements_tab_name("2026-11 Gastos") == "2026-11"
    assert movements_tab_name("2026-11") == "2026-11"


def test_empty_month_still_yields_titles_headers_catalogue_and_formulas() -> None:
    grid = build_month_grid([], [], "2026-08")

    assert _cell(grid, TITLE_ROW, B) == "GASTOS"
    assert _cell(grid, HEADER_ROW, B) == "CATEGORÍA"
    assert _cell(grid, HEADER_ROW, C) == "TOTAL GASTOS"
    assert _cell(grid, 4, G) == "Alimentación"
    assert _cell(grid, CATEGORY_TOTAL_ROW, H) == "=SUM(H4:H52)"
    assert _cell(grid, SUMMARY_FIRST_ROW, K) == _income_formula("2026-08")
    assert _cell(grid, FIRST_CATEGORY_ROW, B) is None
    assert _cell(grid, FIRST_CATEGORY_ROW, C) is None


def test_row_ceiling_is_enforced_instead_of_truncating() -> None:
    assert MAX_CATEGORY_ROWS == 50

    over = [_expense(category=f"CAT {index:02d}") for index in range(MAX_CATEGORY_ROWS + 1)]

    with pytest.raises(ValueError, match="50"):
        build_month_grid(over, [], "2026-08")


def test_exactly_the_row_ceiling_is_accepted_up_to_row_53() -> None:
    transactions = [_expense(category=f"CAT {index:02d}") for index in range(MAX_CATEGORY_ROWS)]

    grid = build_month_grid(transactions, [], "2026-08")

    assert len(grid) == 53
    assert _cell(grid, 53, B) == "CAT 49"
    assert _cell(grid, 4, B) == "CAT 00"


def test_balance_rows_keep_the_supplied_order_and_end_with_total_and_reference() -> None:
    balances = [
        AccountBalance(
            bank="ING España", amount=Decimal("1234.50"), reference_date=date(2026, 8, 31)
        ),
        AccountBalance(bank="Revolut", amount=Decimal("99.99"), reference_date=date(2026, 8, 30)),
    ]

    grid = build_month_grid([], balances, "2026-08")

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

    grid = build_month_grid([], balances, "2026-08")

    assert _cell(grid, BALANCE_TITLE_ROW + 2, J) == "ING España"
    assert _cell(grid, BALANCE_TITLE_ROW + 3, J) == "Sabadell"
    assert _cell(grid, BALANCE_TITLE_ROW + 3, K) is None
    assert _cell(grid, BALANCE_TITLE_ROW + 4, J) == "Revolut"
    # The total is a range over every balance row: SUM skips the blank cell, so a
    # hand-typed balance in it would be picked up later.
    assert _cell(grid, BALANCE_TITLE_ROW + 5, K) == "=SUM(K10:K12)"


def test_all_balances_missing_leave_cells_empty_but_keep_the_total_range() -> None:
    balances = [AccountBalance(bank="Sabadell", amount=None)]

    grid = build_month_grid([], balances, "2026-08")

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

    grid = build_month_grid([], balances, "2026-08")

    reference_row = BALANCE_TITLE_ROW + 2 + len(balances) + 1
    assert _cell(grid, reference_row, J) == "Saldos al"
    assert _cell(grid, reference_row, K) == "2026-08-31"


def test_reference_date_row_without_any_date_says_so() -> None:
    balances = [
        AccountBalance(bank="ING España", amount=Decimal("1.00")),
        AccountBalance(bank="Revolut", amount=None, reference_date=None),
    ]

    grid = build_month_grid([], balances, "2026-08")

    reference_row = BALANCE_TITLE_ROW + 2 + len(balances) + 1
    assert _cell(grid, reference_row, J) == "Saldos al"
    assert _cell(grid, reference_row, K) == "sin dato de referencia"


def test_balance_panel_exists_even_without_balances() -> None:
    grid = build_month_grid([], [], "2026-08")

    assert _cell(grid, BALANCE_TITLE_ROW, J) == "SALDO CUENTAS"
    assert _cell(grid, BALANCE_TITLE_ROW + 1, J) == "CUENTA"
    assert _cell(grid, BALANCE_TITLE_ROW + 2, J) == "Total"
    assert _cell(grid, BALANCE_TITLE_ROW + 2, K) is None
    assert _cell(grid, BALANCE_TITLE_ROW + 3, J) == "Saldos al"
    assert _cell(grid, BALANCE_TITLE_ROW + 3, K) == "sin dato de referencia"


def test_every_formula_is_a_string_starting_with_equals() -> None:
    grid = build_month_grid([], [], "2026-08")

    formulas = [
        value for row in grid for value in row if isinstance(value, str) and value.startswith("=")
    ]
    assert len(formulas) == 4  # shared total, cross-tab income, sums total, net result
    assert all(isinstance(formula, str) for formula in formulas)
