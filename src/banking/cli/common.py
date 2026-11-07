"""Failure helpers shared by the ``banking sync`` and ``banking daily`` handlers.

Both commands fail the same way: they print a per-bank report, name the banks
without a PSD2 session, and send one failure email whose delivery failure becomes
exit code ``4``. Those pieces used to be duplicated in ``cli/sync.py`` and
``cli/daily.py``; they live here once, typed over the notifier's per-bank
`BankOutcome`.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from datetime import date

from banking.notify import DeliveryStatus, EmailNotifier
from banking.sync import BankOutcome

#: Printed on stderr when the failure email could not be delivered (exit code 4).
NOTIFICATION_FAILED_MESSAGE = "ERROR (notificación): no se pudo enviar el email de aviso"


def print_not_onboarded_note(outcomes: Sequence[BankOutcome]) -> None:
    """Name the banks without a PSD2 session, worded so it is not read as a failure."""
    names = [outcome.bank_name for outcome in outcomes if outcome.not_onboarded]
    if not names:
        return
    print(f"  Bancos sin sesión PSD2 (no cuentan como fallo): {', '.join(names)}")


def current_tab_name() -> str:
    """Return this month's tab name, used when an exception carries no context."""
    return date.today().strftime("%Y-%m")


def notify_and_exit(
    notifier: EmailNotifier | None,
    outcomes: Sequence[BankOutcome],
    sheets_error: str | None,
    tab_name: str,
    duration_seconds: float,
    *,
    notifier_factory: Callable[[], EmailNotifier] = EmailNotifier,
) -> int | None:
    """Send the failure email and translate a delivery failure into exit code 4.

    Args:
        notifier: The notifier to use. Injected by tests; the real one is built
            only when a failure actually has to be notified.
        outcomes: Per-bank outcomes of the run, already adapted to the
            notifier's type.
        sheets_error: The Sheets error message, when the run failed (or
            partially failed) while writing.
        tab_name: The destination tab of the run.
        duration_seconds: How long the run took.
        notifier_factory: Builds the notifier when ``notifier`` is ``None``. Each
            CLI module passes its own module-level ``EmailNotifier``, so a test
            can keep replacing that name to observe or forbid the build.

    Returns:
        ``4`` when the delivery failed, ``None`` when it was sent or skipped
        (in which case the caller keeps the run's own exit code).
    """
    email_notifier = notifier if notifier is not None else notifier_factory()
    status = email_notifier.notify_failure(
        outcomes=list(outcomes),
        sheets_error=sheets_error,
        tab_name=tab_name,
        duration_seconds=duration_seconds,
    )
    if status is DeliveryStatus.FAILED:
        print(NOTIFICATION_FAILED_MESSAGE, file=sys.stderr)
        return 4
    return None
