# Implementation Plan: Monthly accounting sheet layout

**Feature**: `specs/008-monthly-sheet-layout/spec.md`
**Branch**: `008-monthly-sheet-layout`

## Technical context

Python 3.12, `gspread==6.2.1`, `httpx==0.28.1`, mypy `strict`, ruff (line length 100). Tests in `tests/unit/`. Four connectors (`IngConnector`, `RevolutConnector`, `MyInvestorConnector`, `SabadellConnector`) all subclass `EnableBankingConnector` and differ only by `BANK_NAME` and `_SESSION_ID_KEY`, so a balance capability added to the base class serves all four.

## Design decisions

### Two tabs, one writer each

`SheetsWriter.write()` clears the whole worksheet before writing, which is correct for a tab the system owns and wrong for a tab the human edits. Instead of teaching the existing writer about regions, the layout gets its own writer with its own contract:

| Tab | Owner | Overwrite semantics |
| --- | --- | --- |
| `YYYY-MM` | daily sync | full replace (unchanged) |
| `YYYY-MM Gastos` | layout command | create once; later runs rewrite only the individual-expenses block |

The daily sync never learns about the layout tab. That is what keeps hand-typed shared amounts safe: the risky writer is a separate class with a narrower contract, not the same code with a flag.

### Geometry

Column A stays empty as a spacer, reproducing the reference worksheet.

```
     B        C        D             E        |  G                        H    |  J             K
 2   └──────── GASTOS ────────┘              |  └── GASTOS COMUNES ──┘         |  └── INGRESOS ──┘
 3   FECHA    BANCO    DESCRIPCIÓN  IMPORTE  |  CATEGORÍA                 TOTAL |  CONCEPTO      IMPORTE
 4   …transactions…                         |  Alimentación                   |  Ingresos     =SUMIF
 …                                          |  …49 categories…                |  Gastos       =SUMIF
53                                          |  Total                     =SUM |  Total        =K4+K5
54                                          |                                 |  SALDO CUENTAS
```

- Individual expenses: `B4:E{3+n}`.
- Shared expenses: labels `G4:G52`, manual totals `H4:H52`, total row 53 `=SUM(H4:H52)`.
- Summary: `J4`/`K4` income, `J5`/`K5` expenses, `J6`/`K6` net.
- Balances panel starts at `J8`, ending with a total row and a reference-date row.

Formulas reference the amount column `$E$4:$E$403`, a 400-row ceiling for the block. The writer refuses to write beyond it rather than silently truncating.

### Formula set

| Cell | Formula | Why |
| --- | --- | --- |
| `K4` | `=SUMIF($E$4:$E$403,">0",$E$4:$E$403)` | income is every positive amount |
| `K5` | `=SUMIF($E$4:$E$403,"<0",$E$4:$E$403)` | expenses stay signed, as the banks report them |
| `K6` | `=K4+K5` | net result without re-signing anything |
| `H53` | `=SUM($H$4:$H$52)` | shared-expense total |

Signed amounts are kept everywhere: no `ABS`, no sign flipping. A negative amount is an expense in the source data, in the raw tab and in this block, so the summary can sum both columns without a translation layer.

### Balances

Enable Banking exposes `GET /accounts/{account_id}/balances`, returning a list of entries with `balance_amount.amount`, `balance_amount.currency`, `balance_type` and `reference_date`. One account per session is already resolved by `_resolve_account_id`.

Selection is deterministic through a preference order, first match wins:

```
CLBD (closing booked) > ITBD (interim booked) > CLAV > ITAV > OPBD > OPAV > FWAV > XPCD
```

Unknown or absent types fall back to the first parseable entry, so an unexpected provider vocabulary degrades to a value instead of an empty cell.

**Known limitation, stated in the output**: PSD2 reports the balance at request time. There is no month-end historical balance, so the panel is truthful only when the command runs on the month's last day. The panel therefore prints the bank's `reference_date` next to the values, and the docs say so. Daily snapshots belong to the scheduler feature.

### Failure isolation

Balances are fetched per bank in the same fixed order the sync uses, each inside its own `try`. A failure yields no balance for that bank, is logged, and is surfaced in the command's report; it never aborts the layout. This mirrors `_sync_one_bank`'s existing contract instead of inventing a second resilience model.

## Module layout

| File | Change |
| --- | --- |
| `src/banking/connectors/enable_banking.py` | `Balance` dataclass, `_parse_balance`, `_select_balance`, `fetch_balance()` |
| `src/banking/sheets/layout.py` | new: catalogue, geometry constants, pure grid builder, `LayoutWriter` |
| `src/banking/cli/layout.py` | new: `layout` command with `--month` |
| `src/banking/__main__.py` | register the command |
| `.gitignore` | ignore `.orca/` |
| `specs/008-monthly-sheet-layout/quickstart.md` | feature guide: command, two-tab model, balance limitation |
| `quickstart.md` (root) | short `IT8` section pointing at the feature guide |
| `tests/unit/test_balances.py` | parsing, preference order, no-balance case |
| `tests/unit/test_layout_grid.py` | grid geometry, ordering, formulas, empty month |
| `tests/unit/test_layout_writer.py` | create vs update, manual regions preserved |

The grid builder is a pure function of `(month, transactions, balances)` returning cells. Everything about Google Sheets lives in the writer, so the geometry is testable without a network or a spreadsheet.

## Risks

- **Region drift**: if the catalogue length changes, `H53`'s formula and the balances panel offsets move. Mitigation: geometry constants derive the offsets from `len(CATEGORIES)`; a test asserts the contract's absolute coordinates.
- **User hand-edits inside the transaction block**: they are overwritten by design, and the docs must say so plainly.
- **`reference_date` absent**: the panel prints the run date and labels it as such rather than pretending it is a bank-reported date.

## Verification

- Unit suite: `.venv/bin/python -m pytest tests/unit -q`
- Lint and types: `ruff check src tests`, `mypy src`
- Manual: generate a layout tab against the real document for a month with data, confirm the three blocks, confirm a hand-typed shared amount survives a rerun.
