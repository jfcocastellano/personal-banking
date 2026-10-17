# Contrato — Workflow de sincronización programada (`sync.yml`)

**Funcionalidad**: `007-scheduler-github-actions` | **Versión**: 1 | **Fecha**: 2026-10-17

Contrato de la infraestructura de ejecución: qué garantiza `.github/workflows/sync.yml` al
propietario. Todo lo aquí descrito es verificable por `tests/unit/test_sync_workflow.py` (sin red) o
por observación de una ejecución real.

---

## 1. Disparadores (FR-001, FR-002, FR-011)

| Disparador | Configuración | Garantía |
|---|---|---|
| Programado | `schedule: - cron: "0 6 * * *"` | Una ejecución diaria, ~06:00 UTC, sin intervención humana |
| Manual | `workflow_dispatch:` sin `inputs` | Ejecución bajo demanda sin parámetros |
| `push` | **ausente** | Un push o merge nunca sincroniza ni escribe en la hoja |
| `pull_request` | **ausente** | Un PR nunca sincroniza ni consume cuota PSD2 |

**Invariantes**

- El workflow NO declara ningún otro evento (`release`, `repository_dispatch`, `workflow_run`, etc.).
- `workflow_dispatch` no acepta entradas: la sincronización no se parametriza (FR-002).
- El cron es diario y de hora fija: un único campo minuto/hora (`M H * * *`), sin listas ni rangos.

---

## 2. Job (FR-005, FR-008, FR-010, FR-011)

```yaml
jobs:
  sync:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    permissions:
      contents: read
    concurrency:
      group: banking-sync
      cancel-in-progress: false
```

| Elemento | Valor | Garantía |
|---|---|---|
| `timeout-minutes` | `10` | Una ejecución colgada se cancela a los 10 min (SLO de la constitución) |
| `permissions` | `contents: read` | El `GITHUB_TOKEN` no puede escribir en el repositorio |
| `concurrency.group` | `banking-sync` | Serializa todas las ejecuciones (programadas y manuales) |
| `concurrency.cancel-in-progress` | `false` | Nunca se interrumpe una escritura en curso (FR-008) |
| `runs-on` | `ubuntu-latest` | Entorno idéntico al de CI |

**Garantía de exclusión mutua**: en ningún instante hay dos ejecuciones activas del job; una ejecución
nueva espera a que termine la anterior (o es descartada por la plataforma si ya hay una pendiente).

---

## 3. Pasos, en orden

| # | Paso | Qué hace | Requisito |
|---|---|---|---|
| 1 | `Validar configuración` | Comprueba que los 14 secretos están presentes y no vacíos; nombra los ausentes; falla en < 1 min sin red | FR-009 |
| 2 | `Checkout` | `actions/checkout@v4` | — |
| 3 | `Preparar Python` | `actions/setup-python@v5`, `python-version: "3.12"` | Decisión 11 |
| 4 | `Instalar dependencias` | `pip install -r requirements.txt` + `pip install -e .` + `pip-audit -r requirements.txt` | Decisión 11 |
| 5 | `Provisionar configuración` | Escribe el `.env` cifrado con `python -m banking secrets set` (familia A) y `eb-config.json` + PEM en `$RUNNER_TEMP/eb` (familia B) | FR-004, Decisión 3 |
| 6 | `Ejecutar sincronización` | `python -m banking sync` con `tee` a log, captura `PIPESTATUS[0]` en `steps.sync.outputs.exit_code` | FR-003, FR-007 |
| 7 | `Publicar resumen` | `if: always()`; escribe el resumen en `$GITHUB_STEP_SUMMARY` | FR-006 |
| 8 | `Propagar resultado` | `exit ${{ steps.sync.outputs.exit_code }}` | FR-007 |

**Orden obligatorio**: 1 antes de 6 (no se toca ninguna API si falta configuración); 7 con
`if: always()` (el resumen se publica también cuando el paso 6 falla); 8 al final (el estado del job
refleja el del proceso, no el de los pasos auxiliares).

---

## 4. Contrato de configuración (FR-004, FR-009, FR-010)

### 4.1 Regla de exposición

- Todo `${{ secrets.<NOMBRE> }}` aparece **exclusivamente** bajo una clave `env:` (de job o de paso).
- Ningún `${{ secrets.* }}` se interpola dentro de un bloque `run:`.
- Ningún valor de secreto se escribe en: el repositorio, `$GITHUB_STEP_SUMMARY`, nombres de artefacto,
  mensajes de error ni `::error::`/`::notice::` anotaciones.

### 4.2 Nombres exigidos (14)

`BANKING_MASTER_KEY`, `ENABLE_BANKING_SESSION_ID_ING`, `ENABLE_BANKING_SESSION_ID_REVOLUT`,
`ENABLE_BANKING_SESSION_ID_MYINVESTOR`, `ENABLE_BANKING_SESSION_ID_SABADELL`,
`ENABLE_BANKING_APP_ID`, `ENABLE_BANKING_PRIVATE_KEY`, `GOOGLE_SHEETS_CREDENTIALS`,
`GOOGLE_SHEET_ID`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFY_EMAIL_TO`.

### 4.3 Materialización

| Familia | Destino | Mecanismo |
|---|---|---|
| A — 11 claves + clave maestra | `.env` en el directorio de trabajo | `BANKING_MASTER_KEY` como variable de entorno + `python -m banking secrets set KEY "$VALOR"` por clave |
| B — firma Enable Banking | `$RUNNER_TEMP/eb/eb-config.json` (`app_id`, `private_key_path`) y `$RUNNER_TEMP/eb/private_key.pem` (chmod 600) | escritura directa desde el secreto; `BANKING_EB_CONFIG_DIR` apunta al directorio |

**Fallo temprano**: si falta un secreto, el paso 1 termina con exit code ≠ 0, imprime la lista de
nombres ausentes (nunca valores) y los pasos 2-8 no se ejecutan.

---

## 5. Contrato de resultado (FR-006, FR-007)

### 5.1 Propagación del exit code

| Exit code del proceso | Estado del job | Lectura |
|---|---|---|
| `0` | éxito | Sincronización completa, sin email (IT6) |
| `1` | fallo | Los 4 bancos fallaron |
| `2` | fallo | Fallo al escribir en Google Sheets |
| `3` | fallo | Fallo parcial (≥ 1 banco fallido, ≥ 1 correcto) |
| `4` | fallo | Fallo al entregar el email de aviso (IT6) |
| otro (p. ej. `1` de un `pip install` fallido) | fallo | Fallo de infraestructura, no de sincronización |

**Invariante**: el estado del job coincide exactamente con el exit code del proceso; un `4` de IT6 no
se enmascara como éxito.

### 5.2 Contenido del resumen

El resumen publicado DEBE contener, en cualquier estado:

1. **Estado** legible (éxito / fallo) y **exit code** del proceso.
2. **Bancos procesados**: cabecera `Sincronización completada|parcial: N/M bancos` + una línea por
   banco con su recuento (`  - <banco>: <n> movimientos`) o su motivo (`  - <banco>: FALLÓ — <motivo>`).
3. **Movimientos escritos**: total y pestaña destino, en la cabecera del proceso.
4. **Duración**: la del proceso (`(Xs)` en la cabecera) y, opcionalmente, la del job.
5. Si no hay salida del proceso: nota explícita de fallo de arranque y remisión a los logs.

**No contiene**: credenciales, tokens, JWT, `session_id` completos ni el JSON de la cuenta de servicio
(FR-010; la salida del proceso ya está sanitizada por IT5/IT6).

---

## 6. Invariantes verificadas por tests (`tests/unit/test_sync_workflow.py`)

| # | Invariante | Requisito |
|---|---|---|
| 1 | `sync.yml` existe y es YAML válido | FR-001 |
| 2 | Sólo `schedule` (cron diario) y `workflow_dispatch` (sin `inputs`) | FR-001, FR-002, FR-011 |
| 3 | Ausencia total de `push` y `pull_request` | FR-011 |
| 4 | `timeout-minutes: 10` y `runs-on: ubuntu-latest` | FR-005 |
| 5 | `concurrency` con `cancel-in-progress: false` | FR-008 |
| 6 | `permissions` de sólo lectura | FR-010 |
| 7 | El job ejecuta `python -m banking sync` (mismo comando que en local) | FR-003 |
| 8 | Todos los `${{ secrets.* }}` están bajo `env:` | FR-010 |
| 9 | Los 14 nombres de secreto están declarados | FR-004 |
| 10 | Paso de resumen con `if: always()` y `$GITHUB_STEP_SUMMARY` | FR-006 |
| 11 | Paso final que propaga `steps.<id>.outputs.exit_code` | FR-007 |
| 12 | El YAML no contiene formas de credencial literal | FR-010, Principio IV |
| 13 | El paso de validación precede al de sincronización | FR-009 |
| 14 | `ci.yml` no se modifica (sigue con `push`/`pull_request` y sus cinco gates) | FR-011 |

---

## 7. Fuera de contrato

- No se notifica nada si la ejecución se cancela por `timeout-minutes` (el proceso muere antes de
  IT6); el propietario lo detecta por el estado fallido y por el resumen degradado.
- No hay reintentos automáticos ni ejecuciones de recuperación: el día siguiente reintenta, o el
  propietario usa `workflow_dispatch` (FR-002).
- No se publican artefactos, ni histórico de ejecuciones, ni métricas más allá del resumen.
- No se automatiza la rotación de credenciales ni la re-autorización PSD2: son actos manuales
  documentados en [quickstart.md](quickstart.md).
