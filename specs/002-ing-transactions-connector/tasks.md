# Tareas: Conector de Movimientos ING España (Enable Banking)

**Entrada**: Documentos de diseño desde `specs/002-ing-transactions-connector/`

**Prerrequisitos**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Tests**: Los tests son **OBLIGATORIOS** según el Principio II (Test-First). Deben
escribirse antes del código de implementación y verificarse en fallo (Red) antes de
empezar cualquier implementación. El ciclo Red → Green → Refactor no es negociable.

**Organización**: US1 (P1) → US2 (P2) → US3 (P3). Cada historia depende de que el
módulo `ing.py` ya exista con la estructura mínima que la historia anterior dejó
lista (misma razón que en IT1: la CI necesita código que revisar, aquí US2/US3
necesitan el bucle de paginación de US1 en el que insertar sus propias
comprobaciones de error).

## Formato: `[ID] [P?] [Story] Descripción`

- **[P]**: Paralelizable — ficheros distintos, sin dependencia bloqueante
- **[Story]**: Etiqueta de historia de usuario (US1, US2, US3)
- Todas las rutas son relativas a la raíz del repositorio
- Todos los tasks de test de esta funcionalidad escriben en el **mismo fichero**
  (`tests/unit/connectors/test_ing.py`); por eso ninguno lleva `[P]` entre sí,
  aunque sí puedan ejecutarse en paralelo con tasks de otros ficheros

---

## Nota de refinamiento sobre `contracts/ing-connector-interface.md`

El contrato de Fase 1 solo documentaba `IngConnector(http_client=...)`. Para que
los tests de Fase 2 puedan aislar la configuración local sin tocar el sistema de
ficheros real del desarrollador, `IngConnector` también acepta un parámetro
opcional `config_dir: Path | None = None` (por defecto
`~/.config/banca-personal`, sobrescribible también vía la variable de entorno
`BANKING_EB_CONFIG_DIR`) — mismo patrón que `SecretStore` ya usa con
`BANKING_ENV_FILE`. Este refinamiento no cambia ningún requisito del spec, solo
la forma de inyectar dependencias en tests.

---

## Nota de remediación (`/speckit-analyze`, 2026-08-03)

Tras ejecutar `/speckit-analyze` se detectaron y corrigieron 4 gaps en esta
versión de `tasks.md`:

- **T009** (nueva) — cierra un hueco del Principio II (Test-First): T014
  (`_load_signing_credential`) implementaba `ConnectorConfigError` sin ningún
  test previo en Rojo para esos caminos.
- **T016** — ampliada con el caso HTTP 500/502 → `EnableBankingAPIError`, que
  antes solo se testeaba de forma implícita en la tarea de implementación
  (T021, antes T016), violando también el Principio II.
- **T013** (core loop de `fetch_transactions`) — ampliada para mencionar
  explícitamente la lectura del `session_id` vía `SecretStore` (FR-002), que
  antes solo existía como fixture de test sin ningún task de implementación
  que la usara.
- **T014 y T016** (tests de US2/US3) — ampliadas con aserciones de log de
  fallo (banco, rango, motivo), que antes solo se testeaban en el camino de
  éxito (FR-010 / SC-005).

---

## Fase 1: Setup (Inicialización del Proyecto)

**Propósito**: Crear la estructura de directorios y añadir las dependencias
nuevas. Sin lógica Python todavía.

- [X] T001 Crear los directorios `src/banking/connectors/` y `tests/unit/connectors/`
- [X] T002 Añadir `httpx` y `PyJWT` a `requirements.txt` con versión exacta pineada (ejecutar `pip install httpx PyJWT`, luego `pip freeze` para capturar las versiones exactas, siguiendo la misma metodología que IT1)

**Checkpoint**: Directorios creados. `httpx` y `PyJWT` instalados y pineados.

---

## Fase 2: Foundational (Fixtures Compartidas)

**Propósito**: Fixtures de test reutilizables por las tres historias de usuario.
Ninguna lógica de negocio del conector todavía — eso empieza en la Fase 3, después
de que los tests estén en Rojo.

**⚠️ CRÍTICO**: Ninguna historia de usuario puede empezar su implementación hasta
que esta fase esté completa.

- [X] T003 Crear ficheros marcadores `__init__.py`: `src/banking/connectors/__init__.py`, `tests/unit/connectors/__init__.py`
- [X] T004 [P] Añadir fixtures a `tests/unit/conftest.py`: `rsa_private_key_pem` (genera un par de claves RSA-2048 efímero vía `cryptography.hazmat.primitives.asymmetric.rsa`, devuelve el PEM de la clave privada — nunca una clave real); `eb_config_dir` (escribe en `tmp_path` un `eb-config.json` con `app_id` + `private_key_path` apuntando al PEM anterior, y hace `monkeypatch.setenv("BANKING_EB_CONFIG_DIR", str(tmp_path))`); `session_id_in_store` (usa `mock_master_key` + `tmp_env_file` ya existentes, hace `monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))` y `SecretStore(tmp_env_file).set("ENABLE_BANKING_SESSION_ID", "test-session-id")`); `mock_http_client` (función fixture que, dado un `handler: Callable[[httpx.Request], httpx.Response]`, devuelve `httpx.Client(transport=httpx.MockTransport(handler))`)

**Checkpoint**: `pytest --collect-only` sigue sin errores de importación. Fixtures
listas para las tres historias.

---

## Fase 3: Historia de Usuario 1 — Recuperar movimientos liquidados en un rango de fechas (Prioridad: P1) 🎯 MVP

**Objetivo**: Dado un rango de fechas, `IngConnector.fetch_transactions()`
devuelve todas las transacciones `BOOK` normalizadas (importe con signo, divisa
ISO 4217), paginando vía `continuation_key`, deduplicando por solape de página,
y emitiendo un log estructurado de éxito.

**Prueba independiente**: Ejecutar `pytest tests/unit/connectors/test_ing.py -k US1`
(o el subconjunto correspondiente) con la API completamente mockeada; todos los
escenarios de aceptación de la Historia de Usuario 1 del spec pasan.

### Tests para la Historia de Usuario 1 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T010

> **NOTA: Escribir TODOS los tests de esta sección primero. Ejecutar `pytest` y
> confirmar que CADA test falla con `ImportError` (el módulo `ing.py` no existe
> todavía) antes de escribir ninguna implementación (Principio II).**

- [X] T005 [US1] Escribir tests en fallo para el camino feliz en `tests/unit/connectors/test_ing.py`: (1) una única página con transacciones `BOOK`/`PDNG`/`INFO` mezcladas → solo las `BOOK` aparecen en el resultado, con importe positivo para `CRDT`, negativo para `DBIT`, y divisa ISO 4217 incluida; (2) resultados repartidos en varias páginas vía `continuation_key` → el resultado combina todas las páginas; (3) una transacción fechada exactamente en `start_date` y otra exactamente en `end_date` → ambas incluidas (rango inclusivo sobre fecha de liquidación); (4) un rango sin transacciones → lista vacía, sin lanzar error
- [X] T006 [US1] Escribir tests en fallo para deduplicación en `tests/unit/connectors/test_ing.py`: la misma transacción (misma fecha de liquidación + importe + descripción) apareciendo como última de una página y primera de la siguiente → aparece una sola vez en el resultado
- [X] T007 [US1] Escribir tests en fallo para el log estructurado de éxito en `tests/unit/connectors/test_ing.py` (usando `caplog`): una invocación exitosa emite exactamente un registro de log que contiene el identificador del banco, la fecha de inicio y fin solicitadas, y el número de registros devueltos
- [X] T008 [US1] Escribir tests en fallo para validación de entrada y registros malformados en `tests/unit/connectors/test_ing.py`: (1) `start_date > end_date` lanza `InvalidDateRangeError` antes de cualquier llamada HTTP; (2) un registro de transacción de la API sin `amount`, `currency`, `status`, o indicador `CRDT`/`DBIT` se omite con un log `WARNING`, y el resto de transacciones de esa página se procesan con normalidad
- [X] T009 [US1] Escribir tests en fallo para configuración inválida en `tests/unit/connectors/test_ing.py`: (1) `eb-config.json` ausente en `config_dir` → `ConnectorConfigError` antes de cualquier llamada HTTP; (2) el fichero existe pero no es JSON válido → `ConnectorConfigError`; (3) falta `app_id` o `private_key_path` en el JSON → `ConnectorConfigError`; (4) `private_key_path` apunta a un fichero inexistente o que no contiene una clave RSA privada válida → `ConnectorConfigError` — los cuatro casos verificados en Rojo antes de T010 *(cierra el gap C1 detectado en `/speckit-analyze`)*

### Implementación para la Historia de Usuario 1

- [X] T010 [US1] Implementar la carga de configuración en `src/banking/connectors/ing.py`: `_load_signing_credential(config_dir: Path | None)` lee `eb-config.json` (respetando `BANKING_EB_CONFIG_DIR`, por defecto `~/.config/banca-personal`), carga la clave privada RSA vía `cryptography.hazmat.primitives.serialization.load_pem_private_key`; define y lanza `ConnectorConfigError` si el fichero no existe, el JSON es inválido, faltan `app_id`/`private_key_path`, o la clave no es válida — fully type-annotated
- [X] T011 [US1] Implementar la generación del JWT en `src/banking/connectors/ing.py`: `_build_jwt(app_id: str, private_key) -> str` usando `PyJWT` con `algorithm="PS256"` y un claim `exp` de vida corta; la función nunca registra en ningún log la clave privada ni el JWT resultante (FR-015)
- [X] T012 [US1] Implementar el dataclass `Transaction` y el parseo/normalización de un registro de la API en `src/banking/connectors/ing.py`: `_parse_transaction(raw: dict) -> Transaction | None` construye `Transaction(booking_date, amount, currency, description)` con el signo aplicado según `CRDT`/`DBIT`, devuelve `None` (y registra un `WARNING`) si falta algún campo obligatorio — fully type-annotated
- [X] T013 [US1] Implementar `IngConnector.__init__` y `fetch_transactions(start_date, end_date) -> list[Transaction]` en `src/banking/connectors/ing.py`: valida el rango de fechas (`InvalidDateRangeError`), obtiene la credencial de firma (T010) y el JWT (T011), lee el `session_id` PSD2 vía `SecretStore().get("ENABLE_BANKING_SESSION_ID")` e inclúyelo en cada petición según el mecanismo descrito en `contracts/enable-banking-api.md` (FR-002 — *cierra el gap E1 detectado en `/speckit-analyze`*), llama al endpoint de transacciones con el `httpx.Client` inyectado o uno por defecto, sigue `continuation_key` hasta agotar la paginación, filtra solo `BOOK`, normaliza cada registro (T012), deduplica por `(booking_date, amount, description)`, evalúa el rango de forma inclusiva sobre `booking_date`, y emite el log estructurado de éxito al finalizar — fully type-annotated

**Checkpoint**: Todos los tests de la Fase 3 pasan. `IngConnector.fetch_transactions()`
funciona de extremo a extremo con la API mockeada, cubriendo el camino feliz, la
deduplicación, el logging de éxito, la validación de entrada y la validación de
configuración.

---

## Fase 4: Historia de Usuario 2 — Detectar una sesión inutilizable y fallar con claridad (Prioridad: P2)

**Objetivo**: Ante HTTP 403 o un estado de sesión `expired`, el conector lanza
`ReauthorizationRequiredError` con un mensaje claro, antes de devolver cualquier
dato, incluso a mitad de paginación.

**Prueba independiente**: Mockear la API para devolver HTTP 403, y por separado
un cuerpo 200 con estado `expired`; confirmar que ambos casos lanzan
`ReauthorizationRequiredError` sin devolver datos parciales.

### Tests para la Historia de Usuario 2 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T015

- [X] T014 [US2] Escribir tests en fallo en `tests/unit/connectors/test_ing.py`: (1) HTTP 403 en la petición inicial → `ReauthorizationRequiredError` con un mensaje que indica explícitamente la necesidad de re-autorización manual por navegador; (2) una respuesta 200 cuyo cuerpo reporta un campo de estado de sesión `expired` → la misma excepción, antes de procesar ninguna transacción; (3) el fallo ocurre después de recuperar con éxito una primera página → no se devuelve ninguna lista parcial, la excepción se propaga igualmente; (4) en cada uno de los tres casos anteriores, usando `caplog`, se emite un log de fallo que contiene el nombre del banco, el rango de fechas solicitado y el motivo del fallo, sin incluir la clave privada, el JWT ni el `session_id` completo *(cierra el gap E2 detectado en `/speckit-analyze`)*

### Implementación para la Historia de Usuario 2

- [X] T015 [US2] Implementar `_check_session_usable(response: httpx.Response) -> None` en `src/banking/connectors/ing.py`: revisa el código HTTP (403) y el campo de estado de sesión del cuerpo de respuesta (`expired`), lanzando `ReauthorizationRequiredError` con mensaje de re-autorización manual; integrar esta comprobación en el bucle de paginación de `fetch_transactions` (T013) antes de acumular las transacciones de cada página en el resultado, y emitir el log de fallo estructurado (banco, rango, motivo) exigido por T014

**Checkpoint**: Todos los tests de la Fase 4 pasan, sin romper los de la Fase 3.

---

## Fase 5: Historia de Usuario 3 — Respetar el límite de peticiones PSD2 e informar con claridad (Prioridad: P3)

**Objetivo**: Ante HTTP 429 (petición inicial o de paginación), el conector
lanza `RateLimitExceededError` con un mensaje que referencia el límite diario
de 4 peticiones/cuenta; ante cualquier otro error HTTP inesperado, lanza
`EnableBankingAPIError`.

**Prueba independiente**: Mockear la API para devolver HTTP 429 en la primera
petición, y por separado en una petición de paginación posterior, y por
separado un HTTP 500; confirmar que los tres casos lanzan la excepción
correspondiente sin resultado parcial.

### Tests para la Historia de Usuario 3 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T017

- [X] T016 [US3] Escribir tests en fallo en `tests/unit/connectors/test_ing.py`: (1) HTTP 429 en la petición inicial → `RateLimitExceededError` con un mensaje que menciona el límite diario de 4 peticiones/cuenta PSD2; (2) HTTP 429 en una petición de paginación posterior (tras una primera página exitosa) → la misma excepción, sin devolver un resultado parcial; (3) HTTP 500 (o cualquier otro código de error inesperado, p. ej. 502) en la petición inicial → `EnableBankingAPIError`, distinta de las dos anteriores *(cierra el gap C2 detectado en `/speckit-analyze`)*; (4) en los tres casos anteriores, usando `caplog`, se emite un log de fallo con el nombre del banco, el rango de fechas solicitado y el motivo *(cierra el gap E2 detectado en `/speckit-analyze`)*

### Implementación para la Historia de Usuario 3

- [X] T017 [US3] Extender el mapeo de errores HTTP en `src/banking/connectors/ing.py` (mismo punto de integración que T015): HTTP 429 → `RateLimitExceededError`; cualquier otro código HTTP de error inesperado (500, 502, etc.) → `EnableBankingAPIError`, cubriendo también el Caso Límite de "error HTTP distinto de 403/429", y emitiendo el log de fallo estructurado exigido por T016

**Checkpoint**: Todos los tests de las Fases 3-5 pasan. Las tres historias de
usuario del spec están implementadas y son verificables de forma independiente.

---

## Fase 6: Polish & Validación

**Propósito**: Verificación final transversal — salvaguarda de paginación,
cumplimiento de la redacción de secretos en logs (FR-015), y validación
completa de la CI local.

- [X] T018 [P] Escribir test en fallo y luego implementar la salvaguarda de paginación en `src/banking/connectors/ing.py` y `tests/unit/connectors/test_ing.py`: definir la constante `MAX_PAGES` (valor inicial 100); si un handler mockeado devuelve `continuation_key` indefinidamente, `fetch_transactions` lanza `PaginationLimitExceededError` en lugar de bucle infinito
- [X] T019 Escribir y ejecutar un test dedicado de redacción de secretos en `tests/unit/connectors/test_ing.py` (usando `caplog` sobre toda la suite de esta funcionalidad): confirmar que el PEM de la clave privada de test, el JWT generado, y el valor completo de `session_id` de test nunca aparecen en ningún registro de log capturado, en ningún escenario (éxito o cualquiera de los fallos de las Fases 3-5) — verificación explícita de FR-015
- [X] T020 [P] Ejecutar la simulación completa de CI local: `pip-audit -r requirements.txt -r requirements-dev.txt && ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/ && pytest tests/ -v` — todo debe salir con código 0
- [X] T021 Añadir una sección breve "IT2 — Conector ING" al `quickstart.md` de la raíz del repositorio, referenciando `specs/002-ing-transactions-connector/quickstart.md` para la validación completa, y confirmando que los placeholders `app_id`/`private_key_path` de `eb-config.json` (creados en el paso 9 de IT1) ahora se usan de verdad en esta funcionalidad
- [X] T022 [P] Verificar que `git grep` no encuentra material real de clave privada RSA, cadenas JWT, ni valores de `session_id` en ningún fichero comiteado (extiende la verificación de credenciales de IT1, T021, a los ficheros nuevos de esta funcionalidad)

**Checkpoint**: Las 22 tareas completas. Todos los escenarios de aceptación del
spec pasan. La funcionalidad está lista para merge.

---

## Dependencias y Orden de Ejecución

### Dependencias de Fase

- **Fase 1 (Setup)**: Sin dependencias — empezar inmediatamente
- **Fase 2 (Foundational)**: Depende de la Fase 1 — bloquea las tres historias
- **Fase 3 (US1)**: Depende de la Fase 2; los tests (T005-T009) deben fallar antes de la implementación (T010-T013)
- **Fase 4 (US2)**: Depende de la Fase 3 — inserta su comprobación en el bucle de paginación que T013 ya implementó
- **Fase 5 (US3)**: Depende de la Fase 4 — extiende el mismo punto de mapeo de errores que T015 introdujo
- **Fase 6 (Polish)**: Depende de las Fases 3, 4 y 5

### Dependencias entre Historias de Usuario

- **US1 (P1)**: Depende solo de la Fase 2 (Foundational). Es el MVP.
- **US2 (P2)**: Depende de US1 — necesita el bucle de paginación de `fetch_transactions` ya existente para insertar `_check_session_usable`.
- **US3 (P3)**: Depende de US2 — extiende el mismo punto de mapeo de errores HTTP (comparten la función de mapeo introducida en T015).

### Dentro de cada Historia

```
US1:  T005,T006,T007,T008,T009 (tests, mismo fichero)  →  T010 → T011 → T013
                                                            T012 ──────────┘
US2:  T014 (test)  →  T015 (usa el bucle de T013)
US3:  T016 (test)  →  T017 (extiende el mapeo de errores de T015)
```

---

## Oportunidades de Paralelización

### Fase 1 y 2

```
T001 y T002 pueden ejecutarse en paralelo (directorios vs requirements.txt)
T003 y T004 pueden ejecutarse en paralelo (ficheros __init__.py vs conftest.py)
```

### Fase 6 (Polish)

```
T018 (pagination cap) y T020 (CI local) y T022 (git grep) pueden ejecutarse
en paralelo — ficheros y comandos independientes.
T019 y T021 no llevan [P]: T019 depende de que T010-T018 ya existan para
poder revisar sus logs; T021 es una edición de documentación aislada pero
secuencial respecto a la verificación de que todo lo demás ya funciona.
```

No hay oportunidades de paralelización dentro de los bloques de tests de cada
historia (T005-T009, T014, T016): todos escriben en el mismo fichero
`tests/unit/connectors/test_ing.py`.

---

## Estrategia de Implementación

### MVP (solo Historia de Usuario 1)

1. Completar Fase 1: Setup
2. Completar Fase 2: Foundational
3. Escribir los tests en fallo de US1 (T005-T009) — verificar que todos están en ROJO
4. Implementar US1 (T010-T013) — verificar que todos están en VERDE
5. **DETENERSE Y VALIDAR**: ejecutar `specs/002-ing-transactions-connector/quickstart.md` Parte A, Pasos 1-3

### Entrega Completa

1. MVP anterior ✅
2. Escribir el test en fallo de US2 (T014) — verificar ROJO
3. Implementar US2 (T015) — verificar VERDE
4. Escribir el test en fallo de US3 (T016) — verificar ROJO
5. Implementar US3 (T017) — verificar VERDE
6. Fase 6 Polish (T018-T022)

---

## Notas

- [P] = ficheros distintos, seguro de paralelizar
- Las excepciones del conector (`ConnectorConfigError`, `InvalidDateRangeError`,
  `ReauthorizationRequiredError`, `RateLimitExceededError`,
  `PaginationLimitExceededError`, `EnableBankingAPIError`) se definen todas en
  `src/banking/connectors/ing.py` — sin módulo de excepciones separado (YAGNI,
  mismo patrón que `ConfigurationError`/`DecryptionError` en IT1)
- Todas las funciones y métodos públicos DEBEN llevar anotaciones de tipo
  completas (mypy strict)
- Ningún `print()` en `ing.py` — usar `logging`, siguiendo la convención ya
  establecida en `secret_store.py`
- Ningún mensaje de excepción ni línea de log puede interpolar la clave
  privada, el JWT firmado, o el `session_id` completo (FR-015) — ver T019
- Comitear tras cada grupo lógico (tras Fase 1+2, tras tests+implementación de
  cada historia, tras Polish)
- `httpx` y `PyJWT` deben quedar pineados con versión exacta en
  `requirements.txt` antes de comitear cualquier código que los importe
