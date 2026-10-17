# Tareas: Scheduler en GitHub Actions (automatización completa)

**Entrada**: Documentos de diseño desde `specs/007-scheduler-github-actions/`

**Prerrequisitos**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅ | quickstart.md ✅

**Tests**: Los tests son **OBLIGATORIOS** según el Principio II (Test-First). Deben
escribirse antes de la implementación y verificarse en fallo (Red) antes de escribir
el workflow. El ciclo Red → Green → Refactor no es negociable.

**Organización**: US1 (P1) → US2 (P2) → US3 (P3). Esta iteración **no tiene código
Python de producción**: el único artefacto de producción es `.github/workflows/sync.yml`,
que se construye de forma incremental sobre los tests de su contrato
(`contracts/sync-workflow.md` § 6): US1 añade el disparador diario y el pipeline
completo (validación → aprovisionamiento → ejecución → propagación del exit code);
US2 añade el disparo manual y la exclusión mutua; US3 añade el resumen publicado.
Cada fase debe dejar en verde, sin regresiones, todo lo construido por las fases
anteriores.

**Nota YAML**: en PyYAML la clave sin comillas `on:` se parsea como el booleano
`True`. `.github/workflows/ci.yml` ya usa `"on":` entrecomillado; `sync.yml` DEBE
hacer lo mismo y el cargador de los tests DEBE normalizar ambas formas.

## Formato: `[ID] [P?] [Story] Descripción`

- **[P]**: Paralelizable — ficheros distintos, sin dependencia bloqueante
- **[Story]**: Etiqueta de historia de usuario (US1, US2, US3)
- Todas las rutas son relativas a la raíz del repositorio

---

## Fase 1: Setup (Inicialización de la funcionalidad)

**Propósito**: Confirmar que no hay dependencias nuevas y cerrar la única rendija por
la que una credencial podría acabar versionada sin querer.

- [ ] T001 [P] Confirmar que no hace falta pinear nada: los tests del workflow solo usarán `pyyaml` (ya en `requirements-dev.txt` con `pyyaml==6.0.3`, usado por `tests/unit/test_ci_config.py` desde IT1) y `pytest`; `requirements.txt`, `requirements-dev.txt` y `[project].dependencies` de `pyproject.toml` quedan **sin cambios** y `tests/unit/test_dependencies.py` sigue pasando (Anti-patrón #10, Principio VII)
- [ ] T002 [P] Añadir `*.pem` a `.gitignore` (sección `# Secrets`, junto a `.env` / `.env.*`), de forma que la clave RSA privada de Enable Banking no pueda commitearse por accidente desde una ruta local — la materialización en el runner usa `$RUNNER_TEMP`, fuera del workspace (FR-004, Principio IV)

**Checkpoint**: Cero dependencias nuevas; el `.gitignore` cubre las tres formas de
credencial que la iteración manipula (`.env`, `.env.*`, `*.pem`).

---

## Fase 2: Foundational (Infraestructura de pruebas bloqueante)

**Propósito**: Crear los dos ficheros de test que sostienen todo el contrato del
workflow, con su cargador YAML y las guardas de seguridad que se aplican al fichero
completo (no a un paso concreto). Sin esta infraestructura ninguna historia puede
verificarse.

**⚠️ CRÍTICO**: Ninguna historia puede empezar su implementación hasta que esta fase
esté completa.

### Tests para Foundational ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T009

- [ ] T003 [P] Crear `tests/unit/test_workflow_secret_guards.py` con guardas sobre todos los workflows: (1) ningún `${{ secrets.* }}` aparece dentro de un bloque `run:` (FR-010 — un secreto interpolado en `run:` se expande antes del enmascarado del log), (2) ningún fichero de `.github/workflows/*.yml` contiene formas de credencial literal (`-----BEGIN`, `Bearer `, `password=`, `enc:`, `private_key`) (Principio IV), (3) `.gitignore` ignora `.env`, `.env.*` y `*.pem`, (4) `ci.yml` **no** se ha modificado en sus disparadores (sigue con `push` y `pull_request` a `main`) ni en sus cinco gates (`pip-audit`, `ruff check`, `ruff format`, `mypy`, `pytest`) — FR-011; los puntos (2)-(4) son guardas que pasan desde el inicio (se documenta así, sin fingir un Red) y el punto (1) se vuelve efectivo al crear el workflow en T010
- [ ] T004 [P] Crear `tests/unit/test_sync_workflow.py` con el cargador y las primeras aserciones de existencia: `SYNC_WORKFLOW = Path(".github/workflows/sync.yml")`, helper `_load_workflow() -> dict[str, Any]` que normaliza la clave `on` (acepta la forma booleana `True` que PyYAML produce con `on:` sin comillas), `test_workflow_file_exists` y `test_workflow_is_valid_yaml` (FR-001) — **deben fallar** en este punto porque `.github/workflows/sync.yml` todavía no existe

**Checkpoint**: T001-T004 ejecutados. `test_sync_workflow.py` falla en rojo por
ausencia del workflow; las guardas de `test_workflow_secret_guards.py` están activas.

---

## Fase 3: Historia de Usuario 1 — Sincronización diaria automática (Prioridad: P1) 🎯 MVP

**Objetivo**: GitHub ejecuta la sincronización una vez al día sin intervención del
propietario: valida los 14 secretos antes de tocar ninguna API, los materializa en
los dos mecanismos que el código ya usa, ejecuta `python -m banking sync` y hace que
el estado del job coincida con el exit code real del pipeline (`0`-`4`).

**Prueba independiente**: Con el workflow en la rama, `gh workflow run sync.yml` (o
el cron, una vez en `main`) produce una ejecución que escribe en la pestaña del mes
y termina con el estado del proceso; sin secretos, la ejecución falla en menos de un
minuto nombrando el secreto ausente y sin llamadas a las APIs bancarias.

### Tests para US1 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T009

- [ ] T005 [US1] Añadir a `tests/unit/test_sync_workflow.py` los tests de disparador (FR-001, FR-011): `schedule` contiene exactamente una expresión cron diaria (regex `^\d{1,2} \d{1,2} \* \* \*$`) y el conjunto de claves de `on` está contenido en `{"schedule", "workflow_dispatch"}` — sin `push`, `pull_request`, `release`, `workflow_run` ni `repository_dispatch`
- [ ] T006 [US1] Añadir a `tests/unit/test_sync_workflow.py` los tests del job (FR-005, Decisión 11): un único job con `runs-on: ubuntu-latest`, `timeout-minutes: 10`, `actions/checkout@v4`, `actions/setup-python@v5` con `python-version: "3.12"`, e instalación de dependencias con `pip install -r requirements.txt`, `pip install -e .` y `pip-audit -r requirements.txt` (y **sin** `requirements-dev.txt`)
- [ ] T007 [US1] Añadir a `tests/unit/test_sync_workflow.py` los tests de configuración (FR-004, FR-009, Decisión 3): los 14 nombres de `contracts/sync-workflow.md` § 4.2 aparecen en `env:` de job o de paso; el paso de validación precede al de sincronización y falla con exit code ≠ 0 si falta alguno (sin imprimir valores); el de aprovisionamiento invoca `python -m banking secrets set`, escribe en `$RUNNER_TEMP`, fija `BANKING_EB_CONFIG_DIR`, genera `eb-config.json` con `app_id` y `private_key_path`, y da permisos `600` al PEM
- [ ] T008 [US1] Añadir a `tests/unit/test_sync_workflow.py` los tests de ejecución y propagación (FR-003, FR-007, Decisión 5): el paso de sincronización ejecuta `python -m banking sync` con `2>&1 | tee` a un log, usa `PIPESTATUS[0]` y escribe `exit_code=…` en `$GITHUB_OUTPUT`, y el último paso del job termina con `exit` sobre `steps.<id>.outputs.exit_code`

### Implementación para US1

- [ ] T009 [US1] Crear `.github/workflows/sync.yml` con `name: Sync diaria`, `"on":` entrecomillado con `schedule: - cron: "0 6 * * *"` (comentario con la equivalencia en hora de Madrid y la nota de que es el único punto a tocar para cambiar la hora), y el job `sync` con `runs-on: ubuntu-latest`, `timeout-minutes: 10`, `permissions: contents: read`, más los pasos `Checkout`, `Preparar Python` e `Instalar dependencias` (T005, T006 en verde)
- [ ] T010 [US1] Añadir a `.github/workflows/sync.yml` el bloque `env:` con los 14 secretos referenciados como `${{ secrets.<NOMBRE> }}`, el paso `Validar configuración` (bash que recorre los nombres, lista los que faltan y termina con exit code 1 sin llegar a red) y el paso `Provisionar configuración` (11 llamadas a `python -m banking secrets set` con `BANKING_MASTER_KEY` en el entorno, `mkdir -p "$RUNNER_TEMP/eb"`, escritura de `eb-config.json` + `private_key.pem`, `chmod 600`, `BANKING_EB_CONFIG_DIR` exportado a `$GITHUB_ENV`) — T007 y la guarda (1) de T003 en verde
- [ ] T011 [US1] Añadir a `.github/workflows/sync.yml` el paso `Ejecutar sincronización` (`set +e`, `set -o pipefail`, `python -m banking sync 2>&1 | tee "$RUNNER_TEMP/sync-output.log"`, `code=${PIPESTATUS[0]}`, `echo "exit_code=$code" >> "$GITHUB_OUTPUT"`, `exit 0` para no abortar antes del resumen) y el paso final `Propagar resultado` (`exit ${{ steps.sync.outputs.exit_code }}`) — T008 en verde

**Checkpoint**: US1 completo. El workflow dispara a diario, valida y provisiona
secretos, ejecuta el mismo comando que en local y marca la ejecución como fallida
con cualquier exit code distinto de 0.

---

## Fase 4: Historia de Usuario 2 — Disparo manual desde GitHub (Prioridad: P2)

**Objetivo**: Poder lanzar la misma sincronización a mano desde la interfaz de GitHub,
sin parámetros, sin que dos ejecuciones escriban nunca a la vez en la hoja.

**Prueba independiente**: `gh workflow run sync.yml` sin parámetros ejecuta
exactamente los mismos pasos que la ejecución programada; dos ejecuciones lanzadas
seguidas se serializan (una espera a la otra).

### Tests para US2 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T013

- [ ] T012 [US2] Añadir a `tests/unit/test_sync_workflow.py` los tests de US2 (FR-002, FR-008): `workflow_dispatch` existe y no declara `inputs`; el job declara `concurrency` con `group: banking-sync` y `cancel-in-progress: false`

### Implementación para US2

- [ ] T013 [US2] Añadir a `.github/workflows/sync.yml` el disparador `workflow_dispatch:` (sin `inputs`) y el bloque `concurrency: {group: banking-sync, cancel-in-progress: false}` a nivel de job, con un comentario que explique por qué no se cancela (una escritura interrumpida dejaría la pestaña incompleta) — T012 en verde

**Checkpoint**: US2 completo. La ejecución manual replica la programada y el grupo de
concurrencia impide escrituras simultáneas sobre la misma pestaña.

---

## Fase 5: Historia de Usuario 3 — Resumen en la página de la ejecución (Prioridad: P3)

**Objetivo**: Cada ejecución publica en su página un resumen legible con bancos
procesados, movimientos escritos, fallos con motivo y duración, sin abrir los logs.

**Prueba independiente**: Abrir la página de una ejecución (exitosa y fallida) y ver
el resumen con los cuatro datos; si el proceso no llegó a imprimir nada, el resumen
lo dice y remite a los logs.

### Tests para US3 ⚠️ OBLIGATORIO — escribir primero, verificar ROJO antes de T015

- [ ] T014 [US3] Añadir a `tests/unit/test_sync_workflow.py` los tests del resumen (FR-006, Decisión 4): existe un paso con `if: always()` que escribe en `$GITHUB_STEP_SUMMARY`; su script incluye el estado y el `exit_code` del paso de sincronización; filtra las líneas de resumen del log (`Sincronización`, `  - `) en lugar de volcar el log completo; y contempla el caso sin salida (fallo de arranque) con una nota explícita; además el paso de resumen se ejecuta **antes** del de propagación del exit code

### Implementación para US3

- [ ] T015 [US3] Añadir a `.github/workflows/sync.yml` el paso `Publicar resumen` (`if: always()`, `env: EXIT_CODE: ${{ steps.sync.outputs.exit_code }}`) que escribe en `$GITHUB_STEP_SUMMARY` un encabezado (`## Sincronización bancaria — <fecha>`, estado legible, exit code) y, en bloque de código, las líneas del log que empiezan por `Sincronización`, `ERROR` o `  - `, con la nota de degradación cuando el log no existe o está vacío — T014 en verde

**Checkpoint**: Las tres historias completas. El workflow cumple las 14 invariantes de
`contracts/sync-workflow.md` § 6.

---

## Fase 6: Polish y cierre

**Propósito**: Alinear la documentación de proyecto, pasar todos los gates de calidad,
auditar seguridad y cerrar la iteración con la ejecución real que exige el roadmap.

- [ ] T016 [P] Actualizar `docs/context.md`: marcar IT7 como **Implementada** en la tabla de iteraciones (con la fecha), y añadir una sección `Despliegue y operación` que describa el workflow (disparadores, hora, `concurrency`, `timeout-minutes: 10`, resumen publicado), el inventario resumido de los 14 secretos de GitHub y el enlace a `specs/007-scheduler-github-actions/quickstart.md` para los runbooks de rotación y de re-autorización PSD2 (FR-012)
- [ ] T017 [P] Añadir a `quickstart.md` (raíz) la sección **IT7 — ejecución automática diaria**: alta de los 14 secretos con `gh secret set`, comprobación con `gh secret list`, primera ejecución real con `gh workflow run sync.yml`, cómo cambiar la hora (una línea del cron) y puntero a los runbooks de PSD2/rotación; incluir la advertencia de que el cron solo se ejecuta desde `main`
- [ ] T018 [P] Actualizar `specs/007-scheduler-github-actions/plan.md`: sustituir el bloque `➡️ Siguiente paso` por `/speckit-implement` sobre `tasks.md` y añadir `tasks.md` al árbol de documentación de la funcionalidad (Principio I)
- [ ] T019 Ejecutar y dejar en verde la batería completa: `pytest tests/` (148 tests previos + los nuevos, sin regresiones), `ruff check src/ tests/`, `ruff format --check src/ tests/`, `mypy src/` y `pip-audit` sobre el entorno — cero avisos, cero errores (Principio VI)
- [ ] T020 Auditoría de seguridad y anti-patrones: `git grep` de formas de credencial (`-----BEGIN`, `Bearer `, `password`, `enc:` real, `session_id` completo) sobre todo el repositorio incluido `.github/workflows/` (debe salir limpio salvo placeholders de `.env.example`), confirmar que ningún test nuevo hace red ni depende de GitHub (Principio III), y que no se ha añadido ningún `print()` en módulos de núcleo (Anti-patrón #6)
- [ ] T021 Verificar la trazabilidad contrato → test: para cada una de las 14 invariantes de `contracts/sync-workflow.md` § 6 existe un test con nombre explícito en `tests/unit/test_sync_workflow.py` o `tests/unit/test_workflow_secret_guards.py`, y los 14 nombres de secreto coinciden exactamente en workflow, tests, `quickstart.md` y `data-model.md` (FR-004, FR-013)
- [ ] T022 Cierre de iteración (post-merge, requisito del roadmap): mergear la PR, ejecutar `gh workflow run sync.yml` sobre `main`, registrar en `docs/context.md` (sección `Despliegue y operación`) la primera ejecución real exitosa con fecha y resultado del resumen, y confirmar que el cron aparece en `gh run list --workflow=sync.yml`
- [ ] T023 Publicar la rama y abrir la PR (`feat(007): schedule daily sync in GitHub Actions (IT7)`) referenciando las tareas implementadas (`Implements T001-T021`), con el resumen de las 11 decisiones de `research.md` y la evidencia de los gates en verde; CI debe quedar en `success`

---

## Dependencias entre fases

```text
Fase 1  T001, T002  ──→ Fase 2  T003, T004
                          │
                          ▼
                    Fase 3  T005…T011   (US1 — MVP)
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
  Fase 4 T012-T013   Fase 5 T014-T015   Fase 6 T016-T023
      (US2)              (US3)               (cierre)
```

- T002 bloquea la guarda (3) de T003.
- T004 bloquea T005-T008, T012 y T014 (todos añaden tests al mismo cargador).
- US2 (T012-T013) y US3 (T014-T015) son incrementos independientes sobre el workflow de
  US1, pero comparten fichero con US1: se ejecutan en orden.
- T019-T021 requieren todo lo anterior; T022 requiere la PR mergeada; T023 es la última.

## Estrategia de validación

1. **Red por fase**: cada bloque de tests debe verse fallar antes de su implementación
   (T004 antes de T009; T005-T008 antes de T009-T011; T012 antes de T013; T014 antes
   de T015).
2. **Guards desde el inicio**: las guardas de `test_workflow_secret_guards.py` que
   pasan vacías (sin secretos declarados) se vuelven efectivas al crear el workflow;
   se documenta honestamente en el propio fichero de test.
3. **Green acumulativo**: cada checkpoint deja la suite completa en verde.
4. **Validación real**: fuera de CI, `gh workflow run sync.yml` (T022), nunca desde los
   tests (Principio III).

## Reglas de paralelización

- Solo los grupos marcados `[P]` pueden ejecutarse en paralelo: T001/T002 (ficheros
  distintos), T003/T004 (ficheros de test distintos) y T016/T017/T018 (documentos
  distintos).
- Todo lo demás toca `.github/workflows/sync.yml` o `tests/unit/test_sync_workflow.py`
  y es estrictamente secuencial.

---

## Trazabilidad contrato → test (T021)

Cada invariante de [`contracts/sync-workflow.md`](contracts/sync-workflow.md) § 6
tiene al menos un test en `tests/unit/test_sync_workflow.py`. Verificado
programáticamente: los 21 tests del fichero existen y la suite está en verde.

| # | Invariante | Test |
|---|---|---|
| 1 | `sync.yml` existe y es YAML válido | `test_workflow_file_exists`, `test_workflow_is_valid_yaml_with_a_name` |
| 2 | Sólo `schedule` (cron diario) y `workflow_dispatch` (sin `inputs`) | `test_schedule_trigger_is_a_single_daily_cron`, `test_manual_trigger_takes_no_parameters` |
| 3 | Ausencia total de `push` y `pull_request` | `test_no_unexpected_triggers` |
| 4 | `timeout-minutes: 10` y `runs-on: ubuntu-latest` | `test_job_runs_on_ubuntu_with_a_ten_minute_timeout` |
| 5 | `concurrency` con `cancel-in-progress: false` | `test_concurrent_runs_are_serialised_without_cancellation` |
| 6 | `permissions` de sólo lectura | `test_workflow_permissions_are_read_only` |
| 7 | El job ejecuta `python -m banking sync` | `test_sync_step_runs_the_same_command_as_local` |
| 8 | Todos los `${{ secrets.* }}` están bajo `env:` | `test_every_required_secret_is_declared_exactly_once` + `test_workflow_secret_guards.py::test_no_secret_expression_is_interpolated_into_a_run_block` |
| 9 | Los 14 nombres de secreto están declarados | `test_every_required_secret_is_declared_exactly_once` |
| 10 | Resumen con `if: always()` y `$GITHUB_STEP_SUMMARY` | `test_summary_step_publishes_even_when_the_sync_fails`, `test_summary_reports_state_and_process_exit_code`, `test_summary_lists_banks_movements_failures_and_duration`, `test_summary_degrades_gracefully_without_process_output` |
| 11 | Paso final que propaga el exit code | `test_final_step_propagates_the_process_exit_code`, `test_summary_is_published_before_the_exit_code_is_propagated` |
| 12 | Sin formas de credencial literal en el YAML | `test_workflow_secret_guards.py::test_workflows_contain_no_literal_credentials` |
| 13 | La validación precede a la sincronización | `test_configuration_is_validated_before_any_external_call` |
| 14 | `ci.yml` sin cambios (triggers + cinco gates) | `test_workflow_secret_guards.py::test_ci_workflow_still_gates_every_commit`, `test_sync_workflow_is_a_separate_file_from_ci` |

Cobertura adicional no exigida por el contrato: `test_python_runtime_and_actions_are_pinned`
(versiones de acciones y Python), `test_runtime_dependencies_are_installed_and_audited`
(FR-013) y `test_configuration_is_provisioned_into_the_existing_mechanisms` (Decisión 3).
