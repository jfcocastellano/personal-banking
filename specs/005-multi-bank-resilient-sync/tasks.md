# Tareas: Sincronización Multi-Banco con Resiliencia Parcial

**Entrada**: Documentos de diseño desde `specs/005-multi-bank-resilient-sync/`

**Prerrequisitos**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Tests**: Los tests son **OBLIGATORIOS** según el Principio II (Test-First). Deben
escribirse antes del código de implementación y verificarse en fallo (Red) antes de
empezar cualquier implementación. El ciclo Red → Green → Refactor no es negociable.

**Organización**: US1 (P1) → US2 (P2) → US3 (P3). Las tres historias comparten la
misma función `run_sync()`, que se construye de forma incremental: US1 añade el
bucle de orquestación en camino feliz (sin manejo de fallos todavía); US2 envuelve
cada llamada a conector en `try/except` y clasifica el resultado global; US3 añade
las dos ramas de terminación controlada (fallo total de bancos, fallo del propio
paso de Sheets). Cada fase dejar pasar en verde, sin regresiones, todo lo construido
por las fases anteriores.

## Formato: `[ID] [P?] [Story] Descripción`

- **[P]**: Paralelizable — ficheros distintos, sin dependencia bloqueante
- **[Story]**: Etiqueta de historia de usuario (US1, US2, US3)
- Todas las rutas son relativas a la raíz del repositorio

---

## Fase 1: Setup (Inicialización del Proyecto)

**Propósito**: Inicialización de la funcionalidad.

Esta funcionalidad no añade ninguna dependencia de terceros ni ningún directorio
nuevo — `src/banking/connectors/`, `tests/unit/connectors/` y `tests/unit/` ya
existen desde IT1-IT2, y no hay librería nueva que pinear (research.md, Contexto
Técnico del plan). No hay tareas de Fase 1.

---

## Fase 2: Foundational (Conector base compartido + tipos de datos multi-banco)

**Propósito**: Extraer la lógica PSD2 común de `IngConnector` a un módulo base
compartido, construir sobre él los tres conectores nuevos (Revolut, MyInvestor,
Sabadell), y definir los tipos de datos multi-banco (`BankOutcome`,
`OverallStatus`, `SyncSummary`, `AllBanksFailedError`) que las tres historias de
usuario necesitan. Ninguna historia puede empezar su implementación hasta que los
cuatro conectores existan y compartan contrato (research.md Decisión 1;
contracts/connector-contract.md).

**⚠️ CRÍTICO**: Ninguna historia de usuario puede empezar su implementación hasta
que esta fase esté completa.

### Tests para Foundational ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T006

- [X] T001 [P] Escribir tests en fallo en `tests/unit/connectors/test_enable_banking.py` (nuevo fichero): usando una subclase mínima de prueba (`class _FakeConnector(EnableBankingConnector): BANK_NAME = "Fake Bank"; _SESSION_ID_KEY = "FAKE_SESSION_ID"`), migrar y generalizar la cobertura de bajo nivel hoy en `test_ing.py` — construcción del JWT RS256 (`kid` = `app_id`, claims `iss`/`aud`/`iat`/`exp`), `_check_session_usable` (200 con `status` != `expired` pasa; 200 con `status == "expired"` y 403 lanzan `ReauthorizationRequiredError`; 429 lanza `RateLimitExceededError`; cualquier otro código lanza `EnableBankingAPIError`), paginación con `continuation_key` hasta agotarse o hasta `PaginationLimitExceededError` a las `_MAX_PAGES` páginas, `_parse_transaction` (débito negativo, crédito positivo, campos ausentes/ inválidos se descartan con `logger.warning`, indicador desconocido se descarta), deduplicación por `(booking_date, amount, description)`, `ConnectorConfigError` ante `eb-config.json`/clave privada ausentes o inválidos, `InvalidDateRangeError` si `start_date > end_date`
- [X] T002 [P] Reescribir `tests/unit/connectors/test_ing.py`: eliminar los tests de lógica de bajo nivel ya migrados a T001; dejar solo `IngConnector.BANK_NAME == "ING España"`, `IngConnector._SESSION_ID_KEY == "ENABLE_BANKING_SESSION_ID_ING"` (cambia respecto al valor actual sin sufijo — debe fallar hoy), y `issubclass(IngConnector, EnableBankingConnector)` (falla hoy, `EnableBankingConnector` no existe todavía)
- [X] T003 [P] Escribir tests en fallo en `tests/unit/connectors/test_revolut.py` (nuevo fichero): `RevolutConnector.BANK_NAME == "Revolut"`, `RevolutConnector._SESSION_ID_KEY == "ENABLE_BANKING_SESSION_ID_REVOLUT"`, `issubclass(RevolutConnector, EnableBankingConnector)`
- [X] T004 [P] Escribir tests en fallo en `tests/unit/connectors/test_myinvestor.py` (nuevo fichero): `MyInvestorConnector.BANK_NAME == "MyInvestor"`, `MyInvestorConnector._SESSION_ID_KEY == "ENABLE_BANKING_SESSION_ID_MYINVESTOR"`, `issubclass(MyInvestorConnector, EnableBankingConnector)`
- [X] T005 [P] Escribir tests en fallo en `tests/unit/connectors/test_sabadell.py` (nuevo fichero): `SabadellConnector.BANK_NAME == "Banco Sabadell"`, `SabadellConnector._SESSION_ID_KEY == "ENABLE_BANKING_SESSION_ID_SABADELL"`, `issubclass(SabadellConnector, EnableBankingConnector)`

### Implementación para Foundational

- [X] T006 Crear `src/banking/connectors/enable_banking.py`: mover desde `ing.py` (sin cambiar su comportamiento) `Transaction`, las excepciones `ConnectorConfigError`/`InvalidDateRangeError`/`ReauthorizationRequiredError`/`RateLimitExceededError`/`EnableBankingAPIError`/`PaginationLimitExceededError`, y la clase `EnableBankingConnector` con `__init__`, `_resolve_account_id`, `fetch_transactions` (JWT, sesión, paginación, parseo) — generalizando las referencias a `_BANK_NAME`/`_SESSION_ID_KEY` de constantes de módulo a atributos de clase `BANK_NAME: str` / `_SESSION_ID_KEY: str` sin valor por defecto (cada subclase los fija); fully type-annotated (T001 debe pasar en verde contra `_FakeConnector`)
- [X] T007 [P] Reescribir `src/banking/connectors/ing.py`: `class IngConnector(EnableBankingConnector): BANK_NAME = "ING España"; _SESSION_ID_KEY = "ENABLE_BANKING_SESSION_ID_ING"` — eliminar toda la lógica ya movida a T006, sin sobrescribir ningún método (T002 debe pasar en verde)
- [X] T008 [P] Crear `src/banking/connectors/revolut.py`: `class RevolutConnector(EnableBankingConnector): BANK_NAME = "Revolut"; _SESSION_ID_KEY = "ENABLE_BANKING_SESSION_ID_REVOLUT"` (T003 debe pasar en verde)
- [X] T009 [P] Crear `src/banking/connectors/myinvestor.py`: `class MyInvestorConnector(EnableBankingConnector): BANK_NAME = "MyInvestor"; _SESSION_ID_KEY = "ENABLE_BANKING_SESSION_ID_MYINVESTOR"` (T004 debe pasar en verde)
- [X] T010 [P] Crear `src/banking/connectors/sabadell.py`: `class SabadellConnector(EnableBankingConnector): BANK_NAME = "Banco Sabadell"; _SESSION_ID_KEY = "ENABLE_BANKING_SESSION_ID_SABADELL"` (T005 debe pasar en verde)
- [X] T011 En `src/banking/sync.py`, sustituir `SyncResult` por los tipos de datos multi-banco (data-model.md): `BankOutcome` (dataclass congelado: `bank_name: str`, `succeeded: bool`, `rows_written: int | None`, `failure_reason: str | None`); `OverallStatus` (`enum.Enum`: `FULL_SUCCESS`, `PARTIAL_FAILURE`, `TOTAL_FAILURE`); `SyncSummary` (dataclass congelado: `outcomes: list[BankOutcome]`, `overall_status: OverallStatus`, `tab_name: str`, `total_rows_written: int`, `duration_seconds: float`); excepción `AllBanksFailedError`; constante de módulo `_CONNECTOR_CLASSES: tuple[type[EnableBankingConnector], ...] = (IngConnector, RevolutConnector, MyInvestorConnector, SabadellConnector)` importando los cuatro conectores de T007-T010 — fully type-annotated, sin lógica de orquestación todavía

**Checkpoint**: T001-T005 pasan en verde. Los cuatro conectores comparten
contrato (`contracts/connector-contract.md`) y son mockeables individualmente con
`Mock(spec=<Connector>)`. `src/banking/sync.py` expone los tipos multi-banco sin
que `run_sync()` los use todavía.

---

## Fase 3: Historia de Usuario 1 — Sincronizar los cuatro bancos en una sola ejecución (Prioridad: P1) 🎯 MVP

**Objetivo**: `python -m banking sync` obtiene los movimientos del mes en curso de
los cuatro bancos, los combina y escribe en una sola pestaña `YYYY-MM`, e imprime
un resumen que confirma los cuatro bancos sincronizados con su recuento de
movimientos.

**Prueba independiente**: `pytest tests/unit/test_sync.py tests/unit/test_cli_sync.py -k US1`
con los cuatro conectores y `SheetsWriter` mockeados devolviendo movimientos
conocidos; confirmar una sola llamada a `writer.write` con las filas combinadas
de los cuatro bancos.

### Tests para la Historia de Usuario 1 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T015

- [X] T012 [US1] Escribir test en fallo en `tests/unit/test_sync.py`: con los cuatro conectores inyectados como `Mock(spec=IngConnector)`, `Mock(spec=RevolutConnector)`, `Mock(spec=MyInvestorConnector)`, `Mock(spec=SabadellConnector)`, cada uno con `fetch_transactions` devolviendo una lista conocida y distinta de `Transaction`, `writer=Mock(spec=SheetsWriter)`, `document_id="doc-id"`, `today=date(2026, 8, 15)`: `run_sync(connectors=[...], writer=writer, document_id="doc-id", today=today)` (1) llama a `fetch_transactions(date(2026, 8, 1), date(2026, 8, 15))` en cada uno de los cuatro conectores; (2) llama a `writer.write` **una sola vez** con `tab_name="2026-08"` y `rows` conteniendo las filas de los cuatro bancos concatenadas en el orden ING/Revolut/MyInvestor/Sabadell, cada fila con el banco correcto en su columna; (3) devuelve un `SyncSummary` con `overall_status == OverallStatus.FULL_SUCCESS`, `outcomes` con los cuatro `BankOutcome(succeeded=True, rows_written=<n>, failure_reason=None)` en ese mismo orden, y `total_rows_written` igual a la suma de movimientos de los cuatro
- [X] T013 [US1] Escribir test en fallo en `tests/unit/test_sync.py`: uno de los cuatro conectores mockeados devuelve `[]` (sin movimientos) mientras los otros tres devuelven movimientos conocidos → ese banco aparece en `outcomes` como `BankOutcome(succeeded=True, rows_written=0, failure_reason=None)` (no es un fallo), `overall_status` sigue siendo `FULL_SUCCESS`, y `writer.write` recibe las filas de los otros tres sin ninguna fila de ese banco
- [X] T014 [P] [US1] Escribir test en fallo en `tests/unit/test_cli_sync.py`: `cli.sync.handle(args)` con `run_sync` sustituido por un doble que devuelve un `SyncSummary` con `overall_status == FULL_SUCCESS` conocido, imprime a **stdout** una línea de cabecera `4/4 bancos` con el total de movimientos, la pestaña y la duración, más una línea por banco con su recuento (formato de `contracts/cli-sync-interface.md`), y devuelve `0`

### Implementación para la Historia de Usuario 1

- [X] T015 [US1] Reescribir `run_sync()` en `src/banking/sync.py`: nueva firma `run_sync(connectors: Sequence[EnableBankingConnector] | None = None, writer: SheetsWriter | None = None, document_id: str | None = None, today: date | None = None) -> SyncSummary` (contracts/sync-pipeline-interface.md); si `connectors` es `None`, instancia por defecto una de cada clase de `_CONNECTOR_CLASSES` (T011); calcula `range_start`/`tab_name` igual que IT4; itera los conectores en orden, llama a `fetch_transactions` de cada uno **sin todavía capturar excepciones** (se añade en T021/US2), construye un `BankOutcome` exitoso por cada uno, transforma y concatena las filas de todos (reutilizando `_transform`, sin cambios), llama una vez a `writer.write(...)`, y devuelve `SyncSummary` con `overall_status = OverallStatus.FULL_SUCCESS` — fully type-annotated
- [X] T016 [US1] Reescribir `handle()` en `src/banking/cli/sync.py`: llama a `run_sync()`; en éxito, imprime a stdout el resumen multi-banco (formato de `contracts/cli-sync-interface.md`, rama de éxito completo: cabecera `4/4 bancos` + una línea por banco con su recuento) y devuelve `0` — sin captura de excepciones todavía (se añade en la Fase 5, US3)

**Checkpoint**: T001-T016 pasan en verde. `python -m banking sync` funciona de
extremo a extremo con los cuatro conectores mockeados devolviendo movimientos,
cubriendo el camino feliz, un banco sin movimientos, y el resumen CLI de éxito
completo.

---

## Fase 4: Historia de Usuario 2 — Continuar cuando un banco falla, sin perder los datos de los demás (Prioridad: P2)

**Objetivo**: Si el conector de un banco lanza cualquiera de sus errores
conocidos (sesión expirada/rechazada, límite de peticiones, error de API,
timeout u otro), `run_sync()` no propaga la excepción: continúa con los bancos
restantes, escribe en Sheets los movimientos de los bancos exitosos, y devuelve
un `SyncSummary` con `overall_status == PARTIAL_FAILURE` que identifica el banco
fallido y su motivo. Además, cada ejecución refleja únicamente los bancos
exitosos de **esa** ejecución — no arrastra silenciosamente datos de un banco que
hubiera tenido éxito en una ejecución anterior el mismo día pero falla en la
actual (FR-006).

**Prueba independiente**: Configurar uno de los cuatro conectores mockeados para
lanzar cada categoría de fallo conocida mientras los otros tres devuelven
movimientos; confirmar una sola llamada a `writer.write` con solo las filas de
los tres exitosos, y `overall_status == PARTIAL_FAILURE`. Por separado, invocar
`run_sync()` dos veces consecutivas para confirmar que la segunda ejecución no
mezcla datos de la primera.

### Tests para la Historia de Usuario 2 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T021

- [X] T017 [US2] Escribir tests en fallo en `tests/unit/test_sync.py`, parametrizados sobre las categorías de fallo de conector alcanzables desde `run_sync()` (`ReauthorizationRequiredError`, `RateLimitExceededError`, `EnableBankingAPIError`, `ConnectorConfigError`, `PaginationLimitExceededError`, y una excepción genérica no contemplada explícitamente como `httpx.TimeoutException` representando "timeout u otro" — se excluye `InvalidDateRangeError`, inalcanzable porque `run_sync()` siempre construye `start_date <= end_date`): con exactamente uno de los cuatro conectores mockeados lanzando la excepción parametrizada y los otros tres devolviendo movimientos conocidos, `run_sync()` (1) no propaga la excepción; (2) sigue llamando a `fetch_transactions` de los conectores restantes en la secuencia; (3) devuelve `SyncSummary` con `overall_status == OverallStatus.PARTIAL_FAILURE`, `outcomes` con el banco fallido como `BankOutcome(succeeded=False, rows_written=None, failure_reason=str(exc))` y los otros tres como exitosos; (4) `writer.write` se llama una sola vez, solo con las filas de los tres bancos exitosos
- [X] T018 [US2] Escribir test en fallo en `tests/unit/test_sync.py` (usando `caplog`): cuando un conector falla, se emite un log `ERROR` que menciona el nombre de ese banco y el motivo; confirmar además que ningún registro capturado contiene el `session_id`, JWT, ni credenciales usadas en los dobles de conector (FR-004) — mismo estándar de aserción que IT4 aplicó a `IngSyncError`
- [X] T019 [P] [US2] Escribir test en fallo en `tests/unit/test_cli_sync.py`: `handle()` con `run_sync` sustituido por un doble que devuelve un `SyncSummary` con `overall_status == PARTIAL_FAILURE` conocido, imprime a **stdout** una cabecera `3/4 bancos` con el total de movimientos escritos, una línea por banco exitoso con su recuento y una línea para el banco fallido con su motivo (formato de `contracts/cli-sync-interface.md`), y devuelve `3`
- [X] T020 [US2] Escribir test en fallo en `tests/unit/test_sync.py` (FR-006, Escenario de Aceptación 5): invocar `run_sync()` dos veces consecutivas con los mismos cuatro conectores mockeados y el mismo `writer` — primera invocación con los cuatro devolviendo movimientos conocidos (éxito completo); segunda invocación con uno de ellos (p. ej. Revolut) lanzando una excepción mientras los otros tres siguen devolviendo movimientos — confirmar que la **segunda** llamada a `writer.write` recibe únicamente las filas de los tres bancos exitosos de la segunda ejecución, sin ninguna fila de Revolut de la primera ejecución mezclada

### Implementación para la Historia de Usuario 2

- [X] T021 [US2] En `run_sync()` (`src/banking/sync.py`, T015), envolver la llamada a `fetch_transactions` de cada conector en `try/except Exception as exc`: en fallo, registrar `logger.error(...)` con el nombre del banco y `exc` (sin credenciales) y construir el `BankOutcome` fallido en vez de propagar; tras el bucle, calcular `overall_status` con un helper `_classify(outcomes: list[BankOutcome]) -> OverallStatus` (todos exitosos → `FULL_SUCCESS`; alguno exitoso y alguno fallido → `PARTIAL_FAILURE`; ninguno exitoso → se resuelve en la Fase 5/US3) — fully type-annotated, complejidad ciclomática de `run_sync()` se mantiene ≤10 delegando en `_classify`. La combinación de filas (T015) ya solo usa los `BankOutcome` exitosos de **esta** invocación, sin estado retenido entre llamadas — satisface T020/FR-006 sin cambio adicional
- [X] T022 [US2] Extender `handle()` en `src/banking/cli/sync.py` (T016): cuando `overall_status == PARTIAL_FAILURE`, imprimir a stdout la rama de fallo parcial del resumen (cabecera `N/4 bancos`, banco(s) fallido(s) con su motivo) y devolver `3`

**Checkpoint**: T001-T022 pasan en verde, sin regresión en la Fase 3 (US1). El
fallo de un banco ya no aborta la ejecución; los datos de los demás se escriben
y quedan reportados en el resumen; una ejecución posterior con un banco fallido
no arrastra datos de una ejecución anterior.

---

## Fase 5: Historia de Usuario 3 — Terminar de forma controlada cuando ningún banco responde (Prioridad: P3)

**Objetivo**: Si los cuatro conectores fallan, `run_sync()` lanza
`AllBanksFailedError` sin llamar nunca a `writer.write`; si al menos un banco
tuvo éxito pero el propio paso de escritura combinada en Sheets falla,
`run_sync()` lanza `SheetsSyncError` (mismo comportamiento que IT4, adaptado a la
escritura combinada). La capa CLI traduce ambos casos a sus códigos de salida
(`1`/`2`) y su mensaje en stderr, sin propagar ninguna excepción no controlada.

**Prueba independiente**: Configurar los cuatro conectores mockeados para que
fallen todos con motivos distintos; confirmar `AllBanksFailedError`, ninguna
llamada a `writer.write`, y el código de salida `1` desde la CLI. Por separado,
forzar un fallo del `SheetsWriter` mockeado tras al menos un banco exitoso;
confirmar `SheetsSyncError` y el código de salida `2`.

### Tests para la Historia de Usuario 3 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T026

- [X] T023 [US3] Escribir test en fallo en `tests/unit/test_sync.py`: los cuatro conectores mockeados lanzan excepciones distintas (p. ej. `ReauthorizationRequiredError`, `RateLimitExceededError`, `EnableBankingAPIError`, y una excepción genérica) → `run_sync()` lanza `AllBanksFailedError` cuyo mensaje agrega los cuatro nombres de banco y motivos, sin credenciales; `writer.write` **nunca** se invoca; se emite un log `ERROR` agregando los cuatro fallos
- [X] T024 [US3] Escribir tests en fallo en `tests/unit/test_sync.py`, parametrizados sobre las excepciones conocidas de `SheetsWriter` (`SheetsConfigError`, `SheetsAccessError`, `SheetsQuotaExceededError`, `SheetsAPIError`): con al menos un conector exitoso y `writer.write` lanzando cada una → `run_sync()` lanza `SheetsSyncError`; y un caso adicional donde `document_id` no se inyecta y `SecretStore().get("GOOGLE_SHEET_ID")` lanza `KeyError` → también `SheetsSyncError`; en ambos, se emite un log `ERROR` que menciona "sheets"
- [X] T025 [P] [US3] Escribir tests en fallo en `tests/unit/test_cli_sync.py`: `handle()` con `run_sync` lanzando `AllBanksFailedError` (con los cuatro motivos) imprime a **stderr** el resumen de fallo total (formato de `contracts/cli-sync-interface.md`: los cuatro bancos con su motivo, sin recuento de movimientos) y devuelve `1`; `handle()` con `run_sync` lanzando `SheetsSyncError` imprime a stderr `ERROR (Sheets): <motivo>` y devuelve `2`

### Implementación para la Historia de Usuario 3

- [X] T026 [US3] En `run_sync()` (`src/banking/sync.py`, T021): tras el bucle, si los cuatro `BankOutcome.succeeded` son `False`, registrar `logger.error(...)` agregando los cuatro motivos y lanzar `AllBanksFailedError` **sin** llamar a `writer.write`; en caso contrario (rama ya existente de T015/T021), envolver la resolución de `document_id` (si no se inyectó) y la llamada combinada a `writer.write(...)` en `try/except Exception as exc: logger.error(...); raise SheetsSyncError(str(exc)) from exc` — mismo patrón que IT4, ahora aplicado a la escritura combinada
- [X] T027 [US3] Extender `handle()` en `src/banking/cli/sync.py` (T022): capturar `AllBanksFailedError` → imprimir a stderr el resumen de fallo total, devolver `1`; capturar `SheetsSyncError` → imprimir a stderr `ERROR (Sheets): <motivo>`, devolver `2`

**Checkpoint**: T001-T027 pasan en verde. Los tres escenarios obligatorios de la
spec (FR-013: todos ok / un banco falla / todos fallan) y el caso de fallo del
propio Sheets están cubiertos. Las tres historias de usuario son verificables de
forma independiente y sin regresión entre sí.

---

## Fase 6: Polish & Validación

**Propósito**: Verificación final transversal, migración de configuración y
consistencia documental.

- [X] T028 [P] Ejecutar la simulación completa de CI local: `pip-audit -r requirements.txt -r requirements-dev.txt && ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/ && pytest tests/ -v` — todo debe salir con código 0
- [X] T029 [P] Verificar que `git grep --untracked` no encuentra material real de credenciales (clave privada RSA, JWT, `session_id`, JSON de cuenta de servicio) en ningún fichero de esta funcionalidad, incluidos los cuatro conectores nuevos/modificados
- [X] T030 [P] Actualizar `.env.example`: sustituir la entrada única `ENABLE_BANKING_SESSION_ID=enc:placeholder` por las cuatro claves por banco (`ENABLE_BANKING_SESSION_ID_ING`, `..._REVOLUT`, `..._MYINVESTOR`, `..._SABADELL`, todas `enc:placeholder`); `ENABLE_BANKING_APP_ID` permanece sin cambios (compartida, research.md Decisión 3)
- [X] T031 [P] Añadir una sección breve "IT5 — Sincronización multi-banco" al `quickstart.md` de la raíz del repositorio, referenciando `specs/005-multi-bank-resilient-sync/quickstart.md`, incluyendo el paso de migración manual de la clave de sesión de ING (`ENABLE_BANKING_SESSION_ID` → `ENABLE_BANKING_SESSION_ID_ING`)
- [X] T032 Ejecutar la porción automatizada de `specs/005-multi-bank-resilient-sync/quickstart.md` (sección "Validación automatizada") y confirmar que los cuatro códigos de salida (`0`/`1`/`2`/`3`) están cubiertos por `test_cli_sync.py`; la validación manual contra las cuatro APIs reales (incluida la medición de SC-006) queda documentada como paso opcional fuera de CI, mismo alcance que IT4

**Checkpoint**: Las 32 tareas completas. Todos los escenarios de aceptación del
spec pasan. El sistema sincroniza los cuatro bancos con resiliencia parcial de
extremo a extremo (con dobles de prueba). La funcionalidad está lista para
merge.

---

## Dependencias y Orden de Ejecución

### Dependencias de Fase

- **Fase 1 (Setup)**: Sin tareas
- **Fase 2 (Foundational)**: Sin dependencias — bloquea las tres historias
- **Fase 3 (US1)**: Depende de la Fase 2; T012-T014 deben fallar antes de T015-T016
- **Fase 4 (US2)**: Depende de la Fase 3 — envuelve la misma función `run_sync()` que T015 construyó
- **Fase 5 (US3)**: Depende de la Fase 4 — añade las dos ramas de terminación sobre el mismo `run_sync()`
- **Fase 6 (Polish)**: Depende de las Fases 3, 4 y 5

### Dependencias entre Historias de Usuario

- **US1 (P1)**: Depende solo de la Fase 2 (Foundational). Es el MVP.
- **US2 (P2)**: Depende de US1 — añade manejo de fallos sobre el mismo `run_sync()`, sin romper el camino feliz.
- **US3 (P3)**: Depende de US2 — añade las dos ramas de terminación sobre el mismo `run_sync()` y `handle()`.

### Dentro de cada Fase

```
Foundational: T001,T002,T003,T004,T005 [P] (ficheros distintos) ─→ T006 ─→ T007,T008,T009,T010 [P] ─→ T011
US1:  T012,T013 (mismo fichero) ─┐
      T014 [P] ──────────────────┼─→ T015 → T016
US2:  T017,T018,T020 (mismo fichero) ─┐
      T019 [P] ────────────────────────┼─→ T021 → T022
US3:  T023,T024 (mismo fichero) ─┐
      T025 [P] ──────────────────┼─→ T026 → T027
```

---

## Oportunidades de Paralelización

```
T001-T005 pueden ejecutarse en paralelo entre sí (Foundational, ficheros distintos)
T007-T010 pueden ejecutarse en paralelo entre sí una vez completado T006 (ficheros distintos)
T014 puede ejecutarse en paralelo respecto a T012/T013 (fichero distinto)
T019 puede ejecutarse en paralelo respecto a T017/T018/T020 (fichero distinto)
T025 puede ejecutarse en paralelo respecto a T023/T024 (fichero distinto)
T028, T029, T030 y T031 (Fase 6) pueden ejecutarse en paralelo — comandos y ficheros independientes
```

No hay oportunidades de paralelización dentro de los bloques de tests que
comparten fichero (T012-T013, T017-T018-T020, T023-T024): todos en
`tests/unit/test_sync.py`.

---

## Ejemplo de Paralelización: Fase 2 (Foundational)

```bash
# Lanzar los cinco tests de conector en paralelo:
Task: "Escribir tests en fallo en tests/unit/connectors/test_enable_banking.py"
Task: "Reescribir tests/unit/connectors/test_ing.py"
Task: "Escribir tests en fallo en tests/unit/connectors/test_revolut.py"
Task: "Escribir tests en fallo en tests/unit/connectors/test_myinvestor.py"
Task: "Escribir tests en fallo en tests/unit/connectors/test_sabadell.py"

# Tras T006 (enable_banking.py), lanzar los cuatro conectores en paralelo:
Task: "Reescribir src/banking/connectors/ing.py"
Task: "Crear src/banking/connectors/revolut.py"
Task: "Crear src/banking/connectors/myinvestor.py"
Task: "Crear src/banking/connectors/sabadell.py"
```

---

## Estrategia de Implementación

### MVP (solo Historia de Usuario 1)

1. Completar Fase 2: Foundational (T001-T011)
2. Escribir los tests en fallo de US1 (T012-T014) — verificar ROJO
3. Implementar US1 (T015-T016) — verificar VERDE
4. **DETENERSE Y VALIDAR**: ejecutar `specs/005-multi-bank-resilient-sync/quickstart.md`, sección "Validación automatizada", filtrando por US1

### Entrega Completa

1. MVP anterior ✅
2. Escribir los tests en fallo de US2 (T017-T020) — verificar ROJO
3. Implementar US2 (T021-T022) — verificar VERDE
4. Escribir los tests en fallo de US3 (T023-T025) — verificar ROJO
5. Implementar US3 (T026-T027) — verificar VERDE
6. Fase 6 Polish (T028-T032)

---

## Notas

- [P] = ficheros distintos, seguro de paralelizar
- `AllBanksFailedError`/`SheetsSyncError` se definen en `src/banking/sync.py`,
  sin clase base compartida (YAGNI, mismo patrón que IT4)
- `sync.py` (núcleo) NUNCA llama a `print()` — solo `cli/sync.py` puede
  (Anti-patrón #6); `sync.py` sí puede usar `logging`
- Ningún mensaje (resumen, log, error) puede interpolar credenciales, JWT,
  `session_id` completo, ni JSON de cuenta de servicio, para ninguno de los
  cuatro bancos (FR-004/FR-014) — se cumple por composición: los mensajes de
  `BankOutcome.failure_reason`/`AllBanksFailedError`/`SheetsSyncError` son el
  `str()` de excepciones ya seguras del conector base (T006) y de `SheetsWriter`
  (IT3)
- No hay techo de tiempo por banco a nivel de orquestador (spec.md §
  Clarifications, research.md Contexto Técnico) — ningún task introduce lógica
  de timeout nueva en `run_sync()`
- `connectors: Sequence[EnableBankingConnector] | None` (T011/T015) — se tipa
  contra la clase base compartida, no contra `object`, para no romper el gate
  `mypy --strict` (Principio VI) al acceder a `.BANK_NAME`/`.fetch_transactions`
  dentro de `run_sync()`
- Comitear tras cada grupo lógico (tras Fase 2, tras cada historia, tras Polish)
- Ninguna dependencia nueva que pinear en esta funcionalidad
- SC-006 (< 2 min para los 4 bancos) es un SLO operacional; no hay ningún task
  que lo mida contra sistemas reales, ya que los tests mockeados completan
  instantáneamente. Se valida manualmente en
  `specs/005-multi-bank-resilient-sync/quickstart.md` — no está automatizado en
  CI (mismo alcance que SC-006 de IT4)
