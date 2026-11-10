# 017 — Consistent sheet order and knowing which transaction fields the API really returns

Status: in progress.

## Why

Two independent problems, reported by the owner after watching the production sheet.

1. **The two tabs disagree on row order.** The raw month tab (`2026-11`) shows newest
   first; the expenses tab (`2026-11 Gastos`) shows oldest first. Nobody chose this: it
   comes from two different code paths, and reading the sheet means re-learning the order
   on every tab.
2. **The roadmap asserts something false.** `docs/roadmap.md` justifies the manual
   `G:H` categorisation with "ninguna API informa la categoría". The Enable Banking
   transaction object documents `merchant_category_code` (ISO 18245), plus
   `bank_transaction_code`, `creditor`/`debtor` and a stable `entry_reference`. The
   premise behind that design note is wrong, and the manual categorisation decision was
   argued on top of it.

## Diagnosis (verified, not assumed)

### Row order

| Tab | Rows built by | Order |
| --- | --- | --- |
| `YYYY-MM` (raw) | `sync.transaction_rows()` (`src/banking/sync.py:130-135`), flattened per bank in `src/banking/daily.py:341` and `src/banking/sync.py:241` | API order, newest first, concatenated bank block after bank block |
| `YYYY-MM Gastos` | `layout._expense_rows()` (`src/banking/sheets/layout.py:287-293`) | `sorted()` ascending by `(booking_date, bank, description)` |

The writer (`src/banking/sheets/writer.py:104-125`) is deliberately banking-agnostic —
"has no knowledge of any banking concepts" — so ordering must not be added there. The
sort belongs where the rows are composed, over `(bank, transaction)` pairs.

### API fields

Fetched from the official reference (`https://enablebanking.com/docs/api/reference/`,
anchors `#schematransaction` and `#banktransactioncode`). Required fields are
`transaction_amount`, `credit_debit_indicator` and `status`; everything below is
**optional**:

| Field | Type | Use for grouping |
| --- | --- | --- |
| `merchant_category_code` | string | ISO 18245 category of the merchant. The closest thing to a native tag. |
| `bank_transaction_code` | `{description, code, sub_code}` | Per-ASPSP categorisation, e.g. `Utlandsbetalning / 12 / 32`. |
| `entry_reference` | string | Unique **and immutable** per account; matches transactions across PSU sessions. |
| `creditor` / `debtor` | `PartyIdentification` | Counterparty name. |
| `value_date`, `transaction_date` | date | Finer dates than `booking_date`. |
| `balance_after_transaction` | `AmountType` | Running balance per movement. |
| `note`, `reference_number`, `reference_number_schema`, `exchange_rate` | varios | Ancillary detail. |
| `transaction_id` | string | **Unusable as an id**: the reference says it cannot identify transactions uniquely and may change. |

Today `_parse_transaction` (`src/banking/connectors/enable_banking.py:190-216`) keeps only
`booking_date`, `transaction_amount.{amount,currency}`, `credit_debit_indicator` and
`remittance_information` (space-joined). Everything else is discarded silently, and
`Transaction` (`:92-99`) has no room for it.

**Unverified:** whether ING España and Revolut actually populate these optional fields.
That is the only open question, and it costs no extra PSD2 request: the payload already
arrives on every run.

## Scope

### T1 — Correct the falsified premise and document the available fields

Fix `docs/roadmap.md` so the manual-categorisation note stops claiming that no API
reports a category, and add the field table above plus the "population unverified" caveat
to `docs/context.md`.

### T2 — Ascending order in the raw tab

Compose the rows for several banks in one ascending order — `(booking_date, bank,
description, amount)` — with the amount as the final deterministic tiebreaker. The key
matches the expenses tab so both tabs read the same way. Test-first: a RED test that fixes
a cross-bank, out-of-order input and asserts ascending output.

### T3 — Log which transaction fields each bank actually returns

Accumulate the key names present in each transaction record and log them once per fetch,
by name only — never values, never `remittance_information`, so no PII reaches the log.
The line goes at `INFO`, deliberately: the run log in Actions is the place where the
answer has to be readable, so the probe must not depend on `LOG_LEVEL` being raised by
somebody (`src/banking/logging_config.py:14` exists, but a scheduled run cannot pass it).
Test-first against a fake payload that carries `status`, `merchant_category_code` and
`entry_reference`.

### T4 — Grouping (conditional, blocked on T3 evidence)

Only if T3 shows the fields arrive: widen `Transaction` with `merchant_category_code`,
`entry_reference` and the counterparty name, carry them through the writer, and expose a
grouping that the expenses tab can use. Not planned in detail until the evidence exists.

## Out of scope

- Replacing the manual `G:H` categorisation. T1 only removes the false justification; the
  decision itself belongs to the owner once T3 answers what data arrives.
- Changing the dedup key to `entry_reference`. Worth a separate feature: it needs the
  field to be populated first.
- Any change to `SheetsWriter` (stays banking-agnostic) or to the tab names and headers.
- The GitHub cron reliability discussed in `docs/context.md`: accepted risk for now, by
  owner decision.

## Evidence

Recorded below as each task closes.

### T1 — closed in `5144574`

The false premise survived in **four** places, not one: `docs/roadmap.md:512-525`, the root
`quickstart.md:449`, and `specs/008-monthly-sheet-layout/quickstart.md:77-80` in addition to
the roadmap bullet. All corrected. The field table, the optionality and the `transaction_id`
warning now live in `docs/context.md` under «Campos de transacción disponibles», and every
other place points there instead of repeating it.

### T2 — closed in `8411c9a`

RED before GREEN, on order rather than imports:

```text
At index 0 diff: ['2026-08-10', 'ING España', 'Compra', -4.0, 'EUR']
              != ['2026-08-01', 'ING España', 'Nomina', 900.0, 'EUR']
At index 0 diff: ('2026-11-09', 'ING España', 'ING última')
              != ('2026-11-02', 'Revolut', 'Revolut primera')
```

Both flattening call sites (`src/banking/daily.py:340`, `src/banking/sync.py:282`) now go
through `transaction_rows_for_banks`, which sorts over `(bank, transaction)` pairs by
`(booking_date, bank, description, amount)`. The amount is compared as `Decimal`; `float()`
appears only when the cell is built.

The per-bank `transaction_rows` helper **was deleted**, not kept: after both call sites moved it
had no production caller, and leaving it behind would have kept a function that returns API
order (newest first) one import away from silently reverting the fix. The column shape now
lives in `_transaction_row` and nowhere else.

Known asymmetry: `layout._sort_key` has no amount component, so the raw tab is a superset. The
two tabs agree on direction; they agree on tie order too unless the expenses tab ever holds two
rows with the same date, bank and description, which it cannot today.

### T3 — closed in `b1dd9ad`

RED: `assert 0 == 1 — where 0 = len([])` over the captured log, with only the pre-existing
`records retrieved` line present. GREEN adds one line per fetch at `INFO`:

```text
Connector ING España: transaction fields, records=42, keys=bank_transaction_code,booking_date,...
```

The tests assert the presence of `status`, `merchant_category_code` and `entry_reference` **and
the absence of** the values `5411`, `REF-UNICA-0001`, `NOMINA CONFIDENCIAL SL`, `42.50` and
`2026-08-15`. Two further tests fix the boundaries: no line when the account returned zero
records, and exactly one line across two pages when every record was filtered out (that case
proves a field can arrive and the movement still be discarded).

One existing test had to change: `test_success_logs_structured_record` asserted a single INFO
record for that logger, which was true only while the connector logged once per fetch.

### T4 — Categories as data and as presentation (owner-directed, unblocked by production evidence)

The T3 probe answered the blocking question on the 2026-11-10 scheduled run
(Actions run `42831483339`): `merchant_category_code` and `entry_reference`
appear in the `keys=` list for both ING España (records=26) and Revolut
(records=1). The fields arrive; the category can be surfaced.

**Owner direction (2026-11-10, verbatim).** First statement: «Que en la pestaña
de movimientos se muestre tambien la categoria como una columna mas, y que en
la pestaña de gastos muestre los movimientos igual que en la otra pestaña y
que ademas haga la agrupacion y sumatorio por categoria». Then revised after
reviewing the geometry: «creo que mejor dejar la pestaña 2026-11 con los
movimientos (junto con la categoria) y en la pestaña 2026-11 Gastos hacer la
agrupacion por categoria, sin fecha, sin banco, sin descripcion, solo los
sumatorios. Ejemplos: alimentacion 58€, ropa 23€, etc. Los gastos comunes y el
resumen se dejarian como hasta ahora». Decisions given as option answers:
«Solo sumatorios, sin lista de movimientos» and «Etiquetas en español +
fallback al código». Added context: «Gastos comunes son gastos de la cuenta
conjunta del hogar, y corresponderian con los movimientos del Sabadell, que no
podemos recuperar» — hence the manual G:H catalogue stays hand-run.

**Spec for this slice (S# = verbatim-derived rules):**

- **S1** — New module `src/banking/categories.py`: a static ISO 18245 →
  Spanish-label table for common consumer codes, and `category_cell(code)` →
  mapped label, else the raw code, else `""`. No network, no invented labels.
- **S2** — `_parse_transaction` keeps `merchant_category_code` (empty/whitespace
  or absent → `None`, never aborts the record). `entry_reference` and the
  counterparty names are **dropped from this slice**: nothing requested consumes
  them (YAGNI); the T3 probe keeps recording key names for a future decision.
- **S3** — The raw tab becomes **six columns**: `_HEADERS` gains "Categoría",
  `_transaction_row` appends `category_cell(tx.merchant_category_code)`.
  Sort key unchanged (category is never a tiebreaker).
- **S4** — The `Gastos` tab replaces the per-movement block with the category
  sums block only: headers `CATEGORÍA` / `TOTAL GASTOS` at B3/C3, then one row
  per category: label in B, signed total in C. Grouping covers expenses only
  (`amount < 0`): incomes never inflate the block. Transactions without a
  category code group under the label `SIN CATEGORÍA` so the sums still add up.
  Order: descending total, then ascending label — deterministic. Cap 50 rows
  (`MAX_CATEGORY_ROWS`), exceeded → `ValueError` before any write. The date,
  bank and description columns disappear from this tab: `ExpenseRow`'s display
  row (`_expense_row`, `_sort_key`, `_expense_rows`) and its per-movement
  placement are removed; `ExpenseRow` itself survives as the sums block's input
  carrier, gaining `category: str | None = None` (resolved label/code) filled
  by `expense_rows_from_banks`.
- **S5** — The `J:K` resumen keeps its labels and stays as now in geometry, but
  its formulas reconnect: «Gastos» = `SUM` over the sums block (C4:C53),
  «Ingresos» = cross-tab `SUMIF` over the movements tab's Importe column
  (the tab name is derived from the layout tab name by stripping the
  " Gastos" suffix — both composed by `layout_tab_name`/`daily.py`). Numbers
  must match the pre-change resumen for unchanged input.
- **S6** — Refresh path clears the legacy `B3:E403` region (old headers + rows
  from pre-T4 tabs) and writes `B3:C...` RAW; creation writes the new grid
  whole. G:H and J:K geometry untouched; money format moves from E to C.

**Known risk carried**: the production probe proved field *names*, not that the
values are well-formed ISO 18245 codes for ING/Revolut. Every failure degrades
to an empty cell or `SIN CATEGORÍA`; it costs visibility, never a lost
transaction. The label table is deliberately partial: unmapped codes fall back
to the raw code instead of a guessed label.

## Risks carried forward

- **`fetch_transactions` sits exactly at the complexity ceiling (10)** — measured at 10 before
  this branch too, so the probe did not push it there. Any next change to that method must
  extract a helper rather than add a branch.
- The probe's `keys=` list includes `remittance_information` as a *name* while never logging its
  text. Harmless in a private log, worth stating if the run log ever becomes shareable output.
- Pagination that raises (auth, rate limit, `PaginationIncomplete`) emits no probe line, so a
  failed fetch is silent about fields rather than misleading.
