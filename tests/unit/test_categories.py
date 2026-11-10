"""Tests for the ISO 18245 category label mapping (T4, S1)."""

from banking import categories


def test_mapped_code_returns_the_spanish_label():
    assert categories.category_cell("5411") == "ALIMENTACIÓN"
    assert categories.category_cell("5812") == "RESTAURACIÓN"
    assert categories.category_cell("5912") == "FARMACIA"


def test_unmapped_code_falls_back_to_the_raw_code():
    assert categories.category_cell("5917") == "5917"


def test_absent_code_is_an_empty_cell():
    assert categories.category_cell(None) == ""


def test_blank_code_is_an_empty_cell():
    assert categories.category_cell("   ") == ""


def test_code_surrounding_whitespace_is_normalized():
    assert categories.category_cell(" 5411 ") == "ALIMENTACIÓN"
