# Modelo de Datos — Scheduler en GitHub Actions (IT7)

**Funcionalidad**: `007-scheduler-github-actions` | **Fecha**: 2026-10-17

Esta iteración **no introduce estructuras de datos en el proceso** (no hay entidades nuevas en
`src/banking/`): su "modelo" es la definición del workflow, el inventario de secretos y los datos que
el proceso ya produce y que el workflow publica. No hay base de datos, ni ficheros versionados, ni
persistencia entre ejecuciones (Principio VII).

---

## Entidad 1 — Definición del workflow (`sync.yml`)

El documento declarativo que determina cuándo y cómo se ejecuta la sincronización.

| Atributo | Valor | Origen |
|---|---|---|
| Ruta | `.github/workflows/sync.yml` | FR-001, FR-011 |
| `name` | `Sync diaria` | FR-006 (identificable en el historial) |
| Disparadores | `schedule` (cron) + `workflow_dispatch` (sin `inputs`) | FR-001, FR-002 |
| Cron | `0 6 * * *` | FR-001, Decisión 2 |
| `permissions` | `contents: read` | FR-010 |
| `concurrency.group` | `banking-sync` | FR-008 |
| `concurrency.cancel-in-progress` | `false` | FR-008 |
| `runs-on` | `ubuntu-latest` | Decisión 11 |
| `timeout-minutes` | `10` | FR-005, SLO de la constitución |
| Comando ejecutado | `python -m banking sync` | FR-003 |

**Regla de integridad**: el fichero no contiene ningún valor de credencial — sólo referencias
`${{ secrets.<NOMBRE> }}` en claves `env:`. Verificable con `tests/unit/test_sync_workflow.py`.

---

## Entidad 2 — Secreto de repositorio (inventario)

Cada valor sensible que el propietario almacena en GitHub y que el job materializa antes de ejecutar
el proceso. 14 secretos en total (FR-004, Decisión 3).

### Familia A — `.env` cifrado (`SecretStore`, AES-256)

| Secreto de GitHub | Clave en `SecretStore` | Consumido por | Formato |
|---|---|---|---|
| `BANKING_MASTER_KEY` | *(no se almacena: es la clave)* | `SecretStore` (variable de entorno) | 64 caracteres hex |
| `ENABLE_BANKING_SESSION_ID_ING` | `ENABLE_BANKING_SESSION_ID_ING` | `connectors/ing.py` | `uuid:hash` |
| `ENABLE_BANKING_SESSION_ID_REVOLUT` | `ENABLE_BANKING_SESSION_ID_REVOLUT` | `connectors/revolut.py` | `uuid:hash` |
| `ENABLE_BANKING_SESSION_ID_MYINVESTOR` | `ENABLE_BANKING_SESSION_ID_MYINVESTOR` | `connectors/myinvestor.py` | `uuid:hash` |
| `ENABLE_BANKING_SESSION_ID_SABADELL` | `ENABLE_BANKING_SESSION_ID_SABADELL` | `connectors/sabadell.py` | `uuid:hash` |
| `GOOGLE_SHEETS_CREDENTIALS` | `GOOGLE_SHEETS_CREDENTIALS` | `sheets/writer.py` | JSON de cuenta de servicio (una línea o multilínea) |
| `GOOGLE_SHEET_ID` | `GOOGLE_SHEET_ID` | `sync.py` | ID del documento |
| `SMTP_HOST` | `SMTP_HOST` | `notify.py` (IT6) | host |
| `SMTP_PORT` | `SMTP_PORT` | `notify.py` (IT6) | entero como texto |
| `SMTP_USER` | `SMTP_USER` | `notify.py` (IT6) | email |
| `SMTP_PASSWORD` | `SMTP_PASSWORD` | `notify.py` (IT6) | contraseña de aplicación |
| `NOTIFY_EMAIL_TO` | `NOTIFY_EMAIL_TO` | `notify.py` (IT6) | email |

### Familia B — Credencial de firma Enable Banking (fichero, no `SecretStore`)

| Secreto de GitHub | Destino en el runner | Formato |
|---|---|---|
| `ENABLE_BANKING_APP_ID` | campo `app_id` de `$RUNNER_TEMP/eb/eb-config.json` | texto |
| `ENABLE_BANKING_PRIVATE_KEY` | `$RUNNER_TEMP/eb/private_key.pem` (chmod 600), referenciado por `private_key_path` | PEM RSA |

**Ciclo de vida**: los valores existen en memoria del runner y en ficheros efímeros
(`.env` en el workspace, `$RUNNER_TEMP/eb/*`); el runner se destruye al terminar la ejecución. Nada se
commitea, nada se cachea, nada se sube como artefacto.

**Reglas de integridad**

1. Ningún valor de estas tablas puede aparecer literalmente en el YAML, en el repositorio ni en logs,
   resúmenes o mensajes de error (FR-010, Principio IV).
2. Si un secreto falta o está vacío, la ejecución falla antes de contactar con ninguna API (FR-009).
3. Rotar una credencial = actualizar ese secreto en GitHub; el workflow no cambia (FR-012).

---

## Entidad 3 — Ejecución (*run*)

Cada intento del workflow, tal y como lo registra GitHub.

| Atributo | Origen | Notas |
|---|---|---|
| Disparador | `schedule` \| `workflow_dispatch` | FR-001, FR-002 |
| Estado | éxito \| fallo | Derivado del exit code del proceso (FR-007) |
| `exit_code` | salida del proceso (`PIPESTATUS[0]`) | `0` éxito · `1` fallo total · `2` fallo de Sheets · `3` fallo parcial · `4` fallo de entrega del email |
| Duración | plataforma | Debe quedar bajo 10 min (FR-005, SC-006) |
| Resumen publicado | paso de resumen | Ver Entidad 5 |
| Salida completa | log del paso | Sanitizada por IT5/IT6 (sin credenciales) |

**Transiciones**: `pendiente` (esperando turno por `concurrency`) → `en curso` → `éxito` \| `fallo`. Una
ejecución pendiente sólo empieza cuando la anterior termina (FR-008).

---

## Entidad 4 — Resultado de sincronización (existente, IT5)

El agregado estructurado que el proceso produce (`SyncSummary` en `src/banking/sync.py`) y que esta
iteración **no modifica**: estado global (`FULL_SUCCESS` \| `PARTIAL_FAILURE`), desenlace por banco
(`BankOutcome`: nombre, `rows_written`, `failure_reason`), pestaña destino, total de movimientos y
duración. Es la fuente de verdad tanto del email de IT6 como del resumen publicado.

---

## Entidad 5 — Resumen de ejecución (`$GITHUB_STEP_SUMMARY`)

Documento Markdown efímero, generado por el workflow a partir de la salida del proceso (Decisión 4).
Estructura fija:

~~~~markdown
## Sincronización bancaria — 2026-10-18

- **Estado**: éxito | fallo
- **Exit code**: 0 | 1 | 2 | 3 | 4
- **Duración del job**: 42s   (dato de plataforma, opcional)

```text
Sincronización completada: 4/4 bancos — 128 movimientos escritos en la pestaña 2026-10 (12.34s)
  - ING: 54 movimientos
  - Revolut: 31 movimientos
  - MyInvestor: 12 movimientos
  - Sabadell: 31 movimientos
```
~~~~

**Datos obligatorios** (FR-006, constitución § Performance & Observability): bancos procesados,
movimientos escritos, fallos con su motivo, duración total. Los cuatro están en la cabecera del
proceso; los fallos, en las líneas `  - <banco>: FALLÓ — <motivo>`.

**Regla de degradación**: si el proceso no llegó a imprimir resumen (fallo de arranque, timeout), el
resumen indica ese hecho y remite a los logs; no se inventan datos (FR-006 + caso límite de arranque).

**Regla de seguridad**: el resumen se construye sólo con líneas de la salida del proceso, que ya está
sanitizada (IT5/IT6). Nunca se interpolan variables de secreto.
