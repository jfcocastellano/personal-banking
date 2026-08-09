"""Tests for banking.sheets.writer — every gspread interaction is mocked."""

import json
import logging
from unittest.mock import Mock

import gspread
import pytest

from banking.config.secret_store import SecretStore
from banking.sheets.writer import (
    SheetsAccessError,
    SheetsAPIError,
    SheetsConfigError,
    SheetsQuotaExceededError,
    SheetsWriter,
)


def _api_error(status_code: int, message: str = "boom") -> gspread.exceptions.APIError:
    """Build a real gspread APIError wrapping a fake HTTP response."""
    response = Mock()
    response.status_code = status_code
    response.json.return_value = {
        "error": {"code": status_code, "message": message, "status": "ERROR"}
    }
    return gspread.exceptions.APIError(response)


def _client_with_existing_worksheet() -> tuple[Mock, Mock, Mock]:
    """Return (client, spreadsheet, worksheet) wired so the tab already exists."""
    worksheet = Mock(spec=gspread.Worksheet)
    spreadsheet = Mock(spec=gspread.Spreadsheet)
    spreadsheet.worksheet.return_value = worksheet
    client = Mock(spec=gspread.Client)
    client.open_by_key.return_value = spreadsheet
    return client, spreadsheet, worksheet


# --- US1: overwrite an existing tab -----------------------------------------


def test_write_overwrites_existing_tab_from_a1() -> None:
    client, spreadsheet, worksheet = _client_with_existing_worksheet()
    writer = SheetsWriter(client=client)

    writer.write("doc-id", "2026-08", ["fecha", "importe"], [["2026-08-01", 42.5]])

    spreadsheet.worksheet.assert_called_once_with("2026-08")
    worksheet.clear.assert_called_once()
    worksheet.update.assert_called_once_with(values=[["fecha", "importe"], ["2026-08-01", 42.5]])


def test_write_with_empty_rows_writes_only_headers() -> None:
    client, _spreadsheet, worksheet = _client_with_existing_worksheet()
    writer = SheetsWriter(client=client)

    writer.write("doc-id", "2026-08", ["fecha", "importe"], [])

    worksheet.update.assert_called_once_with(values=[["fecha", "importe"]])


def test_write_passes_irregular_rows_unchanged() -> None:
    client, _spreadsheet, worksheet = _client_with_existing_worksheet()
    writer = SheetsWriter(client=client)
    rows: list[list[object]] = [["a"], ["b", "c", "d"]]

    writer.write("doc-id", "2026-08", ["col1", "col2"], rows)

    worksheet.update.assert_called_once_with(values=[["col1", "col2"], ["a"], ["b", "c", "d"]])


def test_write_success_emits_info_log_with_tab_and_row_count(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _spreadsheet, _worksheet = _client_with_existing_worksheet()
    writer = SheetsWriter(client=client)

    with caplog.at_level(logging.INFO, logger="banking.sheets.writer"):
        writer.write("doc-id", "2026-08", ["a", "b"], [["1", "2"], ["3", "4"]])

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    message = info_records[0].getMessage()
    assert "tab=2026-08" in message
    assert "rows_written=2" in message


def test_missing_credentials_raises_config_error() -> None:
    writer = SheetsWriter()  # no client injected, no secret stored anywhere

    with pytest.raises(SheetsConfigError):
        writer.write("doc-id", "2026-08", ["a"], [])


def test_invalid_json_credentials_raises_config_error(
    mock_master_key: str, tmp_env_file, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))
    SecretStore(tmp_env_file).set("GOOGLE_SHEETS_CREDENTIALS", "not valid json")
    writer = SheetsWriter()

    with pytest.raises(SheetsConfigError):
        writer.write("doc-id", "2026-08", ["a"], [])


def test_credentials_missing_required_field_raises_config_error(
    google_sheets_credentials_in_store: dict[str, str], tmp_env_file
) -> None:
    info = dict(google_sheets_credentials_in_store)
    del info["private_key"]
    SecretStore(tmp_env_file).set("GOOGLE_SHEETS_CREDENTIALS", json.dumps(info))
    writer = SheetsWriter()

    with pytest.raises(SheetsConfigError):
        writer.write("doc-id", "2026-08", ["a"], [])


def test_inaccessible_document_raises_access_error() -> None:
    client = Mock(spec=gspread.Client)
    client.open_by_key.side_effect = gspread.exceptions.SpreadsheetNotFound
    writer = SheetsWriter(client=client)

    with pytest.raises(SheetsAccessError, match="doc-id"):
        writer.write("doc-id", "2026-08", ["a"], [])


# --- US2: create the target tab automatically -------------------------------


def test_write_creates_missing_tab_without_clearing() -> None:
    new_worksheet = Mock(spec=gspread.Worksheet)
    spreadsheet = Mock(spec=gspread.Spreadsheet)
    spreadsheet.worksheet.side_effect = gspread.exceptions.WorksheetNotFound
    spreadsheet.add_worksheet.return_value = new_worksheet
    client = Mock(spec=gspread.Client)
    client.open_by_key.return_value = spreadsheet
    writer = SheetsWriter(client=client)

    writer.write("doc-id", "2026-09", ["a", "b"], [[1, 2]])

    spreadsheet.add_worksheet.assert_called_once_with(title="2026-09", rows=1, cols=2)
    new_worksheet.clear.assert_not_called()
    new_worksheet.update.assert_called_once_with(values=[["a", "b"], [1, 2]])


def test_write_does_not_create_duplicate_tab_when_it_already_exists() -> None:
    client, spreadsheet, _worksheet = _client_with_existing_worksheet()
    writer = SheetsWriter(client=client)

    writer.write("doc-id", "2026-08", ["a"], [])

    spreadsheet.add_worksheet.assert_not_called()


# --- US3: observability for every category of failure, and for success -----


def test_quota_exceeded_on_update_raises_quota_error_with_log(
    google_sheets_credentials_in_store: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _spreadsheet, worksheet = _client_with_existing_worksheet()
    worksheet.update.side_effect = _api_error(429)
    writer = SheetsWriter(client=client)

    with caplog.at_level(logging.ERROR, logger="banking.sheets.writer"):
        with pytest.raises(SheetsQuotaExceededError, match="quota"):
            writer.write("doc-id", "2026-08", ["a"], [])

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "tab=2026-08" in message
    assert "SheetsQuotaExceededError" in message
    assert google_sheets_credentials_in_store["private_key"] not in message


def test_unexpected_api_error_on_update_raises_api_error_with_log(
    google_sheets_credentials_in_store: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _spreadsheet, worksheet = _client_with_existing_worksheet()
    worksheet.update.side_effect = _api_error(500)
    writer = SheetsWriter(client=client)

    with caplog.at_level(logging.ERROR, logger="banking.sheets.writer"):
        with pytest.raises(SheetsAPIError):
            writer.write("doc-id", "2026-08", ["a"], [])

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "tab=2026-08" in message
    assert "SheetsAPIError" in message
    assert google_sheets_credentials_in_store["private_key"] not in message


def test_config_and_access_failures_also_emit_failure_log(
    google_sheets_credentials_in_store: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = Mock(spec=gspread.Client)
    client.open_by_key.side_effect = gspread.exceptions.SpreadsheetNotFound
    writer = SheetsWriter(client=client)

    with caplog.at_level(logging.ERROR, logger="banking.sheets.writer"):
        with pytest.raises(SheetsAccessError):
            writer.write("doc-id", "2026-08", ["a"], [])

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(error_records) == 1
    message = error_records[0].getMessage()
    assert "tab=2026-08" in message
    assert "SheetsAccessError" in message
    assert google_sheets_credentials_in_store["private_key"] not in message


def test_write_success_logs_measured_duration_and_exact_row_count(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, _spreadsheet, _worksheet = _client_with_existing_worksheet()
    writer = SheetsWriter(client=client)

    times = iter([100.0, 100.25])
    monkeypatch.setattr("banking.sheets.writer.time.monotonic", lambda: next(times))

    with caplog.at_level(logging.INFO, logger="banking.sheets.writer"):
        writer.write("doc-id", "2026-08", ["a"], [[1], [2], [3]])

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    message = info_records[0].getMessage()
    assert "rows_written=3" in message
    assert "duration=0.250s" in message
