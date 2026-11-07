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

### T003 — cerrada

- Commit: `fix(layout): refresh the summary and balance panel on an existing tab`.
- RED observado: 9 tests en rojo contra la implementación previa (`cleared == ['B4:E403', 'B4:E403']` frente a la lista con `J4:K19`, `panel_ranges == []`).
- GREEN: 310 tests unitarios; `ruff check`, `ruff format --check` y `mypy src` limpios.
- Región del panel: con N saldos, limpia `J4:Kmax(11+N, 19)`, escribe en `J4` con `USER_ENTERED` y formatea `K4:K<última>`. Nunca direcciona columnas A–I.
- Suelo fijo `_MAX_BALANCE_ROWS = 8`: un panel que se achica (cuenta dada de baja, banco sin sesión) no deja filas viejas.
- Test que cambió de contrato: `test_second_run_clears_only_the_expense_region_and_writes_only_expense_rows` pasa a `..._and_the_panel`; la supervivencia ahora se afirma sobre `G`/`H` (que ningún rango los mencione) en vez de sobre una celda de `J:K`, porque FR-004 reemplaza lo tipeado a mano en el panel.
- Deuda declarada: la creación formatea `K10:K<total>` y el refresco `K4:K<última>`, así que tras la primera pasada los totales de fórmula del resumen quedan con formato de euros. Cosmético y benigno; unificarlo requiere tocar `_apply_light_formatting` y su test.

### T004 — cerrada

- Commit: `feat(cli): add the banking daily subcommand`.
- RED observado: `ImportError: cannot import name 'daily' from 'banking.cli'` y, en `test_main`, `invalid choice: 'daily' (choose from 'secrets', 'sync', 'layout')`.
- GREEN: 327 tests unitarios; `ruff check`, `ruff format --check` y `mypy src` limpios; `banking --help` lista los cuatro subcomandos.
- Tabla de exit codes implementada: 0 éxito u omitida, 1 fallo total, 2 fallo de Sheets (dice la etapa), 3 parcial con aviso, 4 aviso no entregado.
- El aviso solo se construye en los caminos de fallo (`EmailNotifier` reusable de `cli/sync.py`); `BankPass` se adapta a `BankOutcome` para el notificador, que sigue sin cambios.
- Ronda de pulido: `handle` quedó con la firma de sus hermanos (`args: argparse.Namespace, notifier=None`); se borró el parser interno y el rechazo de flags se prueba ahora en `test_main` contra el parser real.
- Decisión fuera del brief: el `tab_name` del correo es el de la pestaña cruda, y la etapa fallida viaja en `sheets_error`.

### T005 — cerrada

- Commit: `ci(sync): run the daily pass and report both tabs in the summary`.
- RED observado: 3 tests en rojo, entre ellos `assert 'python -m banking daily' in ...python -m banking sync...`.
- GREEN: 328 tests unitarios (327 + 1 nuevo), guardas de secretos intactas (5 passed), YAML válido, `ruff`/`format`/`mypy` limpios.
- Paso de ejecución: `python -m banking daily 2>&1 | tee "$RUNNER_TEMP/sync-output.log"` con `PIPESTATUS[0]` sin cambios.
- Resumen: la cabecera `Pasada diaria ...` se copia entera (no se re-parsea prosa) y aporta bancos X/Y, movimientos por pestaña y duración; tres `grep -c` aportan bancos sin sesión, bancos con fallo y saldos con fallo.
- Acoplamiento aceptado y pinchado por test: los `grep` matchean las líneas de log de `banking.daily`; renombrarlas obliga a tocar `sync.yml`.
- Limitación conocida: en el camino `NOTHING_TO_SYNC` la cabecera no trae conteos porque no se escribió nada; es el comportamiento del comando, no del resumen.

### T006 — cerrada

- Commit: `docs(016): document the daily pass and its balance-panel consequences`.
- Sin RED aplicable: documentación pasiva, sin comportamiento ejecutable nuevo; verificación por `grep`, resolución de links y suite intacta (328 passed).
- `docs/context.md`: workflow que ejecuta `daily`, tabla de los tres comandos, tabla de exit codes compartida por `sync`/`daily` frente a la propia de `layout`, y la decisión de una sola lectura por banco por la cuota PSD2.
- `specs/016-single-daily-pass/quickstart.md`: nuevo, con qué refresca cada corrida, qué sobrevive de `G:H`, la limitación de saldo sin histórico y el cambio de mes.
- `quickstart.md` raíz: corregida la afirmación de que `J:K` se respeta, más una sección con el reemplazo de `sync` por `daily` en el workflow.
- `docs/roadmap.md`: iteración 8 con Definition of Done, dependencias y riesgos; candidatas no comprometidas (snapshot de saldos, categorización, N26, atomicidad del writer) marcadas explícitamente como no aceptadas.
- Fuera del brief, corregido por el padre: `specs/008-monthly-sheet-layout/quickstart.md` afirmaba que `J:K` se respeta, lo que T003 dejó falso.

### Correcciones post-verificación

- `6ca4e23` `fix(daily): name balance failures in the email and align panel formatting`: el correo ahora nombra el fallo de saldo de un banco que sí trajo movimientos (viaja como `saldo no disponible: <motivo>` y `notify._build_body` lo renderiza; los correos de `sync` quedan byte-idénticos), la creación y el refresco del panel comparten una sola definición de rango (`_summary_panel_range_last_row`), y se corrigió un comentario obsoleto sobre el sufijo duplicado.
- `docs(016): correct the PSD2 request accounting`: verificado en `enable_banking.py` que el conector resuelve la sesión con `GET /sessions/{session_id}` antes de **cada** etapa, así que una corrida son **4 GET por cuenta** más paginación, no 2. El margen frente al límite de 4/cuenta/día queda declarado **no verificado**. El argumento de la feature sobrevive mejorado: encadenar `sync` y `layout` habrían sido 6 GET y dos lecturas de movimientos.
- Deuda declarada que queda abierta: resolver la sesión una vez por corrida ahorraría 2 de esos 4 GET (registrado en los riesgos de IT8, no como parte de esta iteración).

### T007 — verificación

- Gates locales: `ruff check src tests` ✅, `ruff format --check src tests` (51 archivos) ✅, `mypy src` (22 archivos) ✅, `pytest tests/unit -q` → **333 passed** ✅, YAML de `.github/workflows` parseable ✅.
- `pip-audit`: **no se pudo correr localmente** (el venv de resolución aislada falla por `ensurepip` ausente en la imagen). Lo cubre CI (`.github/workflows/ci.yml:28`). Queda declarado como verificación pendiente de CI, no como verde local.
- Contratos revisados a mano: orden de los guards antes de leer el secreto y construir los writers; una lectura por banco y por etapa; `_write_summary_region` nunca toca `A`–`I`; el camino de creación conserva el grid completo, el refresco RAW de `B4:E403` y los merges de títulos; exit codes iguales a `sync`; workflow con los 14 secretos una sola vez y `PIPESTATUS[0]`.
- Hallazgos corregidos: `6ca4e23` y `efb5786`. Deuda declarada que sigue abierta: duplicación de `_notify_and_exit`/`_total_failure_message`/`_print_not_onboarded_note` entre `cli/sync.py` y `cli/daily.py`, `run_daily` repitiendo el esqueleto fetch→guard→write, y la resolución de sesión repetida por etapa.
- Pendiente real, fuera del alcance del harness: una corrida contra la hoja con secretos reales (`workflow_dispatch`) para registrar el nombre de las dos pestañas, el run id, que ambas avanzaron y que `G:H` sobrevivió.
