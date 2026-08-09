# Tareas: Pipeline de Sincronización ING → Google Sheets

**Entrada**: Documentos de diseño desde `specs/004-ing-sheets-sync/`

**Prerrequisitos**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Tests**: Los tests son **OBLIGATORIOS** según el Principio II (Test-First). Deben
escribirse antes del código de implementación y verificarse en fallo (Red) antes de
empezar cualquier implementación. El ciclo Red → Green → Refactor no es negociable.

**Organización**: US1 (P1) → US2 (P2) → US3 (P3). US2 verifica una propiedad
(idempotencia) que ya emerge del diseño sin estado de US1 — sus tests pueden
pasar en verde sin código nuevo; eso se documenta explícitamente, no se
fabrica una tarea de implementación artificial. US3 añade manejo de errores
y logging sobre los mismos dos puntos de integración que US1 ya construyó.

## Formato: `[ID] [P?] [Story] Descripción`

- **[P]**: Paralelizable — ficheros distintos, sin dependencia bloqueante
- **[Story]**: Etiqueta de historia de usuario (US1, US2, US3)
- Todas las rutas son relativas a la raíz del repositorio

---

## Fase 1: Setup (Inicialización del Proyecto)

**Propósito**: Inicialización de la funcionalidad.

Esta funcionalidad no añade ninguna dependencia de terceros ni ningún
directorio nuevo — `src/banking/cli/` y `tests/unit/` ya existen desde
IT1, y no hay librería nueva que pinear. No hay tareas de Fase 1.

---

## Fase 2: Foundational (Extensión mínima de `IngConnector`)

**Propósito**: Exponer el nombre del banco públicamente desde el conector
ING (IT2), prerrequisito compartido por la transformación (US1) y el
resumen (US1/US3).

**⚠️ CRÍTICO**: Ninguna historia de usuario puede empezar su implementación
hasta que esta fase esté completa.

- [X] T001 [P] Escribir test en fallo en `tests/unit/connectors/test_ing.py`: `IngConnector.BANK_NAME == "ING España"` (atributo de clase, no instancia)
- [X] T002 Implementar `IngConnector.BANK_NAME: str = _BANK_NAME` como atributo de clase en `src/banking/connectors/ing.py`, reutilizando la constante de módulo privada ya existente — sin tocar ninguna de las 3 llamadas de log internas que ya usan `_BANK_NAME`

**Checkpoint**: `IngConnector.BANK_NAME` disponible. Los 37 tests
preexistentes de `test_ing.py` siguen en verde.

---

## Fase 3: Historia de Usuario 1 — Ejecutar la sincronización con un solo comando (Prioridad: P1) 🎯 MVP

**Objetivo**: `python -m banking sync` obtiene los movimientos ING del mes
en curso, los transforma al esquema fijo de columnas, los escribe en la
pestaña `YYYY-MM`, e imprime un resumen (banco, filas, pestaña, duración).

**Prueba independiente**: Ejecutar `pytest tests/unit/test_sync.py
tests/unit/test_cli_sync.py -k US1` con `IngConnector`/`SheetsWriter`
mockeados; confirmar que `python -m banking sync --help` no falla con
"unknown command".

### Tests para la Historia de Usuario 1 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T007

> **NOTA: Escribir TODOS los tests de esta sección primero. Ejecutar
> `pytest` y confirmar que CADA test falla con `ImportError` (los módulos
> `sync.py`/`cli/sync.py` no existen todavía) antes de escribir ninguna
> implementación (Principio II).**

- [X] T003 [US1] Escribir tests en fallo para el camino feliz en `tests/unit/test_sync.py`: con `connector=Mock(spec=IngConnector)` cuyo `fetch_transactions` devuelve una lista conocida de `Transaction`, `writer=Mock(spec=SheetsWriter)`, `document_id="doc-id"` y `today=date(2026, 8, 15)` inyectados, `run_sync()` (1) llama a `connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 15))`; (2) llama a `writer.write(document_id="doc-id", tab_name="2026-08", headers=["Fecha de liquidación", "Banco", "Descripción", "Importe", "Divisa"], rows=[...])` con cada fila en el orden fijo, la fecha como ISO string, `IngConnector.BANK_NAME` como banco, y el importe convertido a `float`; (3) devuelve un `SyncResult` con `bank_name`, `tab_name == "2026-08"`, `rows_written == len(transactions)`; monkeypatchear `banking.sync.time.monotonic` con una secuencia controlada de dos valores (p. ej. `iter([100.0, 100.5])`) y afirmar `duration_seconds == 0.5` exacto — no contra el reloj real, para evitar un test intermitente en sistemas con resolución de reloj gruesa (mismo cuidado que IT3 aplicó en su test de duración)
- [X] T004 [US1] Escribir test en fallo en `tests/unit/test_sync.py`: cuando `connector.fetch_transactions` devuelve `[]`, `run_sync()` llama igualmente a `writer.write(..., rows=[])` y devuelve `SyncResult.rows_written == 0` — no lanza ningún error (FR-009)
- [X] T005 [P] [US1] Escribir test en fallo en `tests/unit/test_cli_sync.py`: `cli.sync.handle(args)`, con `run_sync` sustituido por un doble que devuelve un `SyncResult` conocido, imprime a **stdout** una línea que contiene el banco, el número de filas, la pestaña y la duración, y devuelve `0`
- [X] T006 [P] [US1] Escribir test en fallo en `tests/unit/test_main.py`: el subcomando `sync` está registrado en `_build_parser()` (no lanza `SystemExit` por comando desconocido) y aparece listado en el mensaje de uso impreso cuando `python -m banking` se invoca sin argumentos

### Implementación para la Historia de Usuario 1

- [X] T007 [US1] Implementar en `src/banking/sync.py`: `SyncResult` (dataclass congelado con `bank_name`, `rows_written`, `tab_name`, `duration_seconds`); excepciones `IngSyncError`, `SheetsSyncError` (planas, sin cuerpo todavía); constante `_HEADERS`; función privada `_transform(bank_name: str, transactions: list[Transaction]) -> list[list[CellValue]]` que convierte cada `Transaction` a `[booking_date.isoformat(), bank_name, description, float(amount), currency]` — fully type-annotated
- [X] T008 [US1] Implementar `run_sync(connector: IngConnector | None = None, writer: SheetsWriter | None = None, document_id: str | None = None, today: date | None = None) -> SyncResult` en `src/banking/sync.py`: calcula `range_start = (today or date.today()).replace(day=1)`, construye `connector`/`writer` por defecto si se omiten, llama a `fetch_transactions(range_start, execution_date)`, transforma (T007), obtiene `document_id` vía `SecretStore().get("GOOGLE_SHEET_ID")` si no se inyectó, llama a `writer.write(...)`, mide la duración con `time.monotonic()` y devuelve `SyncResult` — sin manejo de excepciones ni logging todavía (se añaden en la Fase 5, US3) — fully type-annotated
- [X] T009 [US1] Implementar `add_parser()` y `handle(args: argparse.Namespace) -> int` en `src/banking/cli/sync.py`: registra el subcomando `sync` sin argumentos adicionales; `handle()` llama a `run_sync()`, imprime el resumen a stdout (FR-006) y devuelve `0` — sin captura de excepciones todavía (se añade en la Fase 5, US3)
- [X] T010 [US1] Registrar el subcomando en `src/banking/__main__.py`: importar `banking.cli.sync`, llamar a `sync_cmd.add_parser(subparsers)` en `_build_parser()`, añadir `if args.command == "sync": sys.exit(sync_cmd.handle(args))` en `main()`, y añadir `"sync"` a la lista de comandos del mensaje de uso impreso sin argumentos

**Checkpoint**: Todos los tests de la Fase 3 pasan. `python -m banking sync`
funciona de extremo a extremo con los dobles de prueba, cubriendo el camino
feliz, cero movimientos, el resumen CLI, y el registro del subcomando.

---

## Fase 4: Historia de Usuario 2 — Ejecutar varias veces el mismo día sin duplicar (Prioridad: P2)

**Objetivo**: Confirmar que `run_sync()` es idempotente por construcción
(sin estado compartido entre invocaciones, sobrescritura completa vía
`SheetsWriter`) — propiedad que ya se deriva del diseño de la Fase 3, no
una capacidad nueva.

**Prueba independiente**: Invocar `run_sync()` dos veces seguidas con el
mismo doble de `IngConnector` y confirmar que ambas llamadas a
`writer.write()` reciben exactamente el mismo `rows`.

### Tests para la Historia de Usuario 2 ⚠️ OBLIGATORIO — escribir primero, verificar el resultado

> **NOTA**: A diferencia de las demás historias, se espera que estos tests
> pasen en verde sin ningún cambio de implementación (la propiedad ya
> emerge de T008). Si alguno falla, indica un estado compartido no deseado
> en `run_sync()` que debe corregirse antes de continuar — ver T012.

- [X] T011 [US2] Escribir tests en fallo (o en verde inmediato, ver nota) en `tests/unit/test_sync.py`: (1) invocar `run_sync()` dos veces con el mismo `connector` mockeado devolviendo el mismo conjunto de movimientos ambas veces → las dos llamadas a `writer.write` reciben exactamente el mismo `rows`, sin acumulación; (2) invocar dos veces donde la segunda llamada a `fetch_transactions` devuelve un movimiento adicional respecto a la primera → la segunda llamada a `writer.write` recibe el conjunto completo actualizado (incluida la fila nueva), no solo la fila nueva ni una concatenación de ambas respuestas

### Verificación para la Historia de Usuario 2

- [X] T012 [US2] Ejecutar `pytest tests/unit/test_sync.py -k US2` y confirmar que T011 pasa sin modificar `run_sync()`; si falla, corregir `run_sync()` en `src/banking/sync.py` para eliminar cualquier estado compartido entre invocaciones (p. ej. una variable de módulo acumulando filas) antes de continuar — no se espera ningún cambio de código en el caso esperado

**Checkpoint**: Todos los tests de las Fases 3-4 pasan. La idempotencia
same-day está verificada explícitamente, no solo asumida.

---

## Fase 5: Historia de Usuario 3 — Diagnosticar un fallo sin inspeccionar código (Prioridad: P3)

**Objetivo**: Un fallo de ING lanza `IngSyncError` sin llamar nunca a
`writer.write`; un fallo de Sheets (incluida la lectura de
`GOOGLE_SHEET_ID`) lanza `SheetsSyncError`; ambos con log `ERROR` a nivel
de pipeline; la capa CLI traduce cada una a su código de salida (`1`/`2`)
y su mensaje en stderr.

**Prueba independiente**: Forzar por separado un `ReauthorizationRequiredError`
de `IngConnector` y un `SheetsAccessError` de `SheetsWriter`; confirmar
`IngSyncError`/`SheetsSyncError` respectivamente, sin llamada a
`writer.write` en el primer caso, y los códigos de salida `1`/`2` desde la
CLI.

### Tests para la Historia de Usuario 3 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T016

- [X] T013 [US3] Escribir tests en fallo en `tests/unit/test_sync.py`, parametrizados sobre las excepciones conocidas de `IngConnector` que sí son alcanzables desde `run_sync()` (`ConnectorConfigError`, `ReauthorizationRequiredError`, `RateLimitExceededError`, `PaginationLimitExceededError`, `EnableBankingAPIError` — se excluye `InvalidDateRangeError`, que `IngConnector` solo lanza si `start_date > end_date`, algo que la construcción del rango de `run_sync()` — día 1 del mes hasta hoy — nunca puede producir): `connector.fetch_transactions` lanza cada una → `run_sync()` lanza `IngSyncError` (mensaje reproduce el original) y `writer.write` **nunca** se invoca
- [X] T014 [US3] Escribir tests en fallo en `tests/unit/test_sync.py`, parametrizados sobre las excepciones conocidas de `SheetsWriter` (`SheetsConfigError`, `SheetsAccessError`, `SheetsQuotaExceededError`, `SheetsAPIError`): `writer.write` lanza cada una (tras `fetch_transactions` exitoso) → `run_sync()` lanza `SheetsSyncError`; y un caso adicional donde `document_id` no se inyecta y `SecretStore().get("GOOGLE_SHEET_ID")` lanza `KeyError` → también `SheetsSyncError`
- [X] T015 [US3] Escribir tests en fallo en `tests/unit/test_sync.py` (usando `caplog`): un fallo de ING emite un log `ERROR` que menciona el banco y "ing"; un fallo de Sheets emite un log `ERROR` que menciona "sheets"; una invocación exitosa emite un log `INFO` con banco, pestaña, filas escritas y duración (a nivel del módulo `sync`, no solo el resumen CLI); en los dos casos de fallo, confirmar además que ningún registro capturado contiene el `document_id` real de prueba ni ningún fragmento de las credenciales usadas en los dobles de `IngConnector`/`SheetsWriter` — mismo estándar de aserción que T014 de IT3 (FR-012)
- [X] T016 [P] [US3] Escribir tests en fallo en `tests/unit/test_cli_sync.py`: `handle()` ante `IngSyncError` imprime a **stderr** un mensaje que identifica el fallo como de ING y devuelve `1`; ante `SheetsSyncError` imprime a stderr identificando Sheets y devuelve `2`

### Implementación para la Historia de Usuario 3

- [X] T017 [US3] En `src/banking/sync.py`, envolver dentro de `run_sync()` (T008): la llamada a `connector.fetch_transactions()` en `try/except Exception as exc: raise IngSyncError(str(exc)) from exc`; y, en un bloque separado, la resolución de `document_id` (si no se inyectó) más la llamada a `writer.write()` en `try/except Exception as exc: raise SheetsSyncError(str(exc)) from exc`; añadir `logger.info(...)` en el camino de éxito y `logger.error(...)` en cada uno de los dos caminos de fallo, identificando el sistema responsable
- [X] T018 [US3] En `src/banking/cli/sync.py`, extender `handle()` (T009): capturar `IngSyncError` → imprimir a stderr, devolver `1`; capturar `SheetsSyncError` → imprimir a stderr, devolver `2`

**Checkpoint**: Todos los tests de las Fases 3-5 pasan. Las tres historias
de usuario del spec están implementadas y son verificables de forma
independiente.

---

## Fase 6: Polish & Validación

**Propósito**: Verificación final transversal y consistencia documental.

- [X] T019 [P] Ejecutar la simulación completa de CI local: `pip-audit -r requirements.txt -r requirements-dev.txt && ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/ && pytest tests/ -v` — todo debe salir con código 0
- [X] T020 [P] Verificar que `git grep` no encuentra material real de credenciales (clave privada RSA, JWT, `session_id`, JSON de cuenta de servicio) en ningún fichero comiteado, incluidos los nuevos de esta funcionalidad (usar `--untracked`)
- [X] T021 [P] Añadir una sección breve "IT4 — Pipeline ING → Sheets" al `quickstart.md` de la raíz del repositorio, referenciando `specs/004-ing-sheets-sync/quickstart.md`, y confirmar que el placeholder `GOOGLE_SHEET_ID=enc:placeholder` de `.env.example` (IT1) ahora se usa de verdad en esta funcionalidad

**Checkpoint**: Las 21 tareas completas. Todos los escenarios de
aceptación del spec pasan. El sistema es demostrable de extremo a extremo
para ING España. La funcionalidad está lista para merge.

---

## Dependencias y Orden de Ejecución

### Dependencias de Fase

- **Fase 1 (Setup)**: Sin tareas
- **Fase 2 (Foundational)**: Sin dependencias — bloquea las tres historias
- **Fase 3 (US1)**: Depende de la Fase 2; los tests (T003-T006) deben fallar antes de la implementación (T007-T010)
- **Fase 4 (US2)**: Depende de la Fase 3 — verifica una propiedad de `run_sync()` (T008), no añade una rama de código nueva
- **Fase 5 (US3)**: Depende de la Fase 4 — envuelve los mismos dos puntos de integración que T008 ya construyó
- **Fase 6 (Polish)**: Depende de las Fases 3, 4 y 5

### Dependencias entre Historias de Usuario

- **US1 (P1)**: Depende solo de la Fase 2 (Foundational). Es el MVP.
- **US2 (P2)**: Depende de US1 — verifica, no extiende, `run_sync()`.
- **US3 (P3)**: Depende de US2 — añade manejo de errores y logging sobre la misma función.

### Dentro de cada Historia

```
US1:  T003,T004 (mismo fichero) ─┐
      T005 [P] ──────────────────┼─→ T007 → T008 → T009 → T010
      T006 [P] ──────────────────┘
US2:  T011 (test)  →  T012 (verificación, sin cambio de código esperado)
US3:  T013,T014,T015 (mismo fichero) ─┐
      T016 [P] ──────────────────────┼─→ T017 → T018
```

---

## Oportunidades de Paralelización

```
T001 puede ejecutarse solo (Fase 2, único test antes de T002)
T005 y T006 pueden ejecutarse en paralelo entre sí y respecto a T003/T004 (ficheros distintos)
T016 puede ejecutarse en paralelo respecto a T013/T014/T015 (fichero distinto)
T019, T020 y T021 (Fase 6) pueden ejecutarse en paralelo — comandos y ficheros independientes
```

No hay oportunidades de paralelización dentro de los bloques de tests que
comparten fichero (T003-T004, T013-T015): mismo `tests/unit/test_sync.py`.

---

## Estrategia de Implementación

### MVP (solo Historia de Usuario 1)

1. Completar Fase 2: Foundational (T001-T002)
2. Escribir los tests en fallo de US1 (T003-T006) — verificar ROJO
3. Implementar US1 (T007-T010) — verificar VERDE
4. **DETENERSE Y VALIDAR**: ejecutar `specs/004-ing-sheets-sync/quickstart.md` Parte A, Pasos 1-2

### Entrega Completa

1. MVP anterior ✅
2. Escribir el test de US2 (T011) — verificar que pasa sin cambios (T012)
3. Escribir los tests en fallo de US3 (T013-T016) — verificar ROJO
4. Implementar US3 (T017-T018) — verificar VERDE
5. Fase 6 Polish (T019-T021)

---

## Notas

- [P] = ficheros distintos, seguro de paralelizar
- `IngSyncError`/`SheetsSyncError` se definen en `src/banking/sync.py` —
  sin clase base compartida (YAGNI, mismo patrón que `ing.py`/`writer.py`)
- `sync.py` (núcleo) NUNCA llama a `print()` — solo `cli/sync.py` puede
  (Anti-patrón #6); `sync.py` sí puede usar `logging`
- Ningún mensaje (resumen, log, error) puede interpolar credenciales, JWT,
  `session_id` completo, ni JSON de cuenta de servicio (FR-012) — se
  cumple por composición: los mensajes de `IngSyncError`/`SheetsSyncError`
  son el `str()` de excepciones ya seguras de IT2/IT3
- Comitear tras cada grupo lógico (tras Fase 2, tras cada historia, tras Polish)
- Ninguna dependencia nueva que pinear en esta funcionalidad
- SC-006 (< 2 min por ejecución) es un SLO operacional; no hay ningún task
  que lo mida contra sistemas reales, ya que los tests mockeados completan
  instantáneamente y no ejercitan el umbral de forma significativa. Se
  valida manualmente en `quickstart.md` Parte B (Paso 6) — no está
  automatizado en CI (mismo alcance que SC-006 de IT3).
