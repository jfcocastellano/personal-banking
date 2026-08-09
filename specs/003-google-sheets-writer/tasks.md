# Tareas: Escritor Genérico de Google Sheets

**Entrada**: Documentos de diseño desde `specs/003-google-sheets-writer/`

**Prerrequisitos**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Tests**: Los tests son **OBLIGATORIOS** según el Principio II (Test-First). Deben
escribirse antes del código de implementación y verificarse en fallo (Red) antes de
empezar cualquier implementación. El ciclo Red → Green → Refactor no es negociable.

**Organización**: US1 (P1) → US2 (P2) → US3 (P3). US2 extiende la función de
resolución de pestaña que US1 ya deja construida; US3 extiende el mismo mecanismo
de traducción de errores de US1 a dos nuevos sitios de llamada y añade las
aserciones de logging que las fases anteriores todavía no verificaban (mismo
patrón incremental que IT2).

## Formato: `[ID] [P?] [Story] Descripción`

- **[P]**: Paralelizable — ficheros distintos, sin dependencia bloqueante
- **[Story]**: Etiqueta de historia de usuario (US1, US2, US3)
- Todas las rutas son relativas a la raíz del repositorio
- Todos los tasks de test de esta funcionalidad escriben en el **mismo fichero**
  (`tests/unit/sheets/test_writer.py`); por eso ninguno lleva `[P]` entre sí

---

## Fase 1: Setup (Inicialización del Proyecto)

**Propósito**: Crear la estructura de directorios y añadir la dependencia nueva.
Sin lógica Python todavía.

- [X] T001 [P] Crear los directorios `src/banking/sheets/` y `tests/unit/sheets/`
- [X] T002 [P] Añadir `gspread` a `requirements.txt` con versión exacta pineada (ejecutar `pip install gspread`, luego `pip freeze` para capturar la versión exacta y sus dependencias transitivas, siguiendo la misma metodología que IT1/IT2)

**Checkpoint**: Directorios creados. `gspread` instalado y pineado.

---

## Fase 2: Foundational (Fixtures Compartidas)

**Propósito**: Fixtures de test reutilizables por las tres historias de usuario.
Ninguna lógica de negocio todavía — eso empieza en la Fase 3, después de que los
tests estén en Rojo.

**⚠️ CRÍTICO**: Ninguna historia de usuario puede empezar su implementación hasta
que esta fase esté completa.

- [X] T003 [P] Crear ficheros marcadores `__init__.py`: `src/banking/sheets/__init__.py`, `tests/unit/sheets/__init__.py`
- [X] T004 [P] Añadir fixture `google_sheets_credentials_in_store` a `tests/unit/conftest.py`: usa `mock_master_key` + `tmp_env_file` ya existentes, hace `monkeypatch.setenv("BANKING_ENV_FILE", str(tmp_env_file))` y `SecretStore(tmp_env_file).set("GOOGLE_SHEETS_CREDENTIALS", json.dumps(<dict de cuenta de servicio ficticia pero sintácticamente válida: type, project_id, private_key_id, private_key (PEM RSA generado con `rsa_private_key_pem`), client_email, client_id, token_uri>))`; devuelve el dict usado (mismo patrón que `session_id_in_store`, IT2)

**Checkpoint**: `pytest --collect-only` sigue sin errores de importación. Fixtures
listas para las tres historias.

---

## Fase 3: Historia de Usuario 1 — Sobrescribir una pestaña existente con datos nuevos (Prioridad: P1) 🎯 MVP

**Objetivo**: Dado un documento y una pestaña ya existente, `SheetsWriter.write()`
borra por completo su contenido previo y escribe la fila de cabeceras y las filas
de datos desde `A1`, emitiendo un log de éxito con pestaña, filas escritas y
duración. Incluye la autenticación por defecto (cuenta de servicio) y la
detección de documento inaccesible, ya que son necesarias para que la propia
ruta feliz funcione de extremo a extremo.

**Prueba independiente**: Ejecutar `pytest tests/unit/sheets/test_writer.py -k US1`
con `gspread.Client` mockeado (`Mock(spec=gspread.Client)`); todos los escenarios
de aceptación de la Historia de Usuario 1 del spec pasan.

### Tests para la Historia de Usuario 1 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T008

> **NOTA: Escribir TODOS los tests de esta sección primero. Ejecutar `pytest` y
> confirmar que CADA test falla con `ImportError` (el módulo `writer.py` no
> existe todavía) antes de escribir ninguna implementación (Principio II).**

- [X] T005 [US1] Escribir tests en fallo para el camino feliz en `tests/unit/sheets/test_writer.py`, inyectando `client=Mock(spec=gspread.Client)` con `client.open_by_key(...)` devolviendo un `Mock(spec=gspread.Spreadsheet)` cuyo `worksheet(tab_name)` devuelve un `Mock(spec=gspread.Worksheet)`: (1) pestaña con contenido previo → se llama `worksheet.clear()` y luego `worksheet.update(values=[headers, *rows])` (sin `range_name`, es decir, comenzando en `A1`); (2) `rows=[]` → `update` se llama igualmente con `values=[headers]`, sin lanzar error; (3) una fila de datos con más o menos columnas que `headers` → se pasa tal cual a `update`, sin validar ni rellenar (FR-006)
- [X] T006 [US1] Escribir test en fallo para el log de éxito en `tests/unit/sheets/test_writer.py` (usando `caplog`): una invocación exitosa con 2 filas de datos emite exactamente un registro de log `INFO` que contiene el nombre de la pestaña y el número de filas de datos escritas (2, sin contar la cabecera)
- [X] T007 [US1] Escribir tests en fallo para configuración y acceso inválidos en `tests/unit/sheets/test_writer.py`: (1) sin `client` inyectado y sin `GOOGLE_SHEETS_CREDENTIALS` en el `SecretStore` (fixture `google_sheets_credentials_in_store` no aplicada) → `SheetsConfigError` antes de cualquier llamada a `gspread`; (2) el valor almacenado no es JSON válido → `SheetsConfigError`; (3) el JSON almacenado le falta un campo requerido por la cuenta de servicio (p. ej. `private_key`) → `SheetsConfigError`; (4) con `client` inyectado, `client.open_by_key(...)` lanza `gspread.exceptions.SpreadsheetNotFound` → `SheetsAccessError` con un mensaje que identifica el documento como inaccesible, sin incluir el JSON de la cuenta de servicio

### Implementación para la Historia de Usuario 1

- [X] T008 [US1] Implementar en `src/banking/sheets/writer.py`: el alias de tipo `CellValue = str | int | float | bool | None`; las cuatro excepciones planas `SheetsConfigError`, `SheetsAccessError`, `SheetsQuotaExceededError`, `SheetsAPIError` (sin clase base compartida, mismo patrón que `ing.py`); y `_build_client() -> gspread.Client`, que lee `SecretStore().get("GOOGLE_SHEETS_CREDENTIALS")`, hace `json.loads()` y llama a `gspread.service_account_from_dict(info)`, envolviendo cualquier fallo (clave ausente, JSON inválido, credenciales rechazadas por `gspread`/`google-auth`) en `SheetsConfigError` — fully type-annotated
- [X] T009 [US1] Implementar en `src/banking/sheets/writer.py`: `_translate_api_error(exc: gspread.exceptions.APIError) -> Exception`, que devuelve `SheetsAccessError` si `exc.response.status_code` es `403` o `404`, `SheetsQuotaExceededError` si es `429`, o `SheetsAPIError` en cualquier otro caso; y `_open_spreadsheet(client: gspread.Client, document_id: str) -> gspread.Spreadsheet`, que llama a `client.open_by_key(document_id)`, capturando `gspread.exceptions.SpreadsheetNotFound` → `SheetsAccessError`, y `gspread.exceptions.APIError` → `_translate_api_error(exc)` — fully type-annotated
- [X] T010 [US1] Implementar en `src/banking/sheets/writer.py`: `_prepare_worksheet(spreadsheet: gspread.Spreadsheet, tab_name: str, headers: list[CellValue]) -> gspread.Worksheet` — camino "ya existe" únicamente por ahora: llama a `spreadsheet.worksheet(tab_name)`, y si la encuentra, llama a `worksheet.clear()` antes de devolverla (el camino "no existe", `gspread.exceptions.WorksheetNotFound`, se deja sin capturar en esta tarea — lo añade la Historia de Usuario 2) — fully type-annotated
- [X] T011 [US1] Implementar `SheetsWriter.__init__(self, client: gspread.Client | None = None)` y `write(self, document_id: str, tab_name: str, headers: list[CellValue], rows: list[list[CellValue]]) -> None` en `src/banking/sheets/writer.py`: mide el tiempo con `time.monotonic()`, obtiene el cliente (inyectado o `_build_client()`, T008), abre el documento (`_open_spreadsheet`, T009), resuelve la pestaña (`_prepare_worksheet`, T010), llama a `worksheet.update(values=[headers, *rows])`; en éxito, emite un log `INFO` con pestaña, número de filas de datos y duración; en fallo (`SheetsConfigError`, `SheetsAccessError`, `SheetsQuotaExceededError`, `SheetsAPIError`), emite un log `ERROR` con pestaña, categoría del fallo y motivo (sin el JSON de la cuenta de servicio, FR-012) antes de relanzar la excepción — fully type-annotated

**Checkpoint**: Todos los tests de la Fase 3 pasan. `SheetsWriter.write()` funciona
de extremo a extremo con `gspread` mockeado para el caso de pestaña ya existente,
cubriendo el camino feliz, filas vacías/irregulares, el log de éxito, y los
errores de configuración y de acceso.

---

## Fase 4: Historia de Usuario 2 — Crear automáticamente la pestaña de destino (Prioridad: P2)

**Objetivo**: Cuando la pestaña solicitada no existe en el documento,
`SheetsWriter.write()` la crea automáticamente y escribe los datos en ella, sin
intentar borrarla primero; cuando ya existe, no intenta crearla de nuevo.

**Prueba independiente**: Mockear `spreadsheet.worksheet(tab_name)` para que
lance `gspread.exceptions.WorksheetNotFound`; confirmar que se llama a
`add_worksheet` y que el resultado final contiene cabecera y filas desde `A1`,
igual que en la Historia de Usuario 1.

### Tests para la Historia de Usuario 2 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T013

- [X] T012 [US2] Escribir tests en fallo en `tests/unit/sheets/test_writer.py`: (1) `spreadsheet.worksheet(tab_name)` lanza `gspread.exceptions.WorksheetNotFound` → se llama a `spreadsheet.add_worksheet(title=tab_name, rows=1, cols=max(len(headers), 1))`, y sobre la pestaña devuelta se llama a `update(values=[headers, *rows])`, **sin** llamar a `clear()` (nada que borrar); (2) cuando la pestaña ya existe (mismo mock que T005), `add_worksheet` **no** se llama — no se crea una pestaña duplicada (verificación de regresión sobre el camino de la Historia 1)

### Implementación para la Historia de Usuario 2

- [X] T013 [US2] Extender `_prepare_worksheet` (T010) en `src/banking/sheets/writer.py`: capturar `gspread.exceptions.WorksheetNotFound` alrededor de `spreadsheet.worksheet(tab_name)` y, en ese caso, llamar a `spreadsheet.add_worksheet(title=tab_name, rows=1, cols=max(len(headers), 1))` y devolver la pestaña nueva en lugar de relanzar la excepción

**Checkpoint**: Todos los tests de las Fases 3-4 pasan. Las pestañas se crean o
se sobrescriben correctamente según corresponda.

---

## Fase 5: Historia de Usuario 3 — Observabilidad de cada escritura (Prioridad: P3)

**Objetivo**: Toda invocación, éxito o fallo (incluyendo las dos categorías de
fallo que todavía no tienen cobertura de extremo a extremo — cuota excedida y
error de API genérico), deja un log suficiente para diagnosticar sin inspeccionar
código, con una duración medida de forma fiable.

**Prueba independiente**: Forzar cada una de las cuatro categorías de fallo
(`SheetsConfigError`, `SheetsAccessError`, `SheetsQuotaExceededError`,
`SheetsAPIError`) y confirmar, con `caplog`, que cada una produce un log `ERROR`
distintivo sin datos sensibles; forzar un éxito y confirmar que el log `INFO`
incluye una duración numérica coherente.

### Tests para la Historia de Usuario 3 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T016

- [X] T014 [US3] Escribir tests en fallo en `tests/unit/sheets/test_writer.py` para las dos categorías de fallo aún no ejercitadas de extremo a extremo: (1) `worksheet.update(...)` (o `client.open_by_key(...)`) lanza `gspread.exceptions.APIError` con `response.status_code == 429` → `SheetsQuotaExceededError`, con un log `ERROR` que identifica la pestaña y menciona explícitamente un límite de cuota; (2) el mismo punto de llamada lanza `gspread.exceptions.APIError` con `response.status_code == 500` → `SheetsAPIError`, con su propio log `ERROR` distinto del anterior; en ambos casos, usando `caplog`, confirmar que el JSON de la cuenta de servicio (fixture `google_sheets_credentials_in_store`) no aparece en ningún registro capturado
- [X] T015 [US3] Escribir tests en fallo en `tests/unit/sheets/test_writer.py`: (1) reutilizando los casos de fallo de configuración y acceso ya implementados en la Fase 3 (T007), confirmar con `caplog` que cada uno también emite un log `ERROR` con la pestaña objetivo y una categoría distinguible (no solo la excepción, también el log), y que el JSON de la cuenta de servicio (fixture `google_sheets_credentials_in_store`) no aparece en ningún registro capturado — *cierra la brecha de que T007 solo verificaba la excepción, ni el log de fallo ni la ausencia del secreto en él*; (2) en un caso de éxito con 3 filas de datos, confirmar que el log `INFO` incluye un campo de duración numérico y positivo (monkeypatcheando `time.monotonic` con una secuencia controlada de dos valores) y que el conteo de filas registrado es exactamente 3

### Implementación para la Historia de Usuario 3

- [X] T016 [US3] Extender en `src/banking/sheets/writer.py` el uso de `_translate_api_error` (T009) para envolver también las llamadas a `worksheet.update(...)` y `spreadsheet.add_worksheet(...)` dentro de `write()` (T011), no solo `client.open_by_key(...)` — cierra la cobertura de `SheetsQuotaExceededError`/`SheetsAPIError` en los sitios de llamada que faltaban para que T014 pase

**Checkpoint**: Todos los tests de las Fases 3-5 pasan. Las tres historias de
usuario del spec están implementadas y son verificables de forma independiente.

---

## Fase 6: Polish & Validación

**Propósito**: Verificación final transversal — cumplimiento de la redacción de
secretos en logs (FR-012), consistencia documental, y validación completa de la
CI local.

- [X] T017 [P] Ejecutar la simulación completa de CI local: `pip-audit -r requirements.txt -r requirements-dev.txt && ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/ && pytest tests/ -v` — todo debe salir con código 0
- [X] T018 [P] Verificar que `git grep` no encuentra material real de JSON de cuenta de servicio (p. ej. `"private_key": "-----BEGIN`) en ningún fichero comiteado (extiende la verificación de credenciales de IT1/IT2 a los ficheros nuevos de esta funcionalidad)
- [X] T019 [P] Añadir una sección breve "IT3 — Escritor de Google Sheets" al `quickstart.md` de la raíz del repositorio, referenciando `specs/003-google-sheets-writer/quickstart.md` para la validación completa, y confirmando que el placeholder `GOOGLE_SHEETS_CREDENTIALS=enc:placeholder` de `.env.example` (creado en IT1) ahora se usa de verdad en esta funcionalidad
- [X] T020 [P] Actualizar `docs/context.md` (tabla de librerías principales) para reflejar que `google-auth` se usa transitivamente vía `gspread.service_account_from_dict()` y no se importa directamente en este componente (nota ya documentada en `plan.md` → Constitution Check)

**Checkpoint**: Las 20 tareas completas. Todos los escenarios de aceptación del
spec pasan. La funcionalidad está lista para merge.

---

## Dependencias y Orden de Ejecución

### Dependencias de Fase

- **Fase 1 (Setup)**: Sin dependencias — empezar inmediatamente
- **Fase 2 (Foundational)**: Depende de la Fase 1 — bloquea las tres historias
- **Fase 3 (US1)**: Depende de la Fase 2; los tests (T005-T007) deben fallar antes de la implementación (T008-T011)
- **Fase 4 (US2)**: Depende de la Fase 3 — extiende `_prepare_worksheet` (T010) que US1 ya implementó
- **Fase 5 (US3)**: Depende de la Fase 4 — extiende `_translate_api_error` (T009) a dos sitios de llamada más y añade aserciones de log sobre excepciones que US1/US2 ya lanzan
- **Fase 6 (Polish)**: Depende de las Fases 3, 4 y 5

### Dependencias entre Historias de Usuario

- **US1 (P1)**: Depende solo de la Fase 2 (Foundational). Es el MVP.
- **US2 (P2)**: Depende de US1 — necesita `_prepare_worksheet` ya existente para insertar la rama de creación.
- **US3 (P3)**: Depende de US2 — extiende el mismo mecanismo de traducción de errores que T009 introdujo, a los sitios de llamada que T013 (US2) también usa.

### Dentro de cada Historia

```
US1:  T005,T006,T007 (tests, mismo fichero)  →  T008 → T009 → T010 → T011
US2:  T012 (test)  →  T013 (extiende T010)
US3:  T014,T015 (tests)  →  T016 (extiende T009, usado dentro de T011/T013)
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
T017 (CI local), T018 (git grep) T019 (quickstart raíz) y T020 (docs/context.md)
pueden ejecutarse en paralelo — ficheros y comandos independientes.
```

No hay oportunidades de paralelización dentro de los bloques de tests de cada
historia (T005-T007, T012, T014-T015): todos escriben en el mismo fichero
`tests/unit/sheets/test_writer.py`.

---

## Parallel Example: Fase 1

```bash
# Lanzar juntas las dos tareas de Setup:
Task: "Crear los directorios src/banking/sheets/ y tests/unit/sheets/"
Task: "Añadir gspread a requirements.txt con versión exacta pineada"
```

---

## Estrategia de Implementación

### MVP (solo Historia de Usuario 1)

1. Completar Fase 1: Setup
2. Completar Fase 2: Foundational
3. Escribir los tests en fallo de US1 (T005-T007) — verificar que todos están en ROJO
4. Implementar US1 (T008-T011) — verificar que todos están en VERDE
5. **DETENERSE Y VALIDAR**: ejecutar `specs/003-google-sheets-writer/quickstart.md` Parte A, Pasos 1-3

### Entrega Completa

1. MVP anterior ✅
2. Escribir el test en fallo de US2 (T012) — verificar ROJO
3. Implementar US2 (T013) — verificar VERDE
4. Escribir los tests en fallo de US3 (T014-T015) — verificar ROJO
5. Implementar US3 (T016) — verificar VERDE
6. Fase 6 Polish (T017-T020)

---

## Notas

- [P] = ficheros distintos, seguro de paralelizar
- Las excepciones del componente (`SheetsConfigError`, `SheetsAccessError`,
  `SheetsQuotaExceededError`, `SheetsAPIError`) se definen todas en
  `src/banking/sheets/writer.py` — sin módulo de excepciones separado (YAGNI,
  mismo patrón que `ing.py`, IT2)
- Todas las funciones y métodos públicos DEBEN llevar anotaciones de tipo
  completas (mypy strict)
- Ningún `print()` en `writer.py` — usar `logging`, siguiendo la convención ya
  establecida en `secret_store.py`/`ing.py`
- Ningún mensaje de excepción ni línea de log puede interpolar el JSON de la
  cuenta de servicio ni ningún token derivado de él (FR-012) — ver T014/T015
- `WorksheetNotFound` nunca se traduce a una excepción propia — es la señal
  interna para crear la pestaña (FR-003), no un fallo
- Comitear tras cada grupo lógico (tras Fase 1+2, tras tests+implementación de
  cada historia, tras Polish)
- `gspread` debe quedar pineado con versión exacta en `requirements.txt` antes
  de comitear cualquier código que lo importe
- SC-006 (< 30 s por invocación) es un SLO operacional heredado de la
  constitución; no hay un task que lo mida contra `gspread` real, ya que los
  tests mockeados completan instantáneamente y no ejercitan el umbral de
  forma significativa. Se valida manualmente en `quickstart.md` Parte B
  (Paso 7) contra un documento real — no está automatizado en CI.
