# 016 summary JSON: decouple the workflow summary from log text

Goal: stop the scheduled workflow from scraping `banking.daily`'s log prose to build its run
summary, without changing the human-facing output of `banking daily` or its exit codes.

## Why

The workflow currently takes the run summary from four `grep`s over the process output:

- `grep -m1 '^Pasada diaria'` for the headline (human prose).
- three `grep -c` over `Daily pass skipped stage: … stage=transactions`,
  `Daily pass stage failed: … stage=transactions` and `… stage=balance`.

Nothing links those patterns to the Python log format strings, so renaming a log line silently
turns the production summary into `0`s. `tests/unit/test_sync_workflow.py` only asserts that the
strings appear in the workflow, which is the coupling, not a guard.

## Decision (2026-11-07)

`banking daily` gains an optional `--summary-json PATH`. When the flag is absent, the command
prints exactly what it prints today and writes no file. When present, it writes one JSON document
that carries both the structured values and the exact human headline, so the workflow reads fields
instead of parsing prose. The flag is a presentation option, not a month parameter: the month is
still the execution month.

The file is written on every terminal path with the FINAL exit code, including the two failure
paths, because the workflow publishes the summary even when the process fails. A write failure only
logs a warning: it must never change the exit code.

## Payload schema (`banking.summary/v1`)

```json
{
  "schema": "banking.summary/v1",
  "date": "2026-11-07",
  "status": "full_success",
  "exit_code": 0,
  "raw_tab": "2026-11",
  "layout_tab": "2026-11 Gastos",
  "headline": "Pasada diaria completada: 2/4 bancos — 13 movimientos en la pestaña 2026-11 y 13 filas en la pestaña 2026-11 Gastos (8.99s)",
  "banks_total": 4,
  "banks_succeeded": 2,
  "banks_not_onboarded": 2,
  "banks_failed": 0,
  "balance_failures": 0,
  "rows_written": 13,
  "expense_count": 13,
  "balance_count": 4,
  "duration_seconds": 8.99,
  "sheets_error": null,
  "not_onboarded_banks": ["MyInvestor", "Banco Sabadell"],
  "banks": [
    {
      "bank": "ING",
      "not_onboarded": false,
      "transactions": 5,
      "balance_reported": true,
      "transactions_failure": null,
      "balance_failure": null
    }
  ]
}
```

`status` is the lowercased `OverallStatus` for a completed run (`full_success`,
`partial_failure`, `nothing_to_sync`) and `total_failure` / `sheets_failure` for the two failure
paths. `headline` is the exact line the command printed on stdout (the summary line, or the
`ERROR:` line on failure), so the workflow still copies a string the process authored.

## Tasks

- [x] T1 — `--summary-json PATH` writes the payload on the success and nothing-to-sync paths,
      atomically, leaving stdout byte-identical when compared with a run without the flag (test
      first: the test asserting the file exists is RED before the flag). `f907a89`: RED was
      `SystemExit: 2 — unrecognized arguments: --summary-json`; `src/banking/summary_file.py` is new.
- [x] T2 — The payload is also written on the total-failure and Sheets-failure paths, carrying the
      FINAL exit code (including `4` when the notification delivery failed), and a write failure
      degrades to a stderr warning without touching the exit code. `f907a89`: four terminal paths,
      one write each; the layout-stage `raw_tab` defect and the `4` on a partial run were found by
      verification and fixed before the commit.
- [x] T3 — `sync.yml` reads the JSON instead of grepping `Daily pass skipped stage:` /
      `Daily pass stage failed:`, degrading gracefully when the file is absent (process died before
      writing it). `655544e`: the step-4 script was extracted from the YAML and exercised locally
      with a missing file, a malformed document and a valid one; all three published the summary
      with exit 0.
- [x] T4 — Update `specs/007-scheduler-github-actions/contracts/sync-workflow.md` §5.2, the 016 spec
      note that `daily` takes no arguments, `docs/context.md` and `specs/016-.../tasks.md`.
      `6ad41b2`: also the stale invariant #7 of the same contract (the job still said
      `python -m banking sync`) and the roadmap wording.
- [x] T5 — Gates (`pytest`, `ruff check`, `ruff format --check`, `mypy src/`, workflow YAML parses)
      and a ready PR. `a1b978c` pushed as PR #31: `349 passed`, ruff clean, 54 files formatted,
      mypy 25 files, `sync.yml` parses, CI green; native review `review-647e65c9f7587a3d`
      (high, 4 lenses, 12 files / 897 lines) approved with zero findings and the
      acknowledgement burned.

## Out of scope

- Changing the human-facing summary text, the per-bank report or any exit code.
- Publishing the JSON as a workflow artifact, or keeping it across runs.
- The `grep` that selects the illustrative log excerpt for the step summary; it stays, but it is no
  longer a data source and already degrades to `tail -n 20` when it matches nothing.
