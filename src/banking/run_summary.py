"""One total-failure message for both ``banking sync`` and ``banking daily``.

Both pipelines abort a run when no bank could contribute data, and both render
the same two-branch wording. The message only needs a bank's name and why it
failed, so it is built from a small protocol that `banking.sync.BankOutcome` and
`banking.daily.BankPass` satisfy as they are.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class FailedBank(Protocol):
    """One bank that the total-failure message can name."""

    @property
    def bank_name(self) -> str:
        """The bank name as it appears in the report."""
        ...

    @property
    def failure_reason(self) -> str | None:
        """Why this bank failed, or ``None`` when no reason is known."""
        ...


def total_failure_message(failed: Sequence[FailedBank], not_onboarded: Sequence[FailedBank]) -> str:
    """Render a total-failure message that does not call onboarded banks failed."""
    aggregate = "; ".join(f"{bank.bank_name}: {bank.failure_reason}" for bank in failed)
    if not not_onboarded:
        return f"All {len(failed)} banks failed: {aggregate}"
    names = ", ".join(bank.bank_name for bank in not_onboarded)
    return (
        f"No bank could sync. Failed: {aggregate}. "
        f"Not onboarded (no PSD2 session yet, not a failure): {names}"
    )
