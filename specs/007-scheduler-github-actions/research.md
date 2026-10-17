# Fase 0 — Investigación y decisiones de diseño (IT7)

**Funcionalidad**: Scheduler en GitHub Actions (automatización completa)
**Rama**: `007-scheduler-github-actions` | **Fecha**: 2026-10-17
**Entrada**: [spec.md](spec.md) · [plan.md](plan.md)

Esta iteración no introduce código Python nuevo: introduce un **workflow** que orquesta el binario
ya existente (`python -m banking sync`) y un conjunto de pruebas que validan la definición del
workflow sin tocar la red. Las decisiones de abajo son, por tanto, de infraestructura y de contrato
con el proceso, no de algoritmia.

---

## Decisión 1 — Fichero de workflow separado, con sólo dos disparadores

**Decisión**: crear `.github/workflows/sync.yml` como workflow independiente, con exactamente dos
disparadores: `schedule` (cron diario) y `workflow_dispatch` (sin entradas). Ni `push` ni
`pull_request`.

**Justificación**: FR-011 exige que los pushes y PRs no disparen la sincronización (escribiría en la
hoja de cálculo real y consumiría cuota PSD2 por cada push) y que el pipeline de integración
continua siga funcionando como hasta ahora. `ci.yml` se deja intacto: sigue disparándose en
`push`/`pull_request` a `main` con sus cinco gates.

**Alternativa rechazada**: añadir el job de sincronización a `ci.yml` condicionado a
`if: github.event_name == 'schedule'`. Mezcla dos ciclos de vida con permisos y secretos distintos en
el mismo fichero, y expone el job de sincronización a los mismos disparadores que el CI (un error en
la condición escribiría en la hoja desde un PR). Además rompería los tests existentes de
`tests/unit/test_ci_config.py`, que afirman sobre el contenido de `ci.yml`.

**Nota de plataforma**: los workflows programados sólo se ejecutan desde la rama por defecto, de modo
que el cron no dispara en esta rama de funcionalidad hasta que se mergee en `main`. La validación
previa al merge se hace con `workflow_dispatch` (la rama debe estar en el repositorio remoto para
que aparezca en la UI) o con ejecución local.

---

## Decisión 2 — Hora diaria fija en el cron, "configurable" = una línea documentada

**Decisión**: `cron: "0 6 * * *"` (06:00 UTC ≈ 08:00 en Madrid en horario de verano, 07:00 en
invierno), con un comentario en el propio YAML indicando que esa línea es el único punto a tocar para
cambiar la hora, y el procedimiento documentado en [quickstart.md](quickstart.md).

**Justificación**: FR-001 pide "una hora fija configurable". Las expresiones `schedule` de GitHub
Actions **no admiten** `vars.*` ni `secrets.*` — el cron se evalúa en el planificador, no en el
runner, así que no existe configuración externa posible. La única forma realista de "configurar" la
hora es editar el workflow; documentarlo cumple el requisito sin inventar indirección imposible.

**Alternativa rechazada**: disparar cada hora y decidir dentro del job si toca sincronizar (leyendo
una variable de repositorio). Multiplica por 24 las ejecuciones programadas (ruido en el historial,
24 facturaciones de minutos de runner) para conseguir algo que un `git commit` de una línea resuelve.

**Hora elegida**: 06:00 UTC. Los bancos publican los movimientos del día con retraso variable; a
primera hora de la mañana española el día anterior ya está consolidado y el propietario ve el
resultado al empezar el día. La sincronización no depende de la hora: siempre cubre el mes en curso
desde el día 1 (`docs/context.md`, Constraints Duros: retraso de hasta ~15 min aceptado).

---

## Decisión 3 — Dos familias de credenciales: `.env` cifrado y fichero de firma RSA

**Decisión**: el workflow materializa las credenciales en dos pasos distintos, porque el proyecto
tiene **dos** mecanismos de configuración:

| Familia | Mecanismo del proyecto | Secretos de GitHub | Destino en el runner |
|---|---|---|---|
| 11 claves de configuración | `SecretStore` (AES-256 sobre `.env`) | `BANKING_MASTER_KEY` + los 11 valores | `.env` en el directorio de trabajo, escritos con `python -m banking secrets set KEY "$VALUE"` |
| Credencial de firma Enable Banking | Fichero `eb-config.json` + PEM (`BANKING_EB_CONFIG_DIR`) | `ENABLE_BANKING_APP_ID`, `ENABLE_BANKING_PRIVATE_KEY` | `$RUNNER_TEMP/eb/eb-config.json` + `$RUNNER_TEMP/eb/private_key.pem` (chmod 600) |

**Justificación**: `src/banking/connectors/enable_banking.py` no lee la credencial de firma del
`SecretStore`: carga `eb-config.json` desde `BANKING_EB_CONFIG_DIR` (por defecto
`~/.config/banca-personal`), y ese JSON apunta a un PEM en disco (`_load_signing_credential`). Ningún
secreto se escribe en el repositorio ni en el workspace versionado: `.env` está en `.gitignore` y el
directorio de firma vive en `$RUNNER_TEMP`, que el runner descarta al terminar.

**Recuento total**: 14 secretos de GitHub — 1 clave maestra + 11 valores del `SecretStore` + `app_id` + PEM de Enable Banking. El desglose completo está en [data-model.md](data-model.md).

**Reutilización del CLI existente** (FR-003, no duplicar lógica): los valores se escriben con
`python -m banking secrets set`, ya implementado y probado en IT1 (`tests/unit/test_cli_secrets.py`),
en lugar de cifrar el `.env` desde el workflow con un script nuevo. El runner es efímero y de un solo
inquilino, y GitHub enmascara en logs cualquier valor de secreto, así que pasar el valor como
argumento (única interfaz que expone `secrets set`) es aceptable aquí; se documenta en el contrato.

**Alternativa rechazada**: un único secreto `BANKING_ENV_B64` con el `.env` cifrado completo, escrito
directamente en el runner. Es menos YAML, pero la rotación de una sola credencial (la contraseña de
aplicación de Gmail, por ejemplo) obligaría a regenerar y volver a subir el fichero entero desde una
máquina con la clave maestra, y el contenido completo quedaría opaco en la UI de secretos — en
conflicto directo con FR-012 (procedimiento de rotación por credencial documentado) y con el espíritu
de FR-004 (un secreto por credencial). Con 14 secretos individuales, rotar es `gh secret set` de uno
solo.

---

## Decisión 4 — El resumen de ejecución se construye en el workflow a partir de la salida del proceso

**Decisión**: el paso de sincronización captura stdout + stderr con `tee` a
`$RUNNER_TEMP/sync-output.log`; un paso posterior, con `if: always()`, escribe en
`$GITHUB_STEP_SUMMARY` un encabezado (estado, exit code, fecha) y, en bloque de código, las líneas de
resumen del proceso (la cabecera `Sincronización completada/parcial: N/M bancos — …, movimientos
escritos en la pestaña …, (Xs)` y las líneas `  - <banco>: …`). Si el proceso no produjo resumen
(fallo de arranque), el paso escribe el motivo genérico y una nota remitiendo a los logs.

**Justificación**: `python -m banking sync` ya imprime exactamente los cuatro datos que exigen FR-006
y la constitución (bancos procesados, movimientos escritos, fallos con motivo, duración) y lo hace en
español, en formato estable y cubierto por tests. Formatear en el workflow preserva FR-003 (cero
lógica de CI dentro del código Python) y el Principio VII (no añadir una capa de serialización para un
único consumidor).

**Alternativa rechazada**: añadir al CLI un flag `--summary-json <ruta>` que emitiera el resultado
estructurado para que el workflow lo renderizara. Sería más robusto ante cambios de formato, pero
introduce en el núcleo una salida que sólo existe para CI — justo lo que FR-003 prohíbe — y exigiría
tests y contrato nuevos para un requisito que el texto actual ya satisface.

**Riesgo asumido**: el resumen depende del formato impreso. Mitigación: el test
`tests/unit/test_sync_workflow.py` + los tests existentes de `cli/sync.py` fijan el texto de la
cabecera; si alguien lo cambia, ambos fallan a la vez y el desajuste se detecta en el mismo PR.

---

## Decisión 5 — Exit code preservado a través del pipe y propagado al estado de la ejecución

**Decisión**:

```bash
set -o pipefail
set +e
python -m banking sync 2>&1 | tee "$RUNNER_TEMP/sync-output.log"
code=${PIPESTATUS[0]}
echo "exit_code=$code" >> "$GITHUB_OUTPUT"
```

y un último paso `exit ${{ steps.sync.outputs.exit_code }}` que hace que el job termine con el código
del proceso.

**Justificación**: FR-007 exige que la ejecución quede marcada como fallida con cualquier exit code
distinto de 0 (1/2/3 de IT5 y 4 de IT6). El `tee` conserva la salida para el resumen pero rompe la
propagación del código; `PIPESTATUS[0]` recupera el del proceso Python (no el de `tee`) y `set +e`
evita que el propio paso aborte antes de guardar la salida y el código.

**Alternativa rechazada**: `set -euo pipefail` con redirección a fichero y `cat` posterior. Pierde la
salida en vivo (los logs de la ejecución se ven sólo al final, lo que dificulta diagnosticar un
proceso colgado) y complica el orden de los pasos.

---

## Decisión 6 — Exclusión mutua por grupo de concurrencia, sin cancelación

**Decisión**: `concurrency: {group: banking-sync, cancel-in-progress: false}`.

**Justificación**: FR-008 prohíbe dos escrituras simultáneas en la misma pestaña (la escritura de
Sheets no es transaccional: dos procesos intercalados podrían duplicar o perder filas). Con
`cancel-in-progress: false` la ejecución nueva queda *pendiente* hasta que la anterior acabe:
serialización, no solapamiento.

**Alternativa rechazada**: `cancel-in-progress: true` (cancelaría la ejecución en curso a mitad de la
escritura, dejando la pestaña incompleta — peor que esperar) y ausencia de `concurrency` (el caso
real: `workflow_dispatch` manual mientras corre la ejecución programada).

**Nota de plataforma**: GitHub admite una ejecución en curso y una pendiente por grupo; una tercera
queda cancelada. Es el comportamiento deseado — nunca hay dos ejecuciones activas, y el límite de 10
minutos acota la espera.

---

## Decisión 7 — Validación de secretos como primer paso, antes de cualquier llamada externa

**Decisión**: primer paso del job, `Validar configuración`, que recibe los 14 secretos como `env:` y
falla si alguno está vacío, listando los nombres ausentes (nunca los valores). Los pasos siguientes
no se ejecutan.

**Justificación**: FR-009. El límite PSD2 es de 4 peticiones de información de cuenta por día y
cuenta (`docs/context.md`, Constraints Duros), y el pipeline consulta las cuentas antes de escribir:
una ejecución mal configurada que llegue a ejecutar `sync` consume cuota real sin poder completar
nada. Además, el mensaje del fallo temprano nombra el secreto ausente, mientras que el error nativo
del pipeline (`ConfigurationError: 'GOOGLE_SHEET_ID' is not available…`) llega después de consultas y
no cubre las claves de firma RSA.

**Alternativa rechazada**: confiar en el fallo del propio pipeline. Consume cuota, tarda más y, para
las credenciales de Enable Banking, produce errores por banco (fallo parcial) en lugar de un fallo
único y claro.

---

## Decisión 8 — Secretos sólo en `env:`, nunca interpolados en `run:`

**Decisión**: cada `${{ secrets.X }}` aparece exclusivamente en claves `env:` (de paso o de job) y el
script bash los consume como variables (`"$X"`). Ninguna expresión `${{ secrets.* }}` se interpola
directamente dentro de un bloque `run:`. `permissions: contents: read` a nivel de workflow.

**Justificación**: FR-010 (y Principio IV). Un secreto interpolado en `run:` se expande *antes* de
que la plataforma aplique el enmascarado del log, y basta una comilla o un `echo` accidental para
filtrarlo; como variable de entorno, GitHub enmascara todas sus apariciones en el log del paso.
`permissions: contents: read` limita el `GITHUB_TOKEN` al mínimo necesario (sólo checkout).
`tests/unit/test_sync_workflow.py` verifica esta invariante de forma automatizada.

---

## Decisión 9 — Pruebas del workflow en Python, sin llamar a GitHub

**Decisión**: `tests/unit/test_sync_workflow.py` carga `.github/workflows/sync.yml` con
`yaml.safe_load` y afirma sobre su estructura, siguiendo el patrón ya establecido en
`tests/unit/test_ci_config.py`. Cero peticiones de red, cero llamadas a la API de GitHub (Principio
III).

**Cobertura mínima** (FR-013):

1. El fichero existe y es YAML válido.
2. Disparadores: `schedule` con una expresión cron diaria (`M H * * *`), `workflow_dispatch` sin
   `inputs`, y **ausencia** de `push` y `pull_request`.
3. `timeout-minutes: 10` en el job y `runs-on: ubuntu-latest`.
4. `concurrency` con `cancel-in-progress: false`.
5. `permissions: contents: read` y ningún permiso de escritura.
6. El job ejecuta `python -m banking sync` (el mismo comando que en local) y no ejecuta nada en
   `push`/PR.
7. Ningún secreto interpolado en `run:`; todo `${{ secrets.* }}` bajo `env:`.
8. Los 14 nombres de secreto esperados aparecen declarados.
9. El paso de resumen escribe en `$GITHUB_STEP_SUMMARY` y corre con `if: always()`.
10. Un paso final propaga el exit code del proceso (referencia a `steps.<id>.outputs.exit_code`).
11. El YAML no contiene formas de credencial literal (`-----BEGIN`, `Bearer `, `password=`).

**Alternativa rechazada**: validar el workflow con `act` o con la API de GitHub en CI. `act` no está
en las dependencias y ejecuta contenedores (fuera del alcance de un proyecto sin dependencias nuevas,
Anti-patrón #10); la API de GitHub sería una llamada de red real desde los tests (Anti-patrón #2).

---

## Decisión 10 — Detección de sesión PSD2 caducada: se reutiliza IT5 + IT6, sin código nuevo

**Decisión**: no se añade detección específica. Una sesión caducada la reporta el conector como fallo
de banco (`HTTP 403` o `status: "expired"`, IT5) → fallo parcial + email de IT6 con el banco y el
motivo → ejecución marcada como fallida (Decisión 5). Se documenta el procedimiento de
re-autorización en [quickstart.md](quickstart.md) (FR-012).

**Justificación**: el roadmap lo señala como riesgo esperado ("las sesiones PSD2 expiran cada 90-180
días y requieren re-autorización manual") y la señal ya existe. Añadir un chequeo proactivo de
caducidad implicaría consultar el estado de la sesión — otra petición PSD2 — y adelantar la alerta
unas horas, sin cambiar la acción del propietario (re-autorizar a mano).

---

## Decisión 11 — Runner, runtime e instalación

**Decisión**: `runs-on: ubuntu-latest`, `actions/checkout@v4`, `actions/setup-python@v5` con
`python-version: "3.12"`, y `pip install -r requirements.txt` + `pip install -e .` (sin
`requirements-dev.txt`: el scheduler ejecuta el producto, no la suite) más `pip-audit -r
requirements.txt` como gate de seguridad del artefacto desplegado.

**Justificación**: replican el entorno de CI y local (mismo intérprete, mismas versiones pinneadas).
Instalar sólo las dependencias de runtime reduce el tiempo de arranque y la superficie de ataque del
job que manipula credenciales reales. `pip-audit` sobre el runtime mantiene el Principio de
seguridad de dependencias en el camino que realmente va a producción.

**Alternativa rechazada**: cachear `~/.cache/pip` (`actions/cache`). Ahorraría unos segundos en un
job que corre una vez al día; añade superficie y un servicio externo más al workflow que maneja
secretos (YAGNI, Principio VII).

---

## Resumen de decisiones

| # | Decisión | Requisito que la motiva |
|---|---|---|
| 1 | `sync.yml` separado, sólo `schedule` + `workflow_dispatch` | FR-011 |
| 2 | `cron: "0 6 * * *"`, hora configurable editando esa línea | FR-001 |
| 3 | `.env` cifrado vía `secrets set` + `eb-config.json`/PEM en `$RUNNER_TEMP` | FR-004, FR-012 |
| 4 | Resumen construido en el workflow desde la salida del proceso | FR-006, FR-003 |
| 5 | `PIPESTATUS[0]` + último paso `exit` | FR-007 |
| 6 | `concurrency` sin cancelación | FR-008 |
| 7 | Validación de secretos como primer paso | FR-009 |
| 8 | Secretos sólo en `env:`, `permissions: contents: read` | FR-010 |
| 9 | Tests de YAML en `pytest`, sin red | FR-013 |
| 10 | Sesión PSD2 caducada = fallo de banco ya soportado + runbook | FR-012 |
| 11 | `ubuntu-latest` + Python 3.12 + sólo deps de runtime | FR-005, SC-006 |
