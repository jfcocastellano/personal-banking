"""Domain layer of the single daily pass: one fetch per bank and stage.

The daily pass queries every bank exactly once for movements and once for the
balance, so it stays inside the PSD2 request budget. This module only collects
raw data; classification, guards and the Sheets writes live one layer up.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from banking.connectors.enable_banking import (
    Balance,
    BankNotOnboardedError,
    EnableBankingConnector,
    Transaction,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BankPass:
    """The raw result of querying one bank once for movements and once for balance.

    Each stage fails on its own: a transactions failure leaves ``balance``
    populated and vice versa. ``not_onboarded`` marks a bank without a PSD2
    session yet, which is an expected state rather than a failure, so in that
    case both ``*_failure`` fields stay ``None``.
    """

    bank_name: str
    transactions: tuple[Transaction, ...] = ()
    balance: Balance | None = None
    transactions_failure: str | None = None
    balance_failure: str | None = None
    not_onboarded: bool = False


def _log_not_onboarded(bank_name: str, stage: str, exc: BankNotOnboardedError) -> None:
    """Log a missing PSD2 session at INFO: it is an expected state, not an error."""
    logger.info(
        "Daily pass skipped stage: bank=%s stage=%s not onboarded (no PSD2 session yet) reason=%s",
        bank_name,
        stage,
        exc,
    )


def _log_stage_failure(bank_name: str, stage: str, exc: Exception) -> None:
    """Log a real stage failure at ERROR, naming the bank and the failed stage."""
    logger.error(
        "Daily pass stage failed: bank=%s stage=%s reason=%s",
        bank_name,
        stage,
        exc,
    )


def collect_bank_runs(
    connectors: Sequence[EnableBankingConnector],
    *,
    start_date: date,
    end_date: date,
) -> tuple[BankPass, ...]:
    """Query each bank once for movements and once for its current balance.

    Both stages run for every bank, in the order the connectors were given: a
    transactions failure never skips the balance, and a balance failure never
    discards the movements. Exceptions other than `BankNotOnboardedError` are
    captured in the matching ``*_failure`` field instead of aborting the loop.

    Args:
        connectors: The bank connectors to query, in the desired output order.
        start_date: First movement booking date to request, inclusive.
        end_date: Last movement booking date to request, inclusive.

    Returns:
        One `BankPass` per connector, in the same order as ``connectors``.
    """
    runs: list[BankPass] = []
    for connector in connectors:
        bank_name = connector.BANK_NAME
        transactions: tuple[Transaction, ...] = ()
        transactions_failure: str | None = None
        balance: Balance | None = None
        balance_failure: str | None = None
        not_onboarded = False

        try:
            transactions = tuple(connector.fetch_transactions(start_date, end_date))
        except BankNotOnboardedError as exc:
            not_onboarded = True
            _log_not_onboarded(bank_name, "transactions", exc)
        except Exception as exc:
            transactions_failure = str(exc)
            _log_stage_failure(bank_name, "transactions", exc)

        try:
            balance = connector.fetch_balance()
        except BankNotOnboardedError as exc:
            not_onboarded = True
            _log_not_onboarded(bank_name, "balance", exc)
        except Exception as exc:
            balance_failure = str(exc)
            _log_stage_failure(bank_name, "balance", exc)

        runs.append(
            BankPass(
                bank_name=bank_name,
                transactions=transactions,
                balance=balance,
                transactions_failure=transactions_failure,
                balance_failure=balance_failure,
                not_onboarded=not_onboarded,
            )
        )

    return tuple(runs)
