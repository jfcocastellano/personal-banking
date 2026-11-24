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
    INCOME_LABELS,
    MAX_EXPENSE_ROWS,
    SHARED_DEEP_INDENT_POINTS,
    SHARED_INDENT_POINTS,
    SHARED_SECTION_HEADERS,
    AccountBalance,
    ExpenseRow,
    build_month_grid,
    column_widths,
    content_width_requests,
    shared_indent_requests,
    shared_sub_item_rows,
)

# Sheet coordinates from spec.md "Layout contract" and task 022's panel geometry.
B, C, D, E, G, H, J, K = 1, 2, 3, 4, 6, 7, 9, 10
COLUMN_COUNT = 11  # A..K
TITLE_ROW = 2
HEADER_ROW = 3
FIRST_EXPENSE_ROW = 4
CATEGORY_FIRST_ROW = 4
CATEGORY_LAST_ROW = 3 + len(CATEGORIES)  # 52
CATEGORY_TOTAL_ROW = CATEGORY_LAST_ROW + 1  # 53
INCOME_FIRST_ROW = 4
INCOME_LAST_ROW = 10
SUMMARY_TITLE_ROW = 12
SUMMARY_HEADER_ROW = 13
SUMMARY_INCOME_ROW = 14
SUMMARY_EXPENSE_ROW = 15
SUMMARY_SHARED_ROW = 16
SUMMARY_TOTAL_ROW = 18
BALANCE_TITLE_ROW = 20
BALANCE_HEADER_ROW = 21
BALANCE_FIRST_ROW = 22


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
    assert [_cell(grid, HEADER_ROW, column) for column in (J, K)] == ["CONCEPTO", "CANTIDAD"]


def test_income_table_lists_the_seven_concepts_with_empty_amounts() -> None:
    grid = build_month_grid([], [])

    assert INCOME_LABELS == (
        "Nómina",
        "Acciones IB",
        "Dividendos IB",
        "Opciones IB",
        "Intereses IB",
        "MyInvestor",
        "Parking",
    )
    assert [_cell(grid, INCOME_FIRST_ROW + offset, J) for offset in range(len(INCOME_LABELS))] == [
        *INCOME_LABELS
    ]
    # The owner types every amount by hand: the process never invents one.
    assert [_cell(grid, INCOME_FIRST_ROW + offset, K) for offset in range(len(INCOME_LABELS))] == [
        None
    ] * len(INCOME_LABELS)
    assert _cell(grid, INCOME_LAST_ROW + 1, J) is None  # blank row before the summary


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


def test_summary_table_sums_income_and_subtracts_both_expense_blocks() -> None:
    grid = build_month_grid([_expense()], [])

    assert _cell(grid, SUMMARY_TITLE_ROW, J) == "RESUMEN MES"
    assert [_cell(grid, SUMMARY_HEADER_ROW, column) for column in (J, K)] == [
        "CONCEPTO",
        "CANTIDAD",
    ]
    assert _cell(grid, SUMMARY_INCOME_ROW, J) == "Ingresos totales"
    assert _cell(grid, SUMMARY_INCOME_ROW, K) == "=SUM(K4:K10)"
    assert _cell(grid, SUMMARY_EXPENSE_ROW, J) == "Gastos míos"
    assert _cell(grid, SUMMARY_EXPENSE_ROW, K) == "=-SUMPRODUCT($E$4:$E$403*($E$4:$E$403<0))"
    assert _cell(grid, SUMMARY_SHARED_ROW, J) == "Gastos comunes"
    assert _cell(grid, SUMMARY_SHARED_ROW, K) == "=H53"
    assert _cell(grid, SUMMARY_SHARED_ROW + 1, J) is None  # blank row before the total
    assert _cell(grid, SUMMARY_TOTAL_ROW, J) == "Total"
    assert _cell(grid, SUMMARY_TOTAL_ROW, K) == "=K14-K15-K16"


def test_no_formula_depends_on_the_spreadsheet_locale() -> None:
    # The spreadsheet runs in ``es_ES``, where Sheets separates formula arguments with
    # ``;`` and commas are decimal marks, so a comma-separated ``SUMIF`` is stored but
    # renders ``#ERROR!``. Every formula the layout writes must avoid both separators.
    grid = build_month_grid([_expense()], [AccountBalance(bank="Revolut", amount=None)])

    formulas = [
        cell for row in grid for cell in row if isinstance(cell, str) and cell.startswith("=")
    ]

    assert formulas, "the layout is expected to write formulas"
    for formula in formulas:
        assert "," not in formula, formula
        assert ";" not in formula, formula


def test_summary_is_positioned_independently_of_the_catalogue_length() -> None:
    grid = build_month_grid([], [])

    # The summary does not move when the catalogue grows; the panel below it does.
    assert _cell(grid, SUMMARY_TITLE_ROW, J) == "RESUMEN MES"
    assert _cell(grid, CATEGORY_TOTAL_ROW, G) == "Total"
    assert _cell(grid, BALANCE_TITLE_ROW, J) == "SALDO CUENTAS"


def test_empty_month_still_yields_titles_headers_catalogue_and_formulas() -> None:
    grid = build_month_grid([], [])

    assert _cell(grid, TITLE_ROW, B) == "GASTOS"
    assert _cell(grid, HEADER_ROW, B) == "FECHA"
    assert _cell(grid, CATEGORY_FIRST_ROW, G) == "Alimentación"
    assert _cell(grid, CATEGORY_TOTAL_ROW, H) == "=SUM(H4:H52)"
    assert _cell(grid, SUMMARY_INCOME_ROW, K) == "=SUM(K4:K10)"
    assert _cell(grid, FIRST_EXPENSE_ROW, B) is None


def test_row_ceiling_is_enforced_instead_of_truncating() -> None:
    assert MAX_EXPENSE_ROWS == 400

    with pytest.raises(ValueError, match="400"):
        build_month_grid([_expense() for _ in range(MAX_EXPENSE_ROWS + 1)], [])


def test_exactly_the_row_ceiling_is_accepted_up_to_row_403() -> None:
    grid = build_month_grid([_expense(day=1) for _ in range(MAX_EXPENSE_ROWS)], [])

    assert len(grid) == 403
    assert _cell(grid, 403, B) == "2026-08-01"


def test_balance_rows_keep_the_supplied_order_and_end_with_the_total() -> None:
    balances = [
        AccountBalance(
            bank="ING España", amount=Decimal("1234.50"), reference_date=date(2026, 8, 31)
        ),
        AccountBalance(bank="Revolut", amount=Decimal("99.99"), reference_date=date(2026, 8, 30)),
    ]

    grid = build_month_grid([], balances)

    assert _cell(grid, BALANCE_TITLE_ROW, J) == "SALDO CUENTAS"
    # The second label matches the panel's, like the owner's capture.
    assert [_cell(grid, BALANCE_HEADER_ROW, column) for column in (J, K)] == [
        "CUENTA",
        "CANTIDAD",
    ]
    assert _cell(grid, BALANCE_FIRST_ROW, J) == "ING España"
    assert _cell(grid, BALANCE_FIRST_ROW, K) == 1234.5
    assert _cell(grid, BALANCE_FIRST_ROW + 1, J) == "Revolut"
    assert _cell(grid, BALANCE_FIRST_ROW + 1, K) == 99.99

    total_row = BALANCE_FIRST_ROW + 2
    assert _cell(grid, total_row, J) == "TOTAL"
    assert _cell(grid, total_row, K) == "=SUM(K22:K23)"
    assert _cell(grid, total_row + 1, J) is None
    assert _cell(grid, total_row + 1, K) is None
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

    assert _cell(grid, BALANCE_FIRST_ROW, J) == "ING España"
    assert _cell(grid, BALANCE_FIRST_ROW + 1, J) == "Sabadell"
    assert _cell(grid, BALANCE_FIRST_ROW + 1, K) is None
    assert _cell(grid, BALANCE_FIRST_ROW + 2, J) == "Revolut"
    # The total is a range over every balance row: SUM skips the blank cell, so a
    # hand-typed balance in it would be picked up later.
    assert _cell(grid, BALANCE_FIRST_ROW + 3, K) == "=SUM(K22:K24)"


def test_all_balances_missing_leave_cells_empty_but_keep_the_total_range() -> None:
    balances = [AccountBalance(bank="Sabadell", amount=None)]

    grid = build_month_grid([], balances)

    total_row = BALANCE_FIRST_ROW + len(balances)
    assert _cell(grid, total_row, J) == "TOTAL"
    assert _cell(grid, total_row, K) == "=SUM(K22:K22)"
    assert _cell(grid, BALANCE_FIRST_ROW, K) is None


def test_nothing_is_written_below_the_total_row() -> None:
    balances = [
        AccountBalance(bank="ING España", amount=Decimal("1.00"), reference_date=date(2026, 8, 29)),
        AccountBalance(bank="Revolut", amount=Decimal("2.00"), reference_date=date(2026, 8, 31)),
        AccountBalance(bank="Sabadell", amount=Decimal("3.00"), reference_date=None),
    ]

    grid = build_month_grid([], balances)

    reference_row = BALANCE_FIRST_ROW + len(balances) + 1
    assert _cell(grid, reference_row, J) is None
    assert _cell(grid, reference_row, K) is None


def test_nothing_is_written_below_the_total_row_without_dates() -> None:
    balances = [
        AccountBalance(bank="ING España", amount=Decimal("1.00")),
        AccountBalance(bank="Revolut", amount=None, reference_date=None),
    ]

    grid = build_month_grid([], balances)

    reference_row = BALANCE_FIRST_ROW + len(balances) + 1
    assert _cell(grid, reference_row, J) is None
    assert _cell(grid, reference_row, K) is None


def test_balance_panel_exists_even_without_balances() -> None:
    grid = build_month_grid([], [])

    assert _cell(grid, BALANCE_TITLE_ROW, J) == "SALDO CUENTAS"
    assert _cell(grid, BALANCE_HEADER_ROW, J) == "CUENTA"
    assert _cell(grid, BALANCE_FIRST_ROW, J) == "TOTAL"
    assert _cell(grid, BALANCE_FIRST_ROW, K) is None
    assert _cell(grid, BALANCE_FIRST_ROW + 1, J) is None
    assert _cell(grid, BALANCE_FIRST_ROW + 1, K) is None


def test_every_formula_is_a_string_starting_with_equals() -> None:
    grid = build_month_grid([], [])

    formulas = [
        value for row in grid for value in row if isinstance(value, str) and value.startswith("=")
    ]
    assert len(formulas) == 5  # shared total, income SUM, own expenses, shared cell, outcome
    assert all(isinstance(formula, str) for formula in formulas)


def test_column_widths_follow_the_widest_cell_plus_a_margin() -> None:
    rows = [
        [
            "",
            "FECHA",
            "BANCO",
            "DESCRIPCIÓN",
            "IMPORTE",
            "",
            "CATEGORÍA",
            "TOTAL",
            "",
            "CUENTA",
            "",
        ],
        [
            "",
            "2026-08-01",
            "ING España",
            "Compra",
            -10.0,
            "",
            "Alimentación",
            10.0,
            "",
            "ING España",
            1.0,
        ],
    ]

    widths = column_widths(rows)

    # Only the content columns: A, F and I are spacers between the blocks.
    assert set(widths) == {2, 3, 4, 5, 7, 8, 10, 11}
    assert all(width >= 90 for width in widths.values())
    # The amount columns keep their floors: the sample amounts are short, but a
    # real ``-1.735,98 €`` needs the room.
    assert widths[5] == 130
    assert widths[8] == 130
    # J and K too: short summary labels today, typed figures tomorrow.
    assert widths[10] == 200
    assert widths[11] == 130
    # The widest cell of each column plus the margin, rounded up to 5 px:
    # "DESCRIPCIÓN" (11), "ING España" (10), "CATEGORÍA"/"Alimentación" (12, 9).
    assert widths[4] == 115
    assert widths[3] == 110
    assert widths[7] == 125


def test_a_longer_cell_only_widens_its_own_column() -> None:
    short = column_widths([["", "FECHA", "BANCO", "Compra"]])
    long = column_widths(
        [["", "FECHA", "BANCO", "Compra de material de oficina en la tienda del centro"]]
    )

    assert long[4] > short[4]
    assert long[2] == short[2]
    assert long[3] == short[3]


def test_a_runaway_description_stops_at_the_maximum_width() -> None:
    widths = column_widths([["", "FECHA", "BANCO", "X" * 200]])

    assert widths[4] == 400


def test_a_formula_does_not_widen_its_column() -> None:
    widths = column_widths([["", "FECHA", "BANCO", "=-SUMPRODUCT($E$4:$E$403*($E$4:$E$403<0))"]])

    # The source text is not the width the cell renders at, so D stays at the floor.
    assert widths[4] == 90


def test_content_width_requests_target_the_content_columns_only() -> None:
    requests = content_width_requests(7, [["", "FECHA", "BANCO", "Compra"]])

    ranges = [
        (request["updateDimensionProperties"]["range"]["startIndex"] + 1) for request in requests
    ]
    assert ranges == [2, 3, 4, 5, 7, 8, 10, 11]


def test_the_shared_expenses_tabulate_the_lines_that_hang_from_a_header() -> None:
    rows = shared_sub_item_rows()

    labels = [CATEGORIES[row - 4] for row in rows]
    assert labels == [
        "Mercadona",
        "Consum",
        "Otros",
        "Petsitter",
        "Día",
        "Día",
        "Día",
        "Veterinario",
        "Zooplus",
        "Agua",
        "Gas",
        "Limpieza",
        "Día",
        "Día",
        "Día",
        "Día",
        "Luz",
        "Menaje",
        "HBO",
        "Spotify",
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
    ]
    # Every row is inside the block, and no section header is indented.
    assert rows == tuple(sorted(rows))
    assert all(CATEGORY_FIRST_ROW <= row <= CATEGORY_LAST_ROW for row in rows)
    assert not set(rows) & {4 + CATEGORIES.index(h) for h in SHARED_SECTION_HEADERS}


def test_every_section_header_exists_in_the_catalogue() -> None:
    assert set(SHARED_SECTION_HEADERS) <= set(CATEGORIES)


def test_the_indent_requests_touch_only_column_g() -> None:
    requests = shared_indent_requests(7)

    assert len(requests) == len(shared_sub_item_rows())
    for request, row in zip(requests, shared_sub_item_rows(), strict=True):
        repeat = request["repeatCell"]
        assert repeat["range"]["startRowIndex"] + 1 == row
        assert repeat["range"]["startColumnIndex"] == 6  # G, 0-based
        assert repeat["range"]["endColumnIndex"] == 7
        assert repeat["cell"]["userEnteredFormat"]["padding"]["left"] > 0


def test_the_dia_lines_hang_one_step_deeper_than_the_rest() -> None:
    paddings = {
        request["repeatCell"]["range"]["startRowIndex"] + 1: request["repeatCell"]["cell"][
            "userEnteredFormat"
        ]["padding"]["left"]
        for request in shared_indent_requests(7)
    }

    dia_rows = {row for row, padding in paddings.items() if padding == SHARED_DEEP_INDENT_POINTS}
    assert dia_rows == {14, 15, 16, 23, 24, 25, 26}
    assert {CATEGORIES[row - 4] for row in dia_rows} == {"Día"}
    # Everything else keeps the first step, and the two steps are distinct.
    assert set(paddings.values()) == {SHARED_INDENT_POINTS, SHARED_DEEP_INDENT_POINTS}
    assert len(paddings) - len(dia_rows) == 28
