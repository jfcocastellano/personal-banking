# Tasks: Pasada diaria única (crudo + layout)

Contract: `spec.md`. Design: `plan.md`. Cada tarea cierra con un commit en `016-single-daily-pass`.

## T001 — `run_daily`: consulta única por cuenta

Crear `src/banking/daily.py` con `BankRun` (movimientos, saldo, fallo por etapa, `not_onboarded`) y el loop de consulta por banco: `fetch_transactions` una vez, `fetch_balance` una vez, cada etapa aislada.

**Acceptance**: tests cubren que cada banco recibe exactamente una llamada a `fetch_transactions` y una a `fetch_balance`; un fallo de saldo no descarta los movimientos del banco; un fallo de movimientos no descarta el saldo; `BankNotOnboardedError` marca `not_onboarded` en cualquier etapa sin registrar ERROR; `fetch_balance` devolviendo `None` no es fallo.

## T002 — Clasificación, guardas y escritura de las dos pestañas

Completar `run_daily`: `DailySummary`, clasificación con la semántica de `sync` (incluido `NOTHING_TO_SYNC`), guardas antes de leer `GOOGLE_SHEET_ID`, escritura cruda con `SheetsWriter` y de layout con `LayoutWriter` usando el mismo conjunto de movimientos.

**Acceptance**: con todos los bancos sin sesión no se instancia ningún writer ni se lee el secreto (test con `_ExplodingWriter`); con todos los bancos con error se lanza `AllBanksFailedError` sin escribir; un banco exitoso más uno fallido escribe ambas pestañas y clasifica `PARTIAL_FAILURE`; las filas del layout y del crudo son el mismo conjunto; una excepción del `LayoutWriter` se traduce a `SheetsSyncError`.

## T003 — Refresco del panel de saldos en pestaña existente

Agregar `_write_summary_region` a `src/banking/sheets/layout.py` y usarlo en el camino "pestaña existente", con `USER_ENTERED` para que las fórmulas evalúen.

**Acceptance**: una segunda corrida con saldos distintos cambia `J:K`; `G4:H52` y `H53` quedan intactos (mismo patrón que la prueba de supervivencia de 008); el rango escrito queda dentro de la fila final que dicta `build_month_grid`; un mes sin movimientos sigue refrescando el panel.

## T004 — Comando `banking daily`

Crear `src/banking/cli/daily.py` (`handle`, impresión por banco con `SIN SESIÓN PSD2`, nota de saldos, correo, exit codes 0/1/2/3/4) y registrarlo en `src/banking/__main__.py` con su línea de usage.

**Acceptance**: el comando aparece en el usage; el parser no acepta argumentos; cada situación de la tabla de exit codes tiene su test; el correo se envía solo en fallo parcial/total o fallo de Sheets, y un fallo de entrega produce exit 4; `_classify` sin fallos no envía nada.

## T005 — Workflow diario

Cambiar el paso de ejecución de `.github/workflows/sync.yml` a `python -m banking daily` y ampliar el step summary con movimientos por pestaña, bancos sin sesión, fallos y duración.

**Acceptance**: los tests del workflow pinchan el comando nuevo; siguen verdes las guardas de secretos (14 declarados una vez, ninguno interpolado en `run:`); `layout.yml` sigue existiendo y sin cambios de disparador; permisos read-only y timeout intactos.

## T006 — Documentación

`docs/context.md` (tabla de comandos y exit codes de `daily` frente a `layout`), `specs/016-single-daily-pass/quickstart.md` y el `quickstart.md` raíz: qué corre a diario, qué queda manual y por qué el panel de saldos es una foto con fecha.

**Acceptance**: un lector nuevo entiende la diferencia entre los tres comandos sin leer código; la limitación de saldos (sin histórico) está declarada como limitación, no como omisión; el mes anterior no se reescribe y también está declarado.

## T007 — Verificación

Suite completa, `ruff check src tests`, `ruff format --check src tests`, `mypy src`; y una corrida real de `banking daily` contra la hoja real vía `workflow_dispatch`, confirmando que ambas pestañas del mes en curso avanzan y que `H` sobrevive.

**Acceptance**: gates verdes y corrida real registrada acá con el nombre de pestañas, el run id y el resultado observado.

---

## Registro de cierre

_(se completa al cerrar cada tarea: commit, gates y evidencia)_

### T001 — cerrada

- Commit: `feat(daily): collect one query per bank for the daily pass` (primer commit de la rama).
- RED observado: `ModuleNotFoundError: No module named 'banking.daily'` al correr `tests/unit/test_daily.py` antes de implementar.
- GREEN: `8 passed`; `ruff check` limpio; `ruff format --check` 2 archivos; `mypy src/banking/daily.py` sin issues.
- Decisión no fijada por la tarea: `not_onboarded` es pegajoso — si una etapa lanza `BankNotOnboardedError`, la marca queda aunque la otra etapa responda. Logs: `banking.daily` con `Daily pass skipped stage: ...` (INFO) y `Daily pass stage failed: ...` (ERROR).

### T002 — cerrada

- Commit: `feat(daily): classify the run and write both tabs from one fetch`.
- RED observado: `ImportError: cannot import name 'DailySheetsError' from 'banking.daily'` antes de implementar.
- GREEN: 305 tests unitarios (baseline 295, +10 nuevos); `ruff check`, `ruff format --check` y `mypy src` limpios.
- Enabling edits: `sync._transform` pasa a `transaction_rows` (mismo cuerpo, un call site), y `sheets/layout.py` gana `layout_tab_name`, que ahora usan los dos caminos — se eliminó el `_LAYOUT_TAB_SUFFIX` duplicado del CLI.
- Decisión fuera del brief: `DailySheetsError.stage` es `Literal["raw", "layout"]`; el fallo al resolver `GOOGLE_SHEET_ID` cae en `stage="raw"`, igual que en `run_sync`.
- Deuda declarada: `daily._total_failure_message` re-implementa el texto de `sync` (el original está tipado para `BankOutcome`); si cambia uno hay que cambiar el otro.
