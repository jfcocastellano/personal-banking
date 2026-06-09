"""
ProcessLogger: centralized log writer with ISO 8601 timestamps and severity levels.

Implements Requirements 8.1–8.5 and 8.7:
  - 8.1: Opens log file in append mode; creates directory if needed.
  - 8.2: INFO entries with timestamp, component, bank/global, message.
  - 8.3: WARNING entries with the same fields.
  - 8.4: ERROR entries with the same fields; never reveals credential values.
  - 8.5: INFO entry written on flow completion.
  - 8.7: Fallback to stderr if file write fails; silent if stderr also fails.

Security note: this class writes whatever message it receives. Callers are
responsible for ensuring no credential or token value is included in the
message string (Requirement 7.4 / 8.4).
"""

import sys
from datetime import datetime, timezone
from pathlib import Path


class ProcessLogger:
    """Write timestamped, levelled log entries to a daily log file.

    The log file is named ``execution_{YYYY_MM_DD}.log`` and placed in
    *log_dir*.  The directory is created if it does not exist.  The file
    is opened in append mode so re-executions on the same day accumulate
    entries rather than overwriting them (Requirement 8.1).

    If the file cannot be opened or written to, the logger falls back to
    ``stderr``.  If ``stderr`` also fails, the entry is silently discarded
    and execution continues uninterrupted (Requirement 8.7).
    """

    def __init__(self, log_dir: Path) -> None:
        """Initialise the logger and open (or create) the daily log file.

        Parameters
        ----------
        log_dir:
            Directory where log files are stored.  Created automatically
            (including any missing parent directories) if it does not exist.
        """
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(tz=timezone.utc).strftime("%Y_%m_%d")
        log_path = log_dir / f"execution_{date_str}.log"

        self._file = None
        try:
            self._file = open(log_path, "a", encoding="utf-8")  # noqa: SIM115
        except OSError:
            # File could not be opened; all writes will fall back to stderr.
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def info(self, component: str, bank: str | None, message: str) -> None:
        """Write an INFO-level log entry.

        Parameters
        ----------
        component:
            Name of the component producing the entry (e.g.
            ``"TransactionFetcher"``).
        bank:
            Bank entity name, or ``None`` when the entry is not
            bank-specific (rendered as ``global`` in the log line).
        message:
            Human-readable description of the step or event.  MUST NOT
            contain any credential or token value.
        """
        self._write("INFO", component, bank, message)

    def warning(self, component: str, bank: str | None, message: str) -> None:
        """Write a WARNING-level log entry.

        Parameters
        ----------
        component:
            Name of the component producing the entry.
        bank:
            Bank entity name, or ``None`` for a global entry.
        message:
            Description of the anomalous but non-blocking situation.
            MUST NOT contain any credential or token value.
        """
        self._write("WARNING", component, bank, message)

    def error(self, component: str, bank: str | None, message: str) -> None:
        """Write an ERROR-level log entry.

        Parameters
        ----------
        component:
            Name of the component producing the entry.
        bank:
            Bank entity name, or ``None`` for a global entry.
        message:
            Description of the error condition.  MUST NOT contain any
            credential or token value (Requirement 8.4).
        """
        self._write("ERROR", component, bank, message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write(
        self,
        level: str,
        component: str,
        bank: str | None,
        message: str,
    ) -> None:
        """Format and persist a single log line.

        Format::

            {ISO8601_TIMESTAMP} [{LEVEL}]    {COMPONENT} [{BANK}|global] {MESSAGE}

        The timestamp uses UTC and the ``YYYY-MM-DDTHH:MM:SSZ`` form.
        The bank field is the supplied *bank* value when not ``None``,
        otherwise the literal string ``global``.

        Write attempts:
        1. Try to write to the log file.
        2. On failure, try to write to ``stderr``.
        3. On ``stderr`` failure, discard the entry and continue silently.
        """
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bank_field = bank if bank is not None else "global"
        line = f"{timestamp} [{level}]    {component} [{bank_field}] {message}\n"

        if self._file is not None:
            try:
                self._file.write(line)
                self._file.flush()
                return
            except OSError:
                # File write failed; fall through to stderr.
                pass

        # Fallback: emit to stderr.
        try:
            sys.stderr.write(line)
            sys.stderr.flush()
        except OSError:
            # stderr also failed; continue silently (Requirement 8.7).
            pass
