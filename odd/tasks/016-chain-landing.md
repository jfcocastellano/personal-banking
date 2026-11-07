# 016 chain landing

Goal: land feature 016 (single daily pass) on `main` through its three review slices, without
re-reviewing or re-writing the code that already passed 334 unit tests and one real production run
(`42267975079`).

## Current state (verified 2026-11-07, chain closed)

All three slices are on `main` and the chain is closed:

- `origin/main` = `012d45c`. Slice 1 `ca23ddf` (PR #23), slice 2 `d723eb3` (PR #26, tree
  `483d317f` = the reviewed `8b8556f`), slice 3 `0e1f848` (PR #25, tree `d18eeccd` = the reviewed
  `fde51a4`, native review approved on `review-c6f1e6057ace1bd7`), T022 close `012d45c` (PR #27).
- Production evidence: run [`42366404900`], `workflow_dispatch` on `main`, `success` in 36 s,
  2/4 banks, 13 movements, 13 layout rows.
- Historical detail kept below for audit: the wrong-base PR #24 and the stale PR #25 base.

## Historical state (2026-11-07, before the fix)
- PR #24 was **closed by merging into the wrong base**: `origin/016-p1-foundation` = `d004447`,
  1 commit on top of `25a3604`, tree `483d317f` identical to `8b8556f` (slice 2 content).
- PR #25 is open: head `fde51a4` (`016-p3-docs-fixes`), base `016-p2-cli-workflow` (`8b8556f`).
- Slice 2 content (`d004447`) is correct and safe; only its target branch is wrong.
- Local `main` was 1 commit behind `origin/main`; fast-forwarded.

## Tasks

- [x] T1 — Land slice 2 on `main` with a tight diff. Done: the raw branch would have shown 17
      files / 2.694 lines because the slice-1 squash (`ca23ddf`) left the original commits out of
      history, so slice 2 was re-applied onto `main` as `9d520d8` (tree `483d317f…`, identical to the
      reviewed `8b8556f`), pushed as `016-p2-slice-to-main`. Evidence: PR #26
      (https://github.com/jfcocastellano/personal-banking/pull/26), base `main`, 7 files / +816 / -7,
      CI `ci` completed success, gates `328 passed` + ruff + format + mypy green. Merged into `main`
      as `d723eb3` (tree `483d317f`, confirmed with `git rev-parse origin/main^{tree}`).
- [x] T2 — Rebased `016-p3-docs-fixes` onto `main` and retargeted PR #25. Done:
      `git rebase --onto origin/main 8b8556f 016-p3-docs-fixes` replayed the five slice-3 commits
      (`da0a6ce`, `7904da1`, `3e006c9`, `ad4af11`, `ab7378e`) conflict-free because `8b8556f` and
      `d723eb3` share tree `483d317f`; the rebased tree is `2bc40971…`, identical to the previously
      verified `fde51a4`. Published with `git push --force-with-lease` executed by the human, because
      the harness safety policy blocks that flag even under the AGENTS.md grant. PR #25 now reads
      base `main`, head `ab7378e`, 17 files / +595 / -44, `mergeable_state: clean`.
      Ops note: `pr update 25 --base main` fails with HTTP 400 "Body should be a JSON object" (helper
      bug); `/usr/bin/gh pr edit 25 --base main` works.
- [x] T3 — Ran `gh workflow run sync.yml --ref main` on the merged `main`. Done: run
      [`42366404900`] (`workflow_dispatch`, `head_sha=0e1f848`) finished `success` in 36 s with
      «Pasada diaria completada: 2/4 bancos — 13 movimientos en la pestaña 2026-11 y 13 filas en la
      pestaña 2026-11 Gastos (8.99s)»; MyInvestor and Banco Sabadell skipped as quiet state (no PSD2
      session). Evidence recorded in `docs/context.md` § *Despliegue y operación (IT7)* and T022 of
      `specs/007-scheduler-github-actions/tasks.md` closed, delivered through PR #27 and merged as
      `012d45c`. Note: today's delayed scheduled run may still fire a second pass on the same PSD2
      quota day, because GitHub landed the `0 6 * * *` cron 6.5–8.5 h late on every observed day.

[`42366404900`]: https://github.com/jfcocastellano/personal-banking/actions/runs/42366404900

## Recorded defect outside this chain

Native review lineage `review-74be087fe6327774` is stranded in `correction_required` because of
`R4-STALE-SUMMARY` (CRITICAL, lens `review-resilience`). The finding is a false positive against the
frozen candidate tree `483d317f`: it claims an `if not transactions:` guard at
`src/banking/sheets/layout.py:455-458` that skips `_write_summary_region`, but that call is
unconditional on the existing-tab path (`layout.py:570-571`) and two tests cover the exact case
(`test_empty_month_still_refreshes_the_panel`, `test_second_run_drops_stale_expense_rows_and_handles_an_empty_month`).
No code change was made for it, and none should be.
