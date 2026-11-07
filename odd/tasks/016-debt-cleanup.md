# 016 debt cleanup

Goal: pay the debt disclosed in PR #26 and adjudicate the false-positive review finding, without
changing the observable behaviour of `banking sync`, `banking daily` or the published workflow
summary.

## Scope (decided 2026-11-07)

Three of the four pieces, no workflow decoupling:

- **A** — one shared implementation of `notify_and_exit`, `print_not_onboarded_note` and
  `current_tab_name`, duplicated today between `src/banking/cli/sync.py` and
  `src/banking/cli/daily.py`.
- **B** — one shared total-failure message, duplicated today between `src/banking/sync.py` and
  `src/banking/daily.py`.
- **C** — resolve the PSD2 session and the account once per bank and run instead of once per stage.

Explicitly out of scope: replacing the workflow's `grep` over `banking.daily` log lines with a
machine-readable summary. That changes the production summary contract and needs its own
increment with a real run to re-validate.

## Request accounting (the reason C matters)

Per bank and run, before this change:

```
GET /sessions/{id}                       <- fetch_transactions
GET /accounts/{id}/transactions          <- 1 per page
GET /sessions/{id}                       <- fetch_balance
GET /accounts/{id}/balances
= 4 GET with a single transactions page
```

After C, the session and account lookup happens once per connector instance:

```
GET /sessions/{id}                       <- once, cached on the instance
GET /accounts/{id}/transactions          <- 1 per page
GET /accounts/{id}/balances
= 3 GET with a single transactions page
```

The PSD2 limit stays 4 GET per account and day; the headroom from 1 to 2 GET is what buys room for
one extra transactions page.

## Tasks

- [ ] T1 — Cache the PSD2 session lookup in `EnableBankingConnector` (credential, session id and
      account id resolved once per instance) with a test that counts requests to
      `/sessions/{id}` across `fetch_transactions` + `fetch_balance` (test first: RED before the
      cache).
- [ ] T2 — Extract the shared CLI failure helpers into `src/banking/cli/common.py` and consume them
      from `cli/sync.py` and `cli/daily.py`, keeping the existing CLI tests green without edits.
- [ ] T3 — Extract the shared total-failure message into `src/banking/run_summary.py`, backed by a
      `failure_reason` property on `BankPass` and the existing `BankOutcome.failure_reason`.
- [ ] T4 — Update the quota accounting everywhere it claims the fused pass spends 4 GET
      (`docs/context.md`, `quickstart.md`, `specs/016-single-daily-pass/{spec,plan,quickstart}.md`).
- [ ] T5 — Adjudicate `R4-STALE-SUMMARY` in writing: the finding is false and no code changes.
- [ ] T6 — Gates (`pytest`, `ruff check`, `ruff format --check`, `mypy src/`) and a ready PR.

## Adjudication: `R4-STALE-SUMMARY`

**The claim** (native review lineage `review-74be087fe6327774`, CRITICAL, lens `review-resilience`):
an `if not transactions:` guard at `src/banking/sheets/layout.py:455-458` skips
`_write_summary_region`, so an empty month would leave a stale summary panel.

**Why it is false**:

- `grep -n "if not transactions"` over the frozen candidate tree returns nothing.
- `layout.py:455-458` are the `_write_summary_region` docstring plus the `first_row`/`last_row`
  assignments, not a guard.
- The call is unconditional on the existing-tab path (`layout.py:570-571`).
- Two tests pin the exact scenario: `tests/unit/test_layout_writer.py:456
  test_empty_month_still_refreshes_the_panel` and `:528
  test_second_run_drops_stale_expense_rows_and_handles_an_empty_month`.
- The same `layout.py` passed a later native review with no findings at all
  (`review-c6f1e6057ace1bd7`, tier medium, lens `review-reliability`, approved 2026-11-07).

**Disposition**: adjudicated false, superseded by the later approval, no code change. The stranded
lineage stays in `correction_required`; closing it needs an audited native `review abandon` with
inputs the compact facade does not expose, so it is left to a maintainer decision.
