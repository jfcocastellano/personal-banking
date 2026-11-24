"""The pure style payload: geometry follows layout.py and never writes values."""

from __future__ import annotations

from typing import Any

from banking.sheets.layout import (
    _BALANCE_FIRST_ROW,
    _BALANCE_HEADER_ROW,
    _BALANCE_TITLE_ROW,
    _INCOME_FIRST_ROW,
    _INCOME_HEADER_ROW,
    _INCOME_LAST_ROW,
    _INCOME_TITLE_ROW,
    _SUMMARY_HEADER_ROW,
    _SUMMARY_INCOME_ROW,
    _SUMMARY_PANEL_LAST_ROW,
    _SUMMARY_TITLE_ROW,
    _SUMMARY_TOTAL_ROW,
)
from banking.sheets.style import (
    AMOUNT_FORMAT,
    BLUE_HEADER,
    BLUE_TITLE,
    GREEN_HEADER,
    GREEN_TITLE,
    LIGHT_ORANGE,
    SALMON_TITLE,
    WHITE,
    format_requests,
    layout_requests,
    row_height_requests,
)

SHEET_ID = 7


def _row_spans(
    requests: list[dict[str, Any]], kind: str = "repeatCell"
) -> list[tuple[int, int, int, int]]:
    """The inclusive (first_row, last_row, first_column, last_column) of each request."""
    spans: list[tuple[int, int, int, int]] = []
    for request in requests:
        if kind in request:
            grid = request[kind]["range"]
            spans.append(
                (
                    grid["startRowIndex"] + 1,
                    grid["endRowIndex"],
                    grid["startColumnIndex"] + 1,
                    grid["endColumnIndex"],
                )
            )
    return spans


def test_the_panel_covers_the_income_summary_and_balance_bands() -> None:
    spans = _row_spans(format_requests(SHEET_ID))

    # INGRESOS: title, header and the seven hand-typed rows.
    assert (_INCOME_TITLE_ROW, _INCOME_TITLE_ROW, 10, 11) in spans
    assert (_INCOME_HEADER_ROW, _INCOME_HEADER_ROW, 10, 11) in spans
    assert (_INCOME_FIRST_ROW, _INCOME_LAST_ROW, 10, 11) in spans
    # RESUMEN MES: title, header and the three amounts plus the total.
    assert (_SUMMARY_TITLE_ROW, _SUMMARY_TITLE_ROW, 10, 11) in spans
    assert (_SUMMARY_HEADER_ROW, _SUMMARY_HEADER_ROW, 10, 11) in spans
    assert (_SUMMARY_INCOME_ROW, _SUMMARY_TOTAL_ROW, 10, 11) in spans
    # SALDO CUENTAS: title, header and the balance rows down to the floor.
    assert (_BALANCE_TITLE_ROW, _BALANCE_TITLE_ROW, 10, 11) in spans
    assert (_BALANCE_HEADER_ROW, _BALANCE_HEADER_ROW, 10, 11) in spans
    assert (_BALANCE_FIRST_ROW, _SUMMARY_PANEL_LAST_ROW, 10, 11) in spans
    assert _BALANCE_FIRST_ROW > _SUMMARY_TITLE_ROW


def test_no_request_writes_a_cell_value() -> None:
    requests = [*format_requests(SHEET_ID), *layout_requests(SHEET_ID, column_count=12)]

    for request in requests:
        repeat = request.get("repeatCell")
        if repeat is not None:
            assert "userEnteredValue" not in repeat["cell"]
            assert "userEnteredValue" not in repeat["fields"]


def _formats_at(requests: list[dict[str, Any]], row: int, column: int) -> list[dict[str, Any]]:
    """Every ``repeatCell`` format covering that cell, in application order."""
    formats: list[dict[str, Any]] = []
    for request in requests:
        repeat = request.get("repeatCell")
        if repeat is None:
            continue
        grid = repeat["range"]
        if (
            grid["startRowIndex"] + 1 <= row <= grid["endRowIndex"]
            and grid["startColumnIndex"] + 1 <= column <= grid["endColumnIndex"]
        ):
            formats.append(repeat["cell"]["userEnteredFormat"])
    return formats


def test_each_panel_block_is_a_dark_title_over_a_light_header() -> None:
    requests = format_requests(SHEET_ID)

    for title_row, header_row, title_accent, header_accent in (
        (_INCOME_TITLE_ROW, _INCOME_HEADER_ROW, GREEN_TITLE, GREEN_HEADER),
        (_SUMMARY_TITLE_ROW, _SUMMARY_HEADER_ROW, BLUE_TITLE, BLUE_HEADER),
        (_BALANCE_TITLE_ROW, _BALANCE_HEADER_ROW, SALMON_TITLE, LIGHT_ORANGE),
    ):
        title = _formats_at(requests, title_row, 10)[-1]
        header = _formats_at(requests, header_row, 11)[-1]

        assert title["backgroundColor"] == title_accent
        assert header["backgroundColor"] == header_accent
        # White letters on both bands, like the capture.
        assert title["textFormat"]["foregroundColor"] == WHITE
        assert header["textFormat"]["foregroundColor"] == WHITE


def test_the_panel_reads_from_the_left_edge_except_titles_and_amounts() -> None:
    # The owner asked for the labels ("Nomina", "Ingresos totales"...) to sit flush
    # left; the amounts keep their own repeat, centred like in his capture.
    requests = format_requests(SHEET_ID)

    for row in (
        _INCOME_FIRST_ROW,
        _INCOME_LAST_ROW,
        _SUMMARY_INCOME_ROW,
        _SUMMARY_TOTAL_ROW,
        _BALANCE_FIRST_ROW,
        _SUMMARY_PANEL_LAST_ROW,
    ):
        assert _formats_at(requests, row, 10)[-1]["horizontalAlignment"] == "LEFT"
        assert _formats_at(requests, row, 11)[-1]["horizontalAlignment"] == "CENTER"

    for row in (_INCOME_HEADER_ROW, _SUMMARY_HEADER_ROW, _BALANCE_HEADER_ROW):
        assert _formats_at(requests, row, 10)[-1]["horizontalAlignment"] == "LEFT"
        assert _formats_at(requests, row, 11)[-1]["horizontalAlignment"] == "LEFT"

    for row in (_INCOME_TITLE_ROW, _SUMMARY_TITLE_ROW, _BALANCE_TITLE_ROW):
        assert _formats_at(requests, row, 11)[-1]["horizontalAlignment"] == "CENTER"


def test_the_merged_title_bands_keep_their_dark_accent_and_white_letters() -> None:
    requests = layout_requests(SHEET_ID, column_count=12)

    for title_row, accent in (
        (_SUMMARY_TITLE_ROW, BLUE_TITLE),
        (_BALANCE_TITLE_ROW, SALMON_TITLE),
    ):
        title = _formats_at(requests, title_row, 11)[-1]

        assert title["backgroundColor"] == accent
        assert title["textFormat"]["foregroundColor"] == WHITE


def test_the_money_pattern_is_the_reference_one() -> None:
    assert AMOUNT_FORMAT == "#,##0.00 _€"


def test_layout_merges_the_summary_and_balance_titles_only() -> None:
    spans = [
        span
        for span in _row_spans(layout_requests(SHEET_ID, column_count=12), kind="mergeCells")
        if span[2:] == (10, 11)
    ]

    assert [span[:2] for span in spans] == [
        (_SUMMARY_TITLE_ROW, _SUMMARY_TITLE_ROW),
        (
            _BALANCE_TITLE_ROW,
            _BALANCE_TITLE_ROW,
        ),
    ]


def test_every_row_is_as_tall_as_the_row_the_owner_pointed_at() -> None:
    heights = [
        request["updateDimensionProperties"] for request in row_height_requests(SHEET_ID, 403)
    ]

    # One request over the whole tab: the body used to be 17 px with only the title
    # and header rows at 28, and the owner asked for every row of every table to look
    # like the 28 px one they spotted (an expense row that happened to land on a
    # header row).
    assert len(heights) == 1
    assert heights[0]["properties"]["pixelSize"] == 28
    assert heights[0]["range"]["startIndex"] == 0
    assert heights[0]["range"]["endIndex"] == 403
