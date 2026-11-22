# 021 — One tab per month: the movements tab absorbs the raw tab

Status: in progress — decisions answered (D1-D4 below), implementation pending.

## Why

Owner direction (2026-11-18, verbatim): «como no podemos recuperar las categorias no
podemos agrupar los gastos, con lo cual solo vamos a recuperar los movimientos. La
pestaña de 2026-11, donde se listan solo movimientos, la podemos descartar y dejar solo
la de 2026-11 Gastos, donde ya se incluyen los movimientos y la parte de gastos comunes
y totales, que la rellenaré yo manualmente».

The premise held: #34 added a `Categoría` column and a category-sums block on the
strength of `merchant_category_code`, and #37 (`16022f3`) reverted both because the
codes are not usable. `src/banking/categories.py` no longer exists; `layout.py` keeps
`_EXPENSE_HEADERS = ("FECHA", "BANCO", "DESCRIPCIÓN", "IMPORTE")`. With grouping gone,
the raw tab is pure duplication of the movements the other tab already carries.

## Diagnosis (verified, not assumed)

The surviving tab is already a superset of everything except one column:

| Region | Content | Written by |
| --- | --- | --- |
| `B3:E403` | every transaction of every bank, incomes included | `layout._place_expenses` |
| `G:H` | household common expenses, manual catalogue | nobody (owner, by hand) |
| `J:K` | Ingresos / Gastos / Total via `SUMIF` over its own `E` | formulas (`layout.py:161-162`) |
| row 8+ | per-bank balance panel | `layout._place_balances` |

The raw tab (`sync.py:29`, five columns `Fecha de liquidación, Banco, Descripción,
Importe, Divisa`) contributes exactly one field the layout tab does not: **Divisa**.
Everything else it holds, `B3:E403` already holds.

`run_daily` (`src/banking/daily.py:340-395`) writes both tabs sequentially from one
fetch, each with its own `DailySheetsError(stage="raw"|"layout")`, and reports
`total_rows_written` from the *raw* row count while `expense_count` counts the layout
rows — two numbers that are the same list today.

## Decisions (answered by the owner, 2026-11-18)

- **D1 — Divisa: dropped.** The layout tab keeps its four columns
  `FECHA | BANCO | DESCRIPCIÓN | IMPORTE`, `_EXPENSE_HEADERS`, `_EXPENSE_REGION`
  (`B3:E403`) and `_AMOUNT_RANGE` are untouched. Currency stops being recorded in the
  document. `Transaction.currency` stays in the model: it is not this task's job.
- **D2 — Existing raw tabs: the owner deletes them by hand.** No code deletes, moves or
  renames production data. The process simply stops writing `<YYYY-MM>`.
- **D3 — `banking sync`: deferred, not decided.** `sync` stays exactly as it is and the
  task is opened as `022` once the single-tab month is verified in production. Deleting
  it is a larger unit (its own writer path, its own exit codes, its own tests) and
  bundling it here would make neither change reviewable. What this task does do is mark
  it **legacy** in `docs/context.md` so it stops reading as a supported path.
- **D4 — Tab name: renamed to `<YYYY-MM>`.** `_LAYOUT_TAB_SUFFIX = " Gastos"`
  (`layout.py:175`) disappears; `layout_tab_name` returns `strftime("%Y-%m")`. The
  owner migrates the existing month by hand: rename `2026-11 Gastos` → `2026-11`.

### D4 opens a deployment hazard that the code has to guard

Until the owner renames by hand, the tab `2026-11` exists **and holds the raw grid**
(five columns, `Fecha de liquidación…`). With the suffix gone, `LayoutWriter` resolves
`2026-11` as its target and would clear `B3:E403` and write a layout grid over raw data.
That is silent data loss on the first run after deploy, and it is the one failure the
migration order cannot be trusted to prevent.

So the guard ships with this task: before clearing or writing, the layout writer must
refuse a tab whose existing `B3:E` headers are the raw ones, and fail loudly with the
migration instruction instead of writing. Which means the guard has to land **before or
with** the rename, never after.

## Scope (conditional on the decisions above)

- **S1** — `layout.py`: `_LAYOUT_TAB_SUFFIX` and the suffix arithmetic in
  `layout_tab_name` are removed, so the layout tab is `<YYYY-MM>`. Column shape does not
  change (D1).
- **S2** — `daily.py`: drop the raw write block, `raw_tab_name`, `stage="raw"` and
  `NoBankFetchedError.raw_tab_name`. One writer, one tab, one failure stage.
- **S3** — Counts collapse: `DailySummary.total_rows_written` becomes the movements
  count, `expense_count` is removed or kept only if it stops duplicating. Whatever the
  choice, `banking.summary/v1` (`src/banking/summary_file.py`) and the summary step in
  `.github/workflows/sync.yml` must change **in the same commit**: the workflow step
  degrades to zeros when it reads a field it does not find, so a split change is silent.
- **S3b** — The raw-header guard from the D4 hazard: `LayoutWriter.write` reads the
  target tab's `B3:E` headers when the tab already exists and raises a dedicated, named
  error (message naming the migration step) if they are `sync._HEADERS`. Test-first,
  both ways: the raw headers are refused, the layout headers are accepted.
- **S4** — `sync.py`: untouched (D3 deferred). It keeps `_HEADERS` and
  `transaction_rows_for_banks`; `docs/context.md` marks it legacy.
- **S5** — Tests: the raw-stage cases in `tests/unit/test_daily.py`, the raw counts in
  `test_summary_file.py`, the workflow assertions in `test_sync_workflow.py`, and the
  end-to-end path. RED first, over the new single-tab contract.
- **S6** — Docs: `docs/context.md` (estado actual, tabla de iteraciones, la sección de
  despliegue y operación con el resumen JSON), `quickstart.md` (IT7/IT8),
  `specs/016-single-daily-pass/` marked as superseded where it describes two tabs, and
  the 017 entry noting that #37 reverted T4 and this task supersedes T2/S3.
- **S7** — Hygiene: `src/banking/__pycache__/categories.cpython-312.pyc` is orphaned
  bytecode from a module deleted in #37. Remove it and confirm `__pycache__` is
  ignored, not tracked.

## Out of scope

- Recovering categories by any other route (counterparty, `bank_transaction_code`,
  `entry_reference`). #37 closed that door; reopening it is a new task with its own
  evidence.
- The `G:H` manual catalogue and the `J:K` formulas: the owner fills and owns them.
- The GitHub cron lag (`docs/context.md:46`): still an accepted risk.
- Deleting historical tabs as data migration beyond whatever D2 answers.

## Implementation progress (2026-11-18) — src migrated, tests pending

Landed in the working tree, **not committed**:

- `layout.py`: `_LAYOUT_TAB_SUFFIX` gone, `layout_tab_name` returns `<YYYY-MM>`,
  `RawTabCollisionError` + `_ensure_not_raw_tab` guard on the refresh path,
  `_RAW_HEADERS` duplicated with a test pinning it against `sync._HEADERS`.
- `daily.py`: one write. `DailySummary` is `(passes, overall_status, tab_name,
  total_rows_written, balance_count, duration_seconds)`; `NoBankFetchedError` carries
  `tab_name`; `run_daily` lost the `writer` parameter and the `stage="raw"` path;
  `WriteStage` is `Literal["layout"]`.
- `cli/daily.py`: both headlines name one tab and one count.
- `summary_file.py`: payload has `tab` instead of `raw_tab`/`layout_tab`, and no
  `expense_count`; `_layout_tab` folded into `_month_tab`; the sheets-failure document
  reports `rows_written=0` because nothing is written on that path now.

**Correction to S3 above:** the workflow summary step reads only
`banks_not_onboarded`, `banks_failed`, `balance_failures` and `headline` — never the tab
or count fields. So `.github/workflows/sync.yml` does **not** change, the payload keeps
`banking.summary/v1`, and this task needs no `workflow` token scope. Verified with a grep
over `.github/`.

Green: `tests/unit/test_layout_writer.py` (29 passed), including the guard.

Red, and this is the remaining work — every failure is the old two-tab contract, not a
src defect:

- `tests/unit/test_cli_daily.py` — collection error: `NoBankFetchedError(raw_tab_name=…)`.
  Also `layout_tab_name=`, `expense_count=`, the parameterised `stage`/tab matrix
  (lines 312-313, 397, 630, 672-673) and payload assertions (563, 591).
- `tests/unit/test_daily.py` — 12 failures: `writer=`/`raw_writer` kwargs, the
  `_ExplodingWriter`/`_RecordingWriter` raw-stage fakes, `raw_tab_name`/
  `layout_tab_name`/`expense_count` assertions, and the two tests whose subject no longer
  exists (`..._writes_both_tabs...`, `..._layout_failure_raises_after_the_raw_tab_was_written`,
  `..._writes_the_raw_tab_oldest_first_across_banks`, `..._raw_failure_raises_before_the_layout_writer_is_called`).
- `tests/unit/test_layout_cli.py` — 5 failures: the tests that pin "the layout never
  writes the plain month tab" now assert the inverse, since the layout owns that name.

Nothing is committed and nothing was pushed. The suite is red: **17 failed, 1 error,
337 passed** — do not commit this tree until those three test files are rewritten.

Docs (S6) and the stale `categories.cpython-312.pyc` cleanup (S7) are still open.

## Risks

- **One tab means one 400-row cap.** `MAX_EXPENSE_ROWS = 400` stopped being the second
  tab's limit and became the month's only limit. A month above 400 movements now has
  nowhere else to go.
- **The surviving tab sorts ascending** (`layout._sort_key`: date, bank, description),
  where the raw tab was newest-first. The 017 T2 ordering work now applies to the only
  tab there is; where the two disagreed, the survivor wins.
- **Silent summary degradation** if S3 lands without the workflow step (see S3).
- **D2 is the owner's hand-work, and it has a window**: from the deploy onward
  `<YYYY-MM>` stops being written, so until the owner deletes those tabs they freeze
  mid-month — and the guard in S3b turns a forgotten rename into a failed run rather
  than into overwritten raw data.
- No production evidence exists yet for a month written by this code path; the first
  real run is the only proof, as with every layout change so far.

## Second progress note — test rewrite in flight

Fixed since the note above:

- `src/banking/daily.py`: a leftover `tab_name=target_layout_tab` in the writer call (a
  real `NameError`, not a test problem) — the one-edit refactor had missed it.
- `tests/unit/test_cli_daily.py`: **25 passed.** Tabs collapsed to `payload["tab"]`,
  `expense_count` assertions dropped, and the parameterised sheets-failure test became
  `test_summary_json_names_the_failed_tab` with two cases: an explicit `tab_name` and the
  `None` fallback to the month. That is a small coverage gain, not a loss.
- `tests/unit/test_daily.py`: the full-success test is now
  `test_run_daily_full_success_writes_the_month_tab` (layout writer only, and the old
  raw-vs-layout cross-check became `total_rows_written == len(layout transactions)`).
  **Two tests were deleted** because their subject no longer exists — `..._raw_failure_
  raises_before_the_layout_writer_is_called` and `..._layout_failure_raises_after_the_raw_
  tab_was_written`: with a single write there is no ordering between two writes to test.

Still red (9): `test_daily.py` — `..._balance_failure_keeps_movements...` and
`..._writes_the_raw_tab_oldest_first_across_banks` (both still assert on `_RecordingWriter`
calls; the second is 017's ascending-order guarantee, which must be re-aimed at the layout
tab's sorted rows or at `sync.transaction_rows_for_banks` directly, since the raw write is
gone). `test_layout_cli.py` — 7 failures, all pinning the old naming: the tests that assert
"the layout never writes the plain month tab" now assert the inverse, plus the default-month
and report-count expectations.

Nothing committed. **Do not commit until these 9 are green.**

## Estado final

**376 passed**, `ruff` y `mypy` limpios. S1-S7 cerradas.

- Tests eliminados (sujeto desaparecido, sin equivalente): los dos de orden entre
  escrituras y `..._writes_the_raw_tab_oldest_first_across_banks`. El orden ascendente
  sigue cubierto por `test_layout_grid.py`, que prueba el grid del layout, y por
  `sync.transaction_rows_for_banks`, que conserva su contrato.
- `test_layout_cli.py`: `test_successful_run_writes_the_gastos_tab_and_never_the_plain_
  month_tab` pasa a `..._writes_the_month_tab`; la aserción negativa se invirtió.
- Docs: `README.md` (diagrama de una pestaña, cabecera del flujo), `docs/context.md`
  (tabla de comandos: `daily`/`layout` sobre `YYYY-MM`, `sync` marcado heredado),
  `docs/roadmap.md` (`<YYYY-MM>`).
- S7: borrado `src/banking/__pycache__/categories.cpython-312.pyc`.

Pendiente fuera de alcance: el renombrado a mano de `2026-11 Gastos` → `2026-11` y el
borrado de las pestañas crudas son del dueño (D2/D4). Hasta que renombre, el guard
`RawTabCollisionError` impide que el writer pise la pestaña cruda.
