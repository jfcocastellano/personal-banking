# Plan de Implementación: Notificación de Errores por Email

**Rama**: `006-email-failure-notifications` | **Fecha**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Entrada**: Especificación de la funcionalidad desde `specs/006-email-failure-notifications/spec.md`

> **➡️ Siguiente paso**: ejecutar `/speckit-tasks` para generar `tasks.md` (descomposición en tareas
> con ciclo Red → Green → Refactor) y después `/speckit-implement`. El flujo SDD es
> spec → plan → **tasks** → implement (Principio I de la constitución).

---

## Resumen

Añadir al proceso de sincronización un notificador por email que alerte al propietario cuando una
ejecución termina mal, sin que tenga que revisar los logs de GitHub Actions. El notificador
(`banking.notify`, módulo núcleo nuevo) consume el resultado estructurado que el pipeline de IT5 ya
produce — `SyncSummary` en el camino de retorno, y los motivos por banco en las excepciones
`AllBanksFailedError`/`SheetsSyncError` — y envía **un único email agregado por ejecución fallida**
por Gmail SMTP (stdlib `smtplib`, sin dependencias nuevas): fallo parcial → detalle de bancos
fallidos con su motivo y bancos exitosos con su recuento; fallo total o fallo de escritura en
Sheets → error general (en el caso combinado banco+escritura, un solo email con ambos). Éxito
completo → ningún email. El enganche vive en la capa CLI (`cli/sync.py`), dentro del flujo del
comando y antes de devolver el exit code: la configuración ausente o incompleta degrada a un aviso
en logs sin alterar el resultado (FR-007), mientras que un envío intentado y fallido produce el
**exit code 4** (FR-006), con el resumen de la ejecución impreso igualmente. El transporte SMTP es
inyectable para que todos los tests mockeen el cliente (Principio III).

Ver `research.md` para el detalle de cada decisión de diseño (canal SMTP con stdlib, ubicación del
módulo y punto de enganche, claves de configuración, señal de resultado de entrega, transporte
inyectable, extensión retrocompatible de las excepciones del pipeline, formato del email y alcance
de pruebas).

---

## Contexto Técnico

**Lenguaje/Versión**: Python 3.12 (mismo runtime que IT1-IT5; venv `.venv` con Python 3.12.14)

**Dependencias principales**: Ninguna nueva. El envío usa exclusivamente la librería estándar —
`smtplib` (cliente SMTP con SSL) y `email.message.EmailMessage` (construcción del mensaje) —
preferencia explícita del Principio VII ("prefer Python stdlib over third-party libraries when
capability is equivalent") y de `docs/context.md` (stack técnico: "Usando `smtplib` de la librería
estándar de Python"). Reutiliza `banking.config.secret_store.SecretStore` (IT1) para la
configuración y los tipos `SyncSummary`/`BankOutcome` de `banking.sync` (IT5).

**Almacenamiento**: Ninguno nuevo. Sin persistencia local ni estado entre ejecuciones (sin
deduplicación — ver spec.md § Clarifications); la configuración SMTP vive en el `.env` cifrado ya
existente (SecretStore AES-256, IT1), igual que `GOOGLE_SHEET_ID` y `GOOGLE_SHEETS_CREDENTIALS`.

**Testing**: `pytest` con `pytest-mock`. El transporte SMTP se inyecta en `EmailNotifier` mediante
una fábrica (`smtp_factory`) y los tests usan `Mock(spec=smtplib.SMTP)` — cero conexiones reales
(Principio III). `test_notify.py` cubre el notificador aislado (contenido del email, interacción
SMTP, los tres estados de entrega); `test_cli_sync.py` cubre el enganche (exit codes 0/1/2/3/4,
notificador invocado solo cuando toca) inyectando `Mock(spec=EmailNotifier)` en `handle()`;
`test_sync.py` se amplía con los atributos nuevos de las excepciones (`outcomes`, `tab_name`).

**Plataforma objetivo**: Igual que IT1-IT5 — GitHub Actions `ubuntu-latest` para CI; desarrollo
local en WSL Ubuntu. El scheduler (IT7) llega después; esta iteración se valida con el CLI local y
la suite mockeada.

**Tipo de proyecto**: Componente núcleo nuevo (`src/banking/notify.py`) más extensión de la capa
CLI existente (`src/banking/cli/sync.py`) y de las excepciones del pipeline (`src/banking/sync.py`).

**Objetivos de rendimiento**: Entrega del email de error en menos de 60 segundos desde la detección
del fallo (SC-006 de la spec, SLO "Error email delivery < 60 seconds" de la constitución). El
timeout de conexión/lectura SMTP se fija en 30s (constante de módulo) para que un servidor caído no
cuelgue el proceso más allá del SLO. El presupuesto de sincronización (< 2 minutos, SC-006 de IT5)
no se ve afectado: el email solo se envía en ejecuciones fallidas.

**Restricciones**:
- `notify.py` (núcleo) NO DEBE llamar a `print()` — solo `logging` (Anti-patrón #6); `cli/sync.py`
  sigue siendo el único módulo que imprime.
- Ninguna dependencia de terceros nueva (Anti-patrón #10) — `smtplib`/`email` son stdlib.
- La contraseña SMTP (contraseña de aplicación) NUNCA se interpola en logs, mensajes ni email
  (FR-008, Principio IV); las claves de configuración se leen del SecretStore, nunca hardcodeadas
  (Anti-patrón #4).
- Todos los tests mockean el transporte SMTP; cero red real (Principio III, FR-010).
- Un envío fallido se registra y no propaga excepción (FR-006); la configuración ausente degrada a
  aviso sin alterar el exit code (FR-007).
- Exit code nuevo `4` = fallo de entrega de la notificación (FR-006); los códigos 0/1/2/3 de IT5
  conservan su significado cuando la entrega no falla.
- `handle()` debe permanecer con complejidad ciclomática ≤ 10 (Principio VI) — se extraen helpers.
- Ningún email incluye credenciales, JWT, `session_id` completo ni JSON de cuenta de servicio
  (FR-008); los motivos de fallo ya llegan sanitizados desde los conectores (contrato IT5).

**Escala/Alcance**: Un destinatario, un email por ejecución fallida, texto plano en español. Sin
concurrencia, sin reintentos, sin encolamiento, sin deduplicación (YAGNI, Principio VII — ver
spec.md § Suposiciones y § Clarifications).

---

## Constitution Check

*GATE: Debe pasar antes de la investigación de Fase 0. Se revalida después del diseño de Fase 1.*

- [x] La especificación existe en `specs/006-email-failure-notifications/spec.md` y ha pasado por
  `/speckit-clarify` (6 clarificaciones integradas) (Principio I)
- [x] Ninguna prueba realiza llamadas de red reales — el transporte SMTP se inyecta vía
  `smtp_factory` y todos los tests usan `Mock(spec=smtplib.SMTP)`; Gmail SMTP ya figura entre los
  servicios que la constitución obliga a mockear (Principio III)
- [x] No se introduce base de datos ni persistencia local — sin estado entre ejecuciones (sin
  deduplicación, decisión clarificada); la configuración vive en el `.env` cifrado ya existente
  (Principio VII)
- [x] Los secretos fluyen por el mecanismo cifrado existente — `SMTP_PASSWORD` (contraseña de
  aplicación Gmail) vía `SecretStore` en local / GitHub Secrets en CI; nunca hardcodeada ni
  interpolada en logs o emails (Principio IV)
- [x] Los fallos se manejan de forma independiente — el notificador no propaga excepciones: un
  fallo de entrega se registra y se traduce a exit code 4 sin enmascarar el desenlace de
  sincronización (el resumen sigue imprimiéndose); un solo email agregado por ejecución (Principio V)
- [x] Todas las funciones públicas llevarán anotaciones de tipo completas — exigido por `mypy`
  strict (Principio VI)
- [x] Ninguna función superará complejidad ciclomática 10 — `handle()` se refactoriza con helpers
  (`_finish_total_failure`, `_finish_sheets_failure`) y el notificador delega en `_load_config` y
  `_send` (Principio VI)
- [x] No se añade ninguna dependencia de terceros nueva — `smtplib` y `email` son stdlib
  (Anti-patrón #10 — no aplica, nada que pinear)

**Nota sobre capas de abstracción** (Principio VII, máximo 3 capas por slice vertical): `notify.py`
no añade una cuarta capa — es un componente par de `sheets/writer.py` dentro de la capa de
"salida/notificación" del slice ya existente (conector → servicio `sync.py` → salida
`sheets/` + `notify.py`). El notificador consume tipos ya públicos de IT5 y no introduce
intermediarios nuevos.

**Revalidación post-diseño (Fase 1)**: Sin violaciones nuevas. `data-model.md` introduce
`EmailConfig`, `DeliveryStatus` y `EmailNotifier` como estructuras puras / componente de salida sin
persistencia; `contracts/notify-interface.md` formaliza la interfaz interna Python y
`contracts/cli-sync-interface.md` extiende el contrato CLI de IT5 con el exit code 4 — ningún
cambio de arquitectura más allá de lo justificado arriba.

---

## Estructura del Proyecto

### Documentación (esta funcionalidad)

```text
specs/006-email-failure-notifications/
├── plan.md                                ← este fichero (/speckit-plan)
├── research.md                            ← salida de Fase 0
├── data-model.md                          ← salida de Fase 1
├── quickstart.md                          ← salida de Fase 1 (guía de validación)
├── contracts/
│   ├── notify-interface.md                ← contrato del notificador (interfaz Python interna)
│   └── cli-sync-interface.md              ← contrato CLI extendido (exit codes 0-4 + notificación)
└── checklists/
    └── requirements.md
```

### Código fuente (raíz del repositorio)

```text
src/
└── banking/
    ├── __main__.py                        # SIN CAMBIOS: el dispatch genérico ya cubre sync
    ├── sync.py                            # MODIFICADO: AllBanksFailedError y SheetsSyncError
    │                                       #   llevan outcomes + tab_name (retrocompatible)
    ├── notify.py                          # NUEVO: EmailNotifier, DeliveryStatus, EmailConfig,
    │                                       #   carga de configuración y envío SMTP (solo logging)
    ├── logging_config.py                  # SIN CAMBIOS
    ├── cli/
    │   └── sync.py                        # MODIFICADO: enganche de la notificación en handle(),
    │                                       #   exit code 4, DI del notificador, helpers de terminación
    ├── config/
    │   └── secret_store.py                # SIN CAMBIOS
    ├── connectors/                        # SIN CAMBIOS (enable_banking, ing, revolut,
    │                                       #   myinvestor, sabadell)
    └── sheets/
        └── writer.py                      # SIN CAMBIOS

tests/
└── unit/
    ├── test_notify.py                     # NUEVO: contenido del email, interacción SMTP,
    │                                       #   estados SENT/SKIPPED/FAILED, sin secretos
    ├── test_cli_sync.py                   # MODIFICADO: exit codes con notificador mockeado,
    │                                       #   exit 4, notificador no invocado en éxito
    ├── test_sync.py                       # MODIFICADO: excepciones con outcomes/tab_name
    ├── test_main.py                       # SIN CAMBIOS
    ├── test_logging_config.py             # SIN CAMBIOS
    ├── test_dependencies.py               # SIN CAMBIOS
    ├── connectors/                        # SIN CAMBIOS
    ├── sheets/
    │   └── test_writer.py                 # SIN CAMBIOS
    └── config/
        └── test_secret_store.py           # SIN CAMBIOS
```

**Decisión de estructura**: se mantiene el paquete plano `src/banking/` ya establecido (IT1-IT5);
`notify.py` vive en la raíz del paquete como componente de salida al mismo nivel que `sync.py` y
`sheets/` — es un servicio de notificación transversal al pipeline, no un subcomponente de Sheets
ni de ningún conector. La capa CLI (`cli/sync.py`) orquesta la terminación (impresión + notificación
+ exit code), igual que ya orquestaba la impresión y los exit codes en IT4/IT5.

---

## Complexity Tracking

*Sin violaciones que justificar. El único punto de atención (`handle()` crece con las ramas de
notificación) se resuelve extrayendo los helpers `_finish_total_failure` y `_finish_sheets_failure`
en `cli/sync.py`, y delegando la carga de configuración y el envío en `_load_config` y `_send` en
`notify.py` — todas las funciones quedan muy por debajo del límite de complejidad 10 (Principio VI).*
