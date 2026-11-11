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

**Update 2026-11-10:** the key names are answered (see the T3 evidence below). The 14:10 UTC
production run reports both banks carrying `merchant_category_code`,
`bank_transaction_code`, `entry_reference`, `creditor`/`debtor`, `value_date` and
`balance_after_transaction`. What remains unverified is narrower and different: **whether
those keys carry a value** rather than `null` or `""`. A key present in the JSON is not a
populated field, and the probe logs names only by design.

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

### T4a — Measure whether the category field is actually populated

T3 answered the cheap half: the key names arrive. It cannot answer whether a value comes with
them, and widening `Transaction` on the assumption that it does would ship a column that is
empty for every row.

The measurement has to stay PII-free, so it cannot log a record. It logs one aggregate per
fetch, next to the existing probe: how many records carried a non-empty
`merchant_category_code` out of how many were seen, and the distinct codes themselves — MCC
values are ISO 18245 categories, not personal data, unlike every other field in the record.

Same reasoning as T3 for the level: `INFO`, one line per fetch, because the Actions log is
where the answer has to be readable. Test-first.

### T4b — Grouping (conditional, blocked on T4a evidence)

Only if T4a shows the values arrive: widen `Transaction` with `merchant_category_code`,
`entry_reference` and the counterparty name, carry them through the writer, and expose a
grouping that the expenses tab can use. Not planned in detail until the measurement exists.
If the codes come back empty or absent, the grouping has to be derived from the counterparty
and the description instead, which is a different design.

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

### T3 — answer received in production run `42831483339` (2026-11-10)

The probe reported from the 14:10 UTC cron run on `main`, over 26 ING records and 1 Revolut
record:

```text
Connector ING España: transaction fields, records=26, keys=balance_after_transaction,bank_transaction_code,booking_date,...,merchant_category_code,entry_reference,creditor,debtor,...
Connector Revolut:    transaction fields, records=1,  keys=balance_after_transaction,bank_transaction_code,booking_date,...,merchant_category_code,entry_reference,creditor,debtor,...
```

Both banks send the whole documented set; `transaction_id` is there too, still unusable as an
id. This closes the question T3 was built for and opens T4a: the probe proves key names, not
values, so the populated-count measurement is the next step.

### T4a — closed in `231587b`

RED observed before GREEN, over the probe line T3 already produced:

```text
AssertionError: Connector Fake Bank: transaction fields, records=2, keys=booking_date,credit_debit_indicator,merchant_category_code,remittance_information,status,transaction_amount
E  assert 'mcc_populated=1/2' in '... keys=... merchant_category_code ...'
7 failed, 39 deselected
```

The line now carries the answer next to the field names it already logged:

```text
Connector ING España: transaction fields, records=26, keys=..., mcc_populated=N/26, mcc_codes=5411,5812
```

- `_FieldProbe` owns the aggregate; `observe` is the only place that touches a raw
  record, so the value boundary lives in one spot instead of inline in
  `fetch_transactions` (which was at the complexity ceiling before this change).
- `_merchant_category_code` accepts only a non-empty string. Five tests: the populated
  count, the four unusable values (`absent`, `null`, `empty`, `whitespace-only`), distinct
  codes sorted, records discarded by `status` still counted (`2/2` with one surviving
  movement), and a non-string `5812` not guessed at.
- Every seen record counts, including the ones later dropped by status, date or parse:
  a field can arrive on a movement that is still discarded, which is the case the probe
  exists to reveal.
- Values stay out: the existing leak assertions still pass, and the only data reaching
  the log beyond key names is the MCC itself.

**What this does not prove:** whether the production payload carries a value. The five
new tests prove the measurement is correct, not that the banks populate the field. One
`sync.yml` run answers it at zero extra PSD2 cost, because the aggregate rides on the
fetch that already happens. Nothing in T4b is authorized until that line is read.

## Risks carried forward

- **`fetch_transactions` sits exactly at the complexity ceiling (10)** — measured at 10 before
  this branch too, so the probe did not push it there. T4a moved the aggregate into
  `_FieldProbe` instead of adding counters inline. Any next change to that method must
  extract a helper rather than add a branch.
- The probe's `keys=` list includes `remittance_information` as a *name* while never logging its
  text, and since T4a the line also carries the MCC values themselves. Harmless in a private
  log — an ISO 18245 category is not personal data — but worth stating if the run log ever
  becomes shareable output.
- Pagination that raises (auth, rate limit, `PaginationIncomplete`) emits no probe line, so a
  failed fetch is silent about fields rather than misleading.
