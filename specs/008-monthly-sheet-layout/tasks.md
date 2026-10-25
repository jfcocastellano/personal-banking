# Tasks: Monthly accounting sheet layout

Contract: `spec.md`. Design: `plan.md`. Each task closes with a commit on `008-monthly-sheet-layout`.

## T001 — Ignore local drop files

Add `.orca/` to `.gitignore` so a user-supplied financial export cannot be committed by accident.

**Acceptance**: `git status --porcelain` no longer reports `.orca/`; `git check-ignore -v .orca/drops/x.xlsx` matches the new rule.

## T002 — Balance capability in the Enable Banking connector

Add `Balance` (amount, currency, balance_type, reference_date), a parser for `GET /accounts/{id}/balances`, the documented preference order, and `fetch_balance()` returning `Balance | None` for the session's account.

**Acceptance**: unit tests cover the preference order, an unknown type falling back to the first parseable entry, an empty list returning `None`, a malformed amount being skipped, and a missing `reference_date`.

## T003 — Pure layout grid builder

Add `src/banking/sheets/layout.py` with the category catalogue, geometry constants derived from `len(CATEGORIES)`, and a pure builder returning the full cell grid for a month.

**Acceptance**: tests assert block coordinates from the spec, deterministic ordering (date then bank), the four expense columns with no currency, the catalogue order, the formula strings, the 400-row ceiling raising instead of truncating, and an empty month still yielding headers plus formulas.

## T004 — Layout writer with region-preserving update

Add `LayoutWriter` that creates the tab when missing and otherwise rewrites only `B4:E…`, leaving `G:H` and `J:K` untouched.

**Acceptance**: a fake worksheet proves creation writes every block, a second run touches only the expense region, and a hand-typed shared amount is still present afterwards.

## T005 — `layout` command

Add `src/banking/cli/layout.py` with `--month YYYY-MM`, register it in `__main__.py`, fetch transactions and balances per bank with the existing isolation, print a per-bank report, and exit non-zero only on layout failure.

**Acceptance**: command appears in usage output; `--month` validation rejects malformed input; a bank failing on balances still produces the layout and reports the failure; tests cover dispatch and exit codes.

## T006 — Documentation

Document the command, the two-tab model, the four-column block, the balance limitation (PSD2 reports the balance at request time, no month-end history) and the fact that hand edits inside the expense block are overwritten.

**Acceptance**: `specs/008-monthly-sheet-layout/quickstart.md` explains the command and the limitation, and the root `quickstart.md` points to it; the spec's out-of-scope items are stated as user-facing limitations, not as omissions.

## T007 — Verification

Run the unit suite, `ruff check src tests` and `mypy src`; then generate a layout tab against the real document for a month with data and confirm the three blocks plus survival of a hand-typed amount across a rerun.

**Acceptance**: suite green, lint and types clean; manual confirmation recorded here with the tab name used.

---

## Appendix — category catalogue, verbatim from the reference worksheet

Rows `G4:G52` of the reference sheet, top to bottom. `      Día` rows are placeholder rows for day-dependent shared expenses and are kept as `Día` with whitespace trimmed. Seven of the 49 rows are these placeholders.

```
Alimentación
Mercadona
Consum
Otros
Entradas
Farmacia
Garaje Mossen Fenollar
Recibos C.P
Gatos
Petsitter
Día
Día
Día
Veterinario
Zooplus
Piso
Agua
Gas
Limpieza
Día
Día
Día
Día
Luz
Menaje
Regalos
Restauración
Streaming
HBO
Spotify
Tintorería
Transporte
AVE día
AVE día
AVE día
Motos alquiler
Taxi
VTC
Coche
Gasolina día
Gasolina día
Gasolina día
Gasolina día
Lavado
Parking
Peajes
Taller
Viajes
*Otros
```
