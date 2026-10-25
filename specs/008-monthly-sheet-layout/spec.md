# Feature Specification: Monthly accounting sheet layout

**Feature branch**: `008-monthly-sheet-layout`
**Status**: Draft
**Input**: Reproduce the manual Excel accounting sheet (three blocks: individual expenses, shared expenses, income/summary/balances) inside the Google Sheet this project already writes, filling the parts that can be derived from bank transactions.

## Problem

The project writes one flat table per month (`YYYY-MM`, five columns) built from bank transactions. The human user keeps their real monthly accounting in a different structure: a three-block layout with individual expenses on the left, shared expenses in the middle, and an income/summary/balances panel on the right. Reading the generated tab requires manually reshaping every month, which is exactly the work the project exists to remove.

## Scope

### In scope

- Generate a per-month layout tab (`YYYY-MM Gastos`) next to the existing raw tab (`YYYY-MM`), which stays untouched.
- Fill the individual-expenses block with the month's transactions from every bank that has a connector (ING España, Revolut, MyInvestor, Banco Sabadell).
- Reproduce the shared-expenses block with the category catalogue from the reference worksheet, left empty until Banco Sabadell credentials work.
- Fill the summary block with formulas over the individual-expenses block, and the account-balances panel with the balance reported by each bank.
- Add the missing balance capability to the Enable Banking connector.

### Out of scope (non-goals)

- Automatic categorisation of shared expenses. The catalogue is reproduced; the amounts stay manual.
- Historical balances. PSD2 exposes the balance of the moment it is requested; there is no retroactive month-end balance.
- Daily balance snapshots. Deferred to the scheduler feature (`specs/007-scheduler-github-actions`).
- An N26 connector. N26 appears in the reference worksheet but has no connector in this project.
- Writing the raw tab. Its shape, contents and overwrite semantics do not change.
- Any Banco Sabadell data. Blocked provider-side; see `docs/credentials-setup.md` § 3.5.

## User scenarios

### Primary story

1. The user runs the monthly layout command for a month with data in the raw tab.
2. The system creates `YYYY-MM Gastos` with the three blocks, the shared-expense catalogue, the summary formulas and the balance panel.
3. The user opens that tab and reads their month in the structure they already know, then edits concepts or types shared amounts by hand.

### Edge cases

- **The layout tab already exists.** Only the individual-expenses block is rewritten; the shared-expenses amounts, the income cells and the balance panel are never modified, so hand edits survive regeneration.
- **A bank fails while fetching balances.** The layout is still produced; that account's balance cell stays empty and the failure is logged and reported. A balance failure never fails the layout.
- **A bank returns no balance at all.** The cell stays empty; no zero is invented.
- **A bank returns several balance types.** A single value per account is selected by a documented preference order (closing booked first).
- **The month has no transactions.** The layout is still created with headers, catalogue and formulas; totals evaluate to zero.
- **More transactions than rows reserved for the block.** The limit is documented and the write fails loudly instead of silently truncating.

## Functional requirements

- **FR-001**: The system MUST expose one command that generates the layout tab for an explicit month.
- **FR-002**: The layout tab MUST be named `<YYYY-MM> Gastos` and MUST NOT be the tab written by the daily sync.
- **FR-003**: The individual-expenses block MUST contain four columns: settlement date, bank, description, amount. It MUST NOT contain the currency column.
- **FR-004**: The individual-expenses block MUST be ordered by settlement date and then by bank name, so repeated runs produce identical output for identical input.
- **FR-005**: The shared-expenses block MUST reproduce the reference catalogue of categories in a fixed order, with an empty total column and a total row.
- **FR-006**: The summary block MUST use formulas, not precomputed numbers, so that a hand-edited amount updates the totals.
- **FR-007**: The summary block MUST report total income, total expenses and their net result computed from the individual-expenses block.
- **FR-008**: The balances panel MUST list one row per connector-backed account and a total row, and MUST state the reference date of the reported balances.
- **FR-009**: Regenerating an existing layout tab MUST preserve every cell of the shared-expenses and income regions.
- **FR-010**: The Enable Banking connector MUST expose account balances and select one balance per account by a documented, tested preference order.
- **FR-011**: Balance retrieval MUST be isolated per bank: one failure MUST NOT prevent the layout from being generated.
- **FR-012**: The repository MUST ignore the local `.orca/` drop directory so that user-supplied financial files cannot be committed.

## Layout contract

Column A is a spacer, as in the reference worksheet.

| Region | Cells | Content |
| --- | --- | --- |
| Titles | `B2:E2`, `G2:H2`, `J2:K2` | `GASTOS`, `GASTOS COMUNES`, `INGRESOS` |
| Headers | row 3 | `FECHA`, `BANCO`, `DESCRIPCIÓN`, `IMPORTE` · `CATEGORÍA`, `TOTAL` · `CONCEPTO`, `IMPORTE` |
| Individual expenses | `B4:E…` | one row per transaction |
| Shared expenses | `G4:G52` labels, `H4:H52` manual totals, row 53 total | reference catalogue |
| Summary | `J4:K…` | income, expenses, net result |
| Balances | below the summary | one row per account, total row, reference date |

## Success criteria

- A generated tab reads as the reference worksheet's three-block structure, with block positions matching the contract above.
- Rerunning the command on a tab where a shared-expense amount was typed by hand leaves that amount, and every other manual cell, byte-identical.
- Summary formulas recalculate in Google Sheets when a value in the individual-expenses block is edited by hand.
- Balance rows show a value for each bank whose balance request succeeded and are empty for the ones that failed, with the failure visible in logs and in the command's report.
