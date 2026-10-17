# Tareas: Notificación de Errores por Email

**Entrada**: Documentos de diseño desde `specs/006-email-failure-notifications/`

**Prerrequisitos**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Tests**: Los tests son **OBLIGATORIOS** según el Principio II (Test-First). Deben
escribirse antes del código de implementación y verificarse en fallo (Red) antes de
empezar cualquier implementación. El ciclo Red → Green → Refactor no es negociable.

**Organización**: US1 (P1) → US2 (P2) → US3 (P3). Las tres historias comparten el
módulo `banking.notify` y el enganche en `banking.cli.sync`, que se construyen de
forma incremental: US1 añade el email de fallo parcial (rama `PARTIAL_FAILURE`);
US2 añade los emails de fallo total y de fallo de escritura, incluido el caso
combinado; US3 garantiza el silencio absoluto en el camino feliz (cero
notificaciones, cero configuración leída). Cada fase debe dejar en verde, sin
regresiones, todo lo construido por las fases anteriores.

## Formato: `[ID] [P?] [Story] Descripción`

- **[P]**: Paralelizable — ficheros distintos, sin dependencia bloqueante
- **[Story]**: Etiqueta de historia de usuario (US1, US2, US3)
- Todas las rutas son relativas a la raíz del repositorio

---

## Fase 1: Setup (Inicialización de la funcionalidad)

**Propósito**: Confirmar que la funcionalidad no introduce dependencias nuevas y
alinear la plantilla de configuración con las cinco claves decididas en
`research.md` Decisión 3.

- [x] T001 [P] Confirmar que no hace falta pinear nada: el futuro `src/banking/notify.py` solo importará `smtplib`, `email.message.EmailMessage`, `logging`, `dataclasses`, `enum` y `datetime` (todo stdlib) — `requirements.txt`, `requirements-dev.txt` y `[project].dependencies` de `pyproject.toml` quedan **sin cambios**, y `tests/unit/test_dependencies.py` sigue pasando sin tocarlo (Anti-patrón #10, Principio VII)
- [x] T002 [P] Actualizar `.env.example`: sustituir los placeholders heredados de IT1 (`GMAIL_SMTP_PASSWORD`, `GMAIL_FROM`, `GMAIL_TO`) por las cinco claves de `research.md` Decisión 3 — `SMTP_HOST=enc:placeholder`, `SMTP_PORT=enc:placeholder`, `SMTP_USER=enc:placeholder`, `SMTP_PASSWORD=enc:placeholder`, `NOTIFY_EMAIL_TO=enc:placeholder` — manteniendo intactos los bloques de Enable Banking, Google Sheets y `LOG_LEVEL=INFO`

**Checkpoint**: Cero dependencias nuevas declaradas; `.env.example` documenta
exactamente las cinco claves que leerá `_load_config()`.

---

## Fase 2: Foundational (Prerrequisitos bloqueantes)

**Propósito**: Proveer la infraestructura de test que garantiza cero red real, el
contexto estructurado en las excepciones del pipeline (FR-009) y el esqueleto del
notificador con carga de configuración y transporte SMTP (`EmailConfig`,
`DeliveryStatus`, `EmailNotifier.__init__`, `_load_config`, `_send`). Ninguna
historia puede empezar hasta que esta fase esté completa.

**⚠️ CRÍTICO**: Ninguna historia de usuario puede empezar su implementación hasta
que esta fase esté completa.

### Tests para Foundational ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T007

- [x] T003 [P] Añadir en `tests/unit/conftest.py`: (a) fixture `smtp_config_in_store` que, siguiendo el patrón de `google_sheets_credentials_in_store`, cifra las cinco claves (`SMTP_HOST=smtp.example.com`, `SMTP_PORT=465`, `SMTP_USER=bot@example.com`, `SMTP_PASSWORD=app-password-1234`, `NOTIFY_EMAIL_TO=owner@example.com`) en un `.env` temporal vía `SecretStore` apuntado por `BANKING_ENV_FILE` y devuelve el dict; (b) fixture **autouse** `no_real_smtp` que sustituye `smtplib.SMTP_SSL` y `smtplib.SMTP` por dobles que lanzan `RuntimeError("real SMTP connection attempted")` si alguien los invoca — hace fallar cualquier test que intente un envío real (FR-010, Principio III) y puede ser sobrescrita dentro de un test concreto con `monkeypatch.setattr` sobre el mismo atributo
- [x] T004 [P] Escribir tests en fallo en `tests/unit/test_sync.py`: (1) en el escenario de fallo total ya existente, `AllBanksFailedError` expone `exc.outcomes` con los cuatro `BankOutcome` fallidos en el orden ING/Revolut/MyInvestor/Sabadell y `exc.tab_name == "2026-08"`; (2) en el escenario de fallo de `SheetsWriter` ya existente, `SheetsSyncError` expone `exc.outcomes` con los cuatro `BankOutcome` exitosos y `exc.tab_name == "2026-08"`; (3) el texto de `str(exc)` no cambia respecto a IT5 (sigue agregando `"<banco>: <motivo>"` en fallo total y sigue siendo el `str()` del error del writer en fallo de Sheets); (4) retrocompatibilidad: `AllBanksFailedError("x")` y `SheetsSyncError("x")` se construyen sin contexto y dejan `outcomes is None` y `tab_name is None` (research.md Decisión 6)
- [x] T005 [P] Escribir tests en fallo en `tests/unit/test_notify.py` (nuevo fichero): `EmailConfig` es un `dataclass` congelado con `host`/`port`/`user`/`password`/`to_address`; `DeliveryStatus` expone `SENT`/`SKIPPED`/`FAILED`; construir `EmailNotifier(store=Mock(spec=SecretStore), smtp_factory=Mock())` no toca la red ni lee secretos (la carga es perezosa, en el primer envío); `_load_config()` devuelve la `EmailConfig` completa (incluido `port` como `int`) cuando las cinco claves están en el store, y `None` parametrizado por: cada una de las cinco claves ausente y `SMTP_PORT` no entero (`"abc"`), sin emitir ningún `ERROR` (solo `WARNING` sin secretos, FR-007)
- [x] T006 [P] Escribir tests en fallo en `tests/unit/test_notify.py` para la ruta de transporte: con `smtp_factory` inyectada devolviendo `Mock(spec=smtplib.SMTP)`, la fábrica recibe la `EmailConfig` resuelta y se invoca `login(user, password)`, `send_message(<mensaje>)` y `quit()` en ese orden; éxito → `DeliveryStatus.SENT` y un log `INFO` con destinatario y duración del envío; parametrizado sobre `smtplib.SMTPAuthenticationError`, `smtplib.SMTPException` y `OSError` lanzados por `send_message` o por `login` → `DeliveryStatus.FAILED` **sin propagar la excepción**, log `ERROR` con el tipo y motivo, conexión cerrada igualmente (`quit()` o `close()` invocado) y ningún registro capturado con `caplog` contiene el valor de `SMTP_PASSWORD` (FR-006/FR-008, Principio IV)

### Implementación para Foundational

- [x] T007 Implementar `src/banking/notify.py`: `EmailConfig` (dataclass `frozen=True`), `DeliveryStatus` (`enum.Enum` con `SENT`/`SKIPPED`/`FAILED`), `_SMTP_TIMEOUT_SECONDS: int = 30` (SLO de 60s, research.md Decisión 1 y quickstart § Presupuesto de rendimiento), `EmailNotifier.__init__(store: SecretStore | None = None, smtp_factory: Callable[[EmailConfig], smtplib.SMTP] | None = None) -> None` (por defecto `SecretStore()` y `_default_smtp_factory` que crea `smtplib.SMTP_SSL(config.host, config.port, timeout=_SMTP_TIMEOUT_SECONDS)`), y `_load_config() -> EmailConfig | None` leyendo `SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`NOTIFY_EMAIL_TO` del `SecretStore` con aviso `logger.warning` sin secretos cuando falte cualquiera o el puerto no sea entero — solo `logging`, nunca `print()` (Anti-patrón #6); totalmente anotado para `mypy --strict` (T005 debe pasar en verde)
- [x] T008 Implementar en `src/banking/notify.py` la ruta de envío: `_send(message: EmailMessage) -> DeliveryStatus` que llama a `_load_config()` (`None` → `WARNING` + `SKIPPED`), abre la conexión con la fábrica, hace `login`/`send_message`/`quit` dentro de `try/except` (cualquier excepción → `logger.error` con tipo y motivo, sin secretos, `finally` para cerrar el socket → `FAILED`), más `notify_failure(outcomes: list[BankOutcome], sheets_error: str | None, tab_name: str, duration_seconds: float) -> DeliveryStatus` que **nunca lanza**, construye el `EmailMessage` (cabeceras `From`/`To`/`Subject` + cuerpo `text/plain; charset="utf-8"`) delegando en `_build_subject`/`_build_body` (stubs con la firma final; el contenido completo llega en T013/T018) y devuelve el `DeliveryStatus` de `_send` (T006 debe pasar en verde)
- [x] T009 Extender en `src/banking/sync.py` las excepciones del pipeline con contexto estructurado: `AllBanksFailedError(message, *, outcomes: list[BankOutcome] | None = None, tab_name: str | None = None)` y `SheetsSyncError(message, *, outcomes: list[BankOutcome] | None = None, tab_name: str | None = None)`, y rellenarlos en `run_sync()` en sus dos puntos de lanzamiento — fallo total: los cuatro `outcomes` + `tab_name`; fallo de Sheets: los `outcomes` ya calculados (incluidos los `BankOutcome` fallidos de bancos que no respondieron) + `tab_name` — sin cambiar `str(exc)` ni el comportamiento existente (T004 debe pasar en verde, resto de `test_sync.py` sin regresión)

**Checkpoint**: T001-T009 en verde. Existe el armazón del notificador
(configuración + transporte, sin contenido de email todavía) y las excepciones
del pipeline llevan `outcomes`/`tab_name` de forma retrocompatible. Los tests
tienen garantía activa de cero conexiones SMTP reales.

---

## Fase 3: Historia de Usuario 1 — Email cuando la sincronización falla parcialmente (Prioridad: P1) 🎯 MVP

**Objetivo**: Cuando una ejecución termina con al menos un banco fallido y al menos
uno sincronizado, el propietario recibe **un único email agregado** cuyo asunto
clasifica el fallo parcial y cuyo cuerpo lista los bancos fallidos con su motivo y
los exitosos con su recuento, en español y sin secretos. El envío ocurre dentro
del flujo del comando, antes de devolver el exit code, que sigue siendo `3` (o `4`
si la entrega falla).

**Prueba independiente**: `pytest tests/unit/test_notify.py tests/unit/test_cli_sync.py -k "parcial or partial" -q`
con `smtp_factory` devolviendo `Mock(spec=smtplib.SMTP)` y `notifier=Mock(spec=EmailNotifier)`
en el CLI: confirmar un único `send_message`, el asunto/cuerpo esperados, y
`notify_failure` invocado exactamente una vez con los datos del `SyncSummary`.

### Tests para la Historia de Usuario 1 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T013

- [ ] T010 [US1] Escribir test en fallo en `tests/unit/test_notify.py`: con `smtp_config_in_store` y `smtp_factory` inyectada, `notify_failure(outcomes=<3 exitosos con 3/2/1 movimientos + Revolut fallido con "sesión expirada">, sheets_error=None, tab_name="2026-08", duration_seconds=3.42)` devuelve `DeliveryStatus.SENT` y produce: (1) asunto exacto `Sincronización parcial: 3/4 bancos — fallo en 2026-08`; (2) `From` == `SMTP_USER`, `To` == `NOTIFY_EMAIL_TO`; (3) cuerpo `text/plain` con `charset="utf-8"` que contiene `Fecha:`, `Pestaña: 2026-08`, `Duración: 3.42s`, una línea `- ING España: 3 movimientos` por banco exitoso y una línea `- Revolut: FALLÓ — sesión expirada`; (4) ni asunto, ni cuerpo, ni cabeceras contienen el valor de `SMTP_PASSWORD` (FR-008, contracts/notify-interface.md)
- [ ] T011 [US1] Escribir test en fallo en `tests/unit/test_notify.py` (US1 Escenario de Aceptación 2): dos bancos fallidos con motivos distintos (`RateLimitExceededError: límite alcanzado`, `EnableBankingAPIError: 500`) y dos exitosos → **un solo** email (`send_message` invocado exactamente una vez, `notify_failure` devuelve `SENT`), asunto `Sincronización parcial: 2/4 bancos — fallo en 2026-08` y cuerpo con ambos motivos y ambos recuentos
- [ ] T012 [P] [US1] Escribir tests en fallo en `tests/unit/test_cli_sync.py`: `handle(args, notifier=Mock(spec=EmailNotifier))` con `run_sync` sustituido por un doble que devuelve un `SyncSummary` de `PARTIAL_FAILURE` conocido → (1) `notify_failure` se invoca exactamente una vez con `outcomes=summary.outcomes`, `sheets_error=None`, `tab_name="2026-08"` y `duration_seconds=3.42`; (2) con `notify_failure.return_value = DeliveryStatus.SENT` el resumen IT5 se imprime en **stdout** y `handle()` devuelve `3`; (3) con `DeliveryStatus.SKIPPED` devuelve `3` sin línea extra en stderr; (4) con `DeliveryStatus.FAILED` devuelve `4`, el resumen sigue impreso en stdout y stderr contiene la línea `ERROR (notificación): no se pudo enviar el email de aviso — <motivo>` (FR-006, contracts/cli-sync-interface.md)

### Implementación para la Historia de Usuario 1

- [ ] T013 [US1] Implementar en `src/banking/notify.py` el contenido del email de fallo parcial: `_build_subject(outcomes, sheets_error, tab_name) -> str` (tabla de `research.md` Decisión 7) y `_build_body(outcomes, sheets_error, tab_name, duration_seconds) -> str` (formato de `contracts/notify-interface.md`), con `_count_succeeded(outcomes) -> int` como helper; literales en español reutilizando los del CLI de IT5 (`FALLÓ —`, `movimientos`), rellenando el `EmailMessage` con `From`/`To` y `set_content(cuerpo, subtype="plain", charset="utf-8")` (T010, T011 en verde)
- [ ] T014 [US1] Extender `src/banking/cli/sync.py`: nueva firma `handle(args: argparse.Namespace, notifier: EmailNotifier | None = None) -> int`; helper `_notify_and_exit(notifier: EmailNotifier, outcomes: list[BankOutcome], sheets_error: str | None, tab_name: str, duration_seconds: float) -> int | None` que devuelve `4` e imprime en stderr `ERROR (notificación): no se pudo enviar el email de aviso — <motivo>` solo cuando el `DeliveryStatus` es `FAILED`, y `None` en `SENT`/`SKIPPED`; enganche en la rama `PARTIAL_FAILURE` **antes** de devolver `3` (FR-013); `print` sigue siendo exclusivo de este módulo (Anti-patrón #6); el módulo instancia `EmailNotifier()` solo dentro de `_notify_and_exit` cuando `notifier` no se inyectó (T012 en verde)

**Checkpoint**: T001-T014 en verde. Un fallo parcial envía un email con detalle
completo y el exit code es `3` (o `4` si la entrega falla), sin regresión en las
ramas de IT5.

---

## Fase 4: Historia de Usuario 2 — Email cuando la sincronización falla por completo (Prioridad: P2)

**Objetivo**: Cuando los cuatro bancos fallan, o cuando los bancos responden pero
la escritura en Google Sheets falla — incluido el caso combinado de ambos — el
propietario recibe **un único email** que identifica el error general, distingue
el fallo de escritura de un fallo de banco y agrega los motivos por banco
disponibles. `run_sync()` sigue lanzando (`AllBanksFailedError` /
`SheetsSyncError`), por lo que el contexto se toma de `exc.outcomes` /
`exc.tab_name`.

**Prueba independiente**: `pytest tests/unit/test_notify.py tests/unit/test_cli_sync.py -k "total or sheets" -q`
con `run_sync` lanzando cada excepción (con y sin `outcomes`) y el notificador
mockeado: confirmar un único email por ejecución, el asunto de la tabla de
`research.md` Decisión 7, y exit code `1`/`2` (o `4` si la entrega falla).

### Tests para la Historia de Usuario 2 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T018

- [ ] T015 [US2] Escribir test en fallo en `tests/unit/test_notify.py` (US2 Escenario de Aceptación 1): cuatro `BankOutcome` fallidos con motivos distintos y `sheets_error=None` → `SENT`, un único `send_message`, asunto exacto `Sincronización fallida: los 4 bancos fallaron — 2026-08`, cuerpo con los cuatro motivos y sin líneas de recuento
- [ ] T016 [US2] Escribir tests en fallo en `tests/unit/test_notify.py` (US2 Escenario 2 / FR-002): (1) `sheets_error="SheetsAccessError: sin permisos"` con `outcomes` todos exitosos → asunto `Sincronización fallida: error escribiendo en Google Sheets — 2026-08` y cuerpo con la línea `ERROR (Sheets): sin permisos` como causa principal, sin línea `FALLÓ —` de banco; (2) caso combinado, dos `BankOutcome` fallidos + `sheets_error="SheetsQuotaExceededError: cuota"` → **un único** email con asunto `Sincronización fallida: error escribiendo en Google Sheets (con fallos de banco) — 2026-08`, la causa de Sheets **y** los dos motivos por banco
- [ ] T017 [P] [US2] Escribir tests en fallo en `tests/unit/test_cli_sync.py` (contracts/cli-sync-interface.md § Contexto pasado al notificador): (1) `run_sync` lanza `AllBanksFailedError(...)` con `outcomes` (cuatro fallidos) y `tab_name="2026-08"` → stderr con el formato IT5, `notify_failure` invocado exactamente una vez con `outcomes=exc.outcomes`, `sheets_error=None`, `tab_name="2026-08"`, `duration_seconds=0.0`, y retorno `1` con `SENT`/`SKIPPED` o `4` con `FAILED`; (2) `run_sync` lanza `SheetsSyncError(...)` con `outcomes` y `tab_name` → `notify_failure` con `sheets_error=str(exc)` y esos `outcomes`, retorno `2` o `4`; (3) invocador sin contexto (`outcomes is None`, `tab_name is None`) → `notify_failure` recibe `outcomes=[]` y `tab_name` de la ejecución en curso, sin excepción ni cambio de exit code (fallback defensivo de `research.md` Decisión 6)

### Implementación para la Historia de Usuario 2

- [ ] T018 [US2] Extender en `src/banking/notify.py` `_build_subject`/`_build_body` con las ramas de fallo total, fallo de Sheets puro y caso combinado (tabla de `research.md` Decisión 7 y cuerpo de `contracts/notify-interface.md`), incluida la línea `ERROR (Sheets): <motivo>` como causa principal y las líneas por banco cuando `outcomes` está disponible; comportamiento equivalente para `outcomes` vacío + `sheets_error` no nulo (fallo de Sheets puro) (T015, T016 en verde)
- [ ] T019 [US2] Refactorizar `src/banking/cli/sync.py`: extraer `_finish_total_failure(notifier, exc) -> int` y `_finish_sheets_failure(notifier, exc, tab_name) -> int` (impresión IT5 + notificación + `4` si `FAILED`) y hacer que `handle()` los use, de modo que su complejidad ciclomática se mantenga ≤ 10 (Principio VI, `plan.md` § Complexity Tracking) (T017 en verde, sin regresión en T012)

**Checkpoint**: T001-T019 en verde. Los cuatro desenlaces notificables de IT5
(parcial, total, fallo de Sheets, combinado) producen un email correcto y los
exit codes `1`/`2`/`3` (o `4` si la entrega falla) siguen intactos.

---

## Fase 5: Historia de Usuario 3 — Ningún email cuando todo va bien (Prioridad: P3)

**Objetivo**: En una ejecución con éxito completo (incluido el caso de un banco o
del mes entero con cero movimientos) el notificador **no se invoca**, no se lee
configuración SMTP y el exit code sigue siendo `0`, de forma que cualquier email
recibido signifique siempre que hay un problema.

**Prueba independiente**: `pytest tests/unit/test_cli_sync.py -k "success or exito" -q`
con `run_sync` devolviendo `FULL_SUCCESS` y `notifier=Mock(spec=EmailNotifier)`:
confirmar cero llamadas a `notify_failure` y exit code `0`.

### Tests para la Historia de Usuario 3 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T021

- [ ] T020 [P] [US3] Escribir tests en fallo en `tests/unit/test_cli_sync.py` (FR-003): (1) `FULL_SUCCESS` con los cuatro bancos exitosos y `notifier` mockeado → `notify_failure` **cero** llamadas, resumen en stdout y retorno `0`; (2) `FULL_SUCCESS` con todos los `rows_written=0` (US3 Escenario 2) → igualmente cero llamadas y retorno `0`; (3) en éxito completo no se construye ningún `EmailNotifier` ni se consulta el `SecretStore`: `monkeypatch.setattr(cli_sync, "EmailNotifier", <doble que falla si se instancia>)` y `handle(args)` sin `notifier` inyectado sigue devolviendo `0`

### Implementación para la Historia de Usuario 3

- [ ] T021 [US3] Garantizar en `src/banking/cli/sync.py` que la construcción del notificador y la carga de configuración ocurren **solo** dentro de las ramas de fallo (`_finish_total_failure`, `_finish_sheets_failure` y la rama `PARTIAL_FAILURE`), de forma perezosa: el camino de `FULL_SUCCESS` no crea `EmailNotifier` ni toca el `SecretStore` (T020 en verde)

**Checkpoint**: T001-T021 en verde. Éxito completo ⇒ cero emails, cero
configuración leída, exit `0`; las tres historias son verificables de forma
independiente y sin regresión entre sí.

---

## Fase 6: Polish & Validación

**Propósito**: Verificación final transversal y consistencia documental.

- [ ] T022 [P] Ejecutar la simulación completa de CI local: `pip-audit -r requirements.txt -r requirements-dev.txt && ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/ && pytest tests/ -q` — todo debe salir con código 0
- [ ] T023 [P] Auditoría de secretos y de red: `git grep -In` sin material real (contraseña de aplicación, `SMTP_PASSWORD` con valor, JWT, `session_id` completo, JSON de cuenta de servicio) en `src/banking/notify.py`, `src/banking/sync.py`, `src/banking/cli/sync.py`, `tests/unit/test_notify.py` y `.env.example`; y confirmar que toda aparición de `smtplib.SMTP`/`smtplib.SMTP_SSL` en `tests/` está tras una fábrica inyectada o bajo `Mock(spec=smtplib.SMTP)` (FR-010, Principio III)
- [ ] T024 [P] Actualizar `docs/context.md`: fila IT6 de la tabla "Estado actual de la implementación" → **Implementada**, refrescar `Última actualización`, y precisar en la sección de Notificaciones las cinco claves de configuración (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO`) y los cinco exit codes (`0`-`4`, con `4` = fallo de entrega)
- [ ] T025 [P] Añadir al `quickstart.md` de la raíz del repositorio una sección breve "IT6 — Notificación de errores por email" que referencie `specs/006-email-failure-notifications/quickstart.md`, con el alta de las cinco claves vía `python -m banking secrets set ...` y una nota de migración desde los placeholders antiguos `GMAIL_*`
- [x] T026 [P] Actualizar el bloque "➡️ Siguiente paso" de `specs/006-email-failure-notifications/plan.md`: `tasks.md` ya existe y el siguiente paso es `/speckit-implement` (sustituir la referencia a `/speckit-tasks`)
- [ ] T027 Ejecutar la porción automatizada de `specs/006-email-failure-notifications/quickstart.md` (sección "Validación automatizada") y confirmar que `test_cli_sync.py` cubre los cinco códigos de salida (`0`/`1`/`2`/`3`/`4`) y que `test_notify.py` cubre los tres estados de entrega (`SENT`/`SKIPPED`/`FAILED`), incluido el caso combinado banco+escritura; la validación manual contra Gmail real y la medición de SC-006 quedan documentadas como pasos opcionales fuera de CI (mismo alcance que IT5)

**Checkpoint**: Las 27 tareas completas. Todos los escenarios de aceptación del
spec (FR-001 a FR-013) pasan con dobles de prueba y CERO envíos SMTP reales. La
funcionalidad está lista para merge.

---

## Dependencias y Orden de Ejecución

### Dependencias de Fase

- **Fase 1 (Setup)**: sin dependencias — T001 y T002 son paralelizables entre sí
- **Fase 2 (Foundational)**: depende de Fase 1; **bloquea** las tres historias (T003-T009)
- **Fase 3 (US1)**: depende de Fase 2; T010-T012 deben fallar antes de T013-T014
- **Fase 4 (US2)**: depende de Fase 3 (reutiliza `notify_failure`, `_send` y `_notify_and_exit`); T015-T017 deben fallar antes de T018-T019
- **Fase 5 (US3)**: depende de Fase 3 (necesita el enganche del CLI ya existente); T020 debe fallar antes de T021
- **Fase 6 (Polish)**: depende de las tres historias completas

### Dependencias entre tareas

- T005 → T007 (los tipos y `_load_config` se validan contra los tests ya escritos)
- T006 → T008 (la ruta de envío se valida contra los tests ya escritos)
- T004 → T009 (contexto estructurado en las excepciones del pipeline)
- T007, T008 → T013, T018 (contenido del email sobre el armazón del notificador)
- T012 → T014 (contrato CLI y su implementación)
- T013, T014 → T017 → T018, T019 (US2 se apoya en el enganche de US1)
- T020 → T021 (guard del camino feliz)

### Oportunidades de paralelización

- **Foundational**: T003, T004, T005 y T006 son cuatro zonas distintas —
  paralelizables entre sí; T007 y T008 comparten `notify.py` (secuenciales entre
  sí) y T009 vive en `sync.py` (paralelizable con T007/T008 una vez T004 listo)
- **US1**: T012 (`test_cli_sync.py`) puede escribirse en paralelo con T010/T011
  (`test_notify.py`); las implementaciones T013 (`notify.py`) y T014
  (`cli/sync.py`) tocan ficheros distintos y pueden hacerse en paralelo tras los tests
- **US2**: T015/T016 (`test_notify.py`) y T017 (`test_cli_sync.py`) en paralelo;
  T018 y T019 en paralelo (ficheros distintos)
- **Polish**: T022-T026 son independientes entre sí (CI local, auditoría de
  secretos y tres documentos distintos)

### Ejemplos de ejecución paralela

```text
# Fase 2 (tras Fase 1):
T003 (tests/unit/conftest.py)           ┐
T004 (tests/unit/test_sync.py)          ├─ en paralelo
T005 (tests/unit/test_notify.py: tipos) │
T006 (tests/unit/test_notify.py: SMTP)  ┘

# Fase 3 (tras Fase 2):
T010, T011 (test_notify.py) ┐ en paralelo
T012       (test_cli_sync.py) ┘
→ T013 (notify.py) ┐ en paralelo
  T014 (cli/sync.py) ┘

# Fase 4 (tras Fase 3):
T015, T016 (test_notify.py) ┐ en paralelo
T017       (test_cli_sync.py) ┘
→ T018 (notify.py) ┐ en paralelo
  T019 (cli/sync.py) ┘
```

---

## Estrategia de Implementación

### MVP primero (solo US1)

1. Fase 1 + Fase 2 completas (Setup + Foundational)
2. Escribir los tests en fallo de US1 (T010-T012) — verificar ROJO
3. Implementar US1 (T013-T014) — verificar VERDE
4. **DETENERSE Y VALIDAR**: ejecutar `specs/006-email-failure-notifications/quickstart.md`,
   sección "Validación automatizada", filtrando por US1

### Entrega Completa

1. MVP anterior ✅
2. Escribir los tests en fallo de US2 (T015-T017) — verificar ROJO
3. Implementar US2 (T018-T019) — verificar VERDE
4. Escribir los tests en fallo de US3 (T020) — verificar ROJO
5. Implementar US3 (T021) — verificar VERDE
6. Fase 6 Polish (T022-T027)

---

## Notas

- [P] = ficheros distintos, seguro de paralelizar
- `notify.py` (núcleo) NUNCA llama a `print()` — solo `logging`
  (Anti-patrón #6); `cli/sync.py` sigue siendo el único módulo que imprime
- La contraseña de aplicación (`SMTP_PASSWORD`) no se interpola jamás en logs,
  asunto, cuerpo ni cabeceras del email (FR-008, Principio IV): el único punto que
  la usa es la llamada `login(user, password)` dentro de `_send`
- Todos los tests usan `Mock(spec=smtplib.SMTP)` vía `smtp_factory` inyectada, más
  la fixture autouse `no_real_smtp` (T003) que hace fallar cualquier intento de
  conexión real (FR-010, Principio III). No se usa `monkeypatch` sobre
  `smtplib.SMTP_SSL` salvo en el test concreto de la fábrica por defecto, que debe
  sobrescribir la fixture dentro del propio test
- `DeliveryStatus.SKIPPED` (configuración ausente) **no** altera el exit code del
  desenlace (FR-007); solo `FAILED` produce el exit code `4` (FR-006); la
  precedencia de `4` sobre `1`/`2`/`3` está fijada en
  `contracts/cli-sync-interface.md`
- Sin deduplicación, reintentos ni encolamiento entre ejecuciones (spec §
  Clarifications y § Suposiciones, Principio VII); ninguna tarea introduce estado
  persistente
- El fallo de Sheets en modo combinado envía **un solo** email con la causa de
  escritura y los motivos por banco (FR-002) — no dos emails
- `docs/roadmap.md` no se modifica en esta iteración: IT6 ya está descrito allí y
  el estado se refleja en `docs/context.md` (T024)
- El drift entre `.env.example` (heredado de IT1: `GMAIL_SMTP_PASSWORD`,
  `GMAIL_FROM`, `GMAIL_TO`) y las cinco claves de `research.md` Decisión 3 se
  resuelve en T002; `specs/001-project-skeleton-ci/contracts/secret-store-format.md`
  se deja intacto por ser un contrato histórico ya cerrado
- SC-006 (< 60 s de entrega) se garantiza por diseño con
  `_SMTP_TIMEOUT_SECONDS = 30`; al igual que SC-006 de IT4/IT5, se valida
  manualmente en `quickstart.md`, no está automatizado en CI
- Comitear tras cada grupo lógico (tras Fase 2, tras cada historia, tras Polish)
