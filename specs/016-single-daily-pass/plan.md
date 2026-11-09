# Implementation Plan: Pasada diaria única (crudo + layout)

**Branch**: `016-single-daily-pass` | **Date**: 2026-11-04 | **Spec**: [spec.md](./spec.md)

## Summary

Agregar un comando `banking daily` que hace en una sola pasada lo que hoy hacen dos procesos separados: consulta Enable Banking una vez por etapa (movimientos + saldo), escribe la pestaña cruda `YYYY-MM` con `SheetsWriter` y la pestaña `YYYY-MM Gastos` con `LayoutWriter`, y refresca el panel de saldos/resumen de la pestaña de layout existente sin tocar `G:H`.

`sync` y `layout` no cambian. El workflow diario pasa a ejecutar `daily`.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: `httpx` (Enable Banking), `gspread` (Sheets), `PyJWT`/`cryptography` (firma y secretos), `smtplib` (correo). Sin dependencias nuevas.

**Storage**: Google Sheets (dos pestañas por mes) y `SecretStore` cifrado en `.env` / GitHub Secrets. Sin base de datos (Principio VII).

**Testing**: `pytest` + `pytest-mock`; APIs externas mockeadas (Principio III).

**Target Platform**: CLI en GitHub Actions (ubuntu-latest) y local.

**Project Type**: CLI batch / integración de datos.

**Constraints**:
- 2 llamadas de datos PSD2 por cuenta y corrida (movimientos + saldo) y una sola consulta de sesión, así que son 3 GET por cuenta más paginación. Con el límite de 4/cuenta/día queda 1 GET de margen; si la consulta de sesión cuenta contra ese límite no está verificado.
- Sin lógica de negocio en el YAML del workflow.
- Toda función pública con anotaciones completas y `mypy` estricto (Principio VI).

**Scale/Scope**: 4 bancos, ≤400 movimientos por mes y pestaña.

## Constitution Check

*GATE: debe pasar antes de la fase de diseño y re-chequearse al final.*

- [x] Spec aprobado en `/specs/016-single-daily-pass/spec.md` (Principio I)
- [x] Ningún test planeado hace llamadas reales (Principio III)
- [x] Sin base de datos ni persistencia local nueva (Principio VII)
- [x] Secretos solo por GitHub Secrets o `.env` cifrado (Principio IV)
- [x] Aislamiento por banco y por etapa conservado (Principio V)
- [x] Anotaciones completas y complejidad ≤10, o justificada abajo (Principio VI)
- [x] Sin dependencias nuevas (Anti-patrón #10)

## Diseño

### Módulos

```
src/banking/daily.py          # dominio: run_daily, BankRun, DailySummary, clasificación
src/banking/cli/daily.py      # presentación: argparse, impresión, exit codes, correo
src/banking/sheets/layout.py  # + refresco region-preserving del panel J:K
src/banking/__main__.py       # registro del subcomando
.github/workflows/sync.yml    # python -m banking daily
```

`daily.py` **reutiliza** de `sync.py`: `_CONNECTOR_CLASSES`, `OverallStatus`, `BankNotOnboardedError` y las excepciones `AllBanksFailedError`/`SheetsSyncError` con su contexto. No importa `BankOutcome` porque el resultado por banco necesita además movimientos y saldo: `BankRun` es un tipo nuevo y `DailySummary` reemplaza a `SyncSummary`.

No se extrae una capa de fetch compartida con `layout`: `layout` es el camino manual de backfill y su contrato de tests queda intacto (FR-003). La duplicación del loop se acepta y se documenta; unificarla es trabajo de una feature posterior si el costo aparece.

### Flujo de `run_daily`

1. `today` (inyectable, default `date.today()`), `month_start = today.replace(day=1)`, `raw_tab = "%Y-%m"`, `layout_tab = "%Y-%m Gastos"`.
2. Construir conectores (`connectors or [cls() for cls in _CONNECTOR_CLASSES]`); lista vacía → `NoConnectorsError` (reuso de `sync.py`).
3. Por banco, en su propio `try` por etapa:
   - `fetch_transactions(month_start, today)` → `BankRun.transactions` o `transactions_failure`.
   - `fetch_balance()` → `BankRun.balance` o `balance_failure` (`None` sin excepción no es fallo).
   - `BankNotOnboardedError` en cualquier etapa → `not_onboarded=True`, log INFO, sin correo.
4. Clasificar con la misma semántica de `sync`: sin fallos → `FULL_SUCCESS`; ninguno con movimientos y alguno con fallo → `TOTAL_FAILURE`; resto → `PARTIAL_FAILURE`; ninguno con movimientos y ninguno con fallo → `NOTHING_TO_SYNC`.
5. Guardas antes de tocar Sheets: `NOTHING_TO_SYNC` no lee `GOOGLE_SHEET_ID` ni construye writers; `TOTAL_FAILURE` lanza `AllBanksFailedError` con el contexto.
6. Escritura cruda: `SheetsWriter().write(document_id, raw_tab, headers, rows)` con los movimientos de todos los bancos que respondieron. Excepción → `SheetsSyncError`.
7. Escritura layout: `LayoutWriter().write(document_id, layout_tab, expense_rows, balances)` con el **mismo conjunto** de movimientos. Excepción → `LayoutWriteError` traducida a `SheetsSyncError` para que el CLI tenga un solo camino de exit 2.
8. `DailySummary` con runs, status, tabs, filas crudas escritas, duración.

### Cambio en `LayoutWriter` (FR-004, FR-005)

Hoy el camino "pestaña existente" solo limpia y reescribe `B4:E403` (`sheets/layout.py:435`). Se agrega `_write_summary_region(worksheet, balances)`:

- limpia `J4:K<última fila del resumen>` y reescribe la tabla de resumen + panel `SALDO CUENTAS` con `USER_ENTERED` (las fórmulas tienen que evaluarse).
- no abre rango sobre `G:H` ni sobre `F`; `H4:H52` y `H53` no se tocan.
- mantiene el orden de bancos y el formato del panel que ya produce `build_month_grid`, para que la creación y el refresco no diverjan.

El límite superior del rango sale de `build_month_grid` (la geometría es la única fuente de verdad, como ya establece la feature 008).

### CLI y exit codes (FR-009)

`banking daily`, sin parámetro de mes: su única opción (`--summary-json PATH`, añadida después para que el workflow no re-parseara los logs) no cambia qué imprime ni qué escribe. Tabla idéntica a `sync`:

| Situación | Exit |
| --- | --- |
| Éxito completo, o todos los bancos sin sesión (nada que sincronizar) | 0 |
| Fallo total (ningún banco con movimientos, alguno con error real) | 1 |
| Fallo de escritura en Sheets (crudo o layout) | 2 |
| Fallo parcial con al menos un banco exitoso | 3 |
| Fallo parcial/total y el correo no se pudo entregar | 4 |

La notificación reutiliza `EmailNotifier` y la construcción de cuerpo de `cli/sync.py`, con los conteos extendidos a las dos pestañas.

### Workflow (FR-010, FR-011)

`sync.yml`: el paso `Ejecutar sincronización` pasa a `python -m banking daily`; el resto del andamiaje (validación de los 14 secretos, provisionamiento, `PIPESTATUS[0]`, step summary, propagación del exit code) se conserva. `layout.yml` no se toca: sigue siendo el backfill manual por mes.

### Test-First por tarea (Principio II)

Cada tarea arranca con el test que falla:

| Tarea | RED observable |
| --- | --- |
| T001 | `run_daily` no existe / no consulta saldo / no aísla etapas |
| T002 | clasificación y guardas sin efecto (escribe con 0 bancos) |
| T003 | segunda corrida no cambia `J:K` |
| T004 | `banking daily` no está registrado en el usage |
| T005 | el workflow sigue diciendo `banking sync` |

## Estructura de archivos a tocar

| Archivo | Acción |
| --- | --- |
| `src/banking/daily.py` | nuevo |
| `src/banking/cli/daily.py` | nuevo |
| `src/banking/__main__.py` | registrar subcomando + usage |
| `src/banking/sheets/layout.py` | `_write_summary_region` + uso en el camino existente |
| `tests/unit/test_daily.py` | nuevo |
| `tests/unit/test_cli_daily.py` | nuevo |
| `tests/unit/test_layout_writer.py` | + casos de refresco del panel |
| `tests/unit/test_sync_workflow.py` | comando y summary del workflow |
| `tests/unit/test_main.py` | registro del subcomando |
| `.github/workflows/sync.yml` | comando del paso + summary |
| `docs/context.md` | tabla de comandos y exit codes |
| `quickstart.md` | cómo se comporta la pasada diaria |

## Complexity Tracking

| Decisión | Justificación |
| --- | --- |
| `BankRun` en lugar de reutilizar `BankOutcome` | `BankOutcome` no puede transportar movimientos ni saldo; extenderlo obligaría a cambiar `sync` y sus ~30 tests (viola FR-003). |
| Duplicar el loop de fetch de `cli/layout.py` | Extraer una capa común obliga a tocar el camino manual y su contrato, sin valor inmediato; se documenta como deuda explícita. |
| `_write_summary_region` dentro de `LayoutWriter` | La geometría del panel ya vive ahí; ubicarlo afuera duplicaría las coordenadas. |
