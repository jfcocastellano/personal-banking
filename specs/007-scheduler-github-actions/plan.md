# Plan de Implementación: Scheduler en GitHub Actions (automatización completa)

**Rama**: `007-scheduler-github-actions` | **Fecha**: 2026-10-17 | **Spec**: [spec.md](spec.md)

**Entrada**: Especificación de la funcionalidad desde `specs/007-scheduler-github-actions/spec.md`

> **➡️ Siguiente paso**: ejecutar `/speckit-tasks` para generar [tasks.md](tasks.md) y después
> `/speckit-implement`. El flujo SDD es spec → plan → **tasks** → implement (Principio I de la
> constitución).

---

## Resumen

Cerrar el proyecto: que la sincronización de los cuatro bancos se ejecute **sola, una vez al día**,
sin intervención del propietario, y que pueda relanzarse a mano desde GitHub. La iteración **no añade
lógica de negocio ni código Python de producción**: añade un workflow
(`.github/workflows/sync.yml`) que orquesta el binario ya existente con el mismo comando que en local
(`python -m banking sync`), más la suite que valida ese workflow sin tocar la red.

El workflow hace cuatro cosas:

1. **Dispara**: `schedule` con cron diario (`0 6 * * *`) y `workflow_dispatch` sin parámetros; nada
   más (ni `push` ni `pull_request`). `concurrency: banking-sync` con `cancel-in-progress: false`
   garantiza que nunca haya dos ejecuciones escribiendo en la misma pestaña.
2. **Configura**: valida los 14 secretos antes de cualquier llamada externa (protege la cuota PSD2 de
   4 peticiones/cuenta/día) y los materializa en los dos mecanismos que el código ya usa: el `.env`
   cifrado del `SecretStore` (11 claves, vía `python -m banking secrets set`) y el fichero de firma
   RSA de Enable Banking (`eb-config.json` + PEM en `$RUNNER_TEMP`, fuera del workspace).
3. **Ejecuta**: `python -m banking sync` con `tee` a log, capturando el exit code real del proceso
   (`PIPESTATUS[0]`) para que el estado del job coincida con el del pipeline `0`-`4` de IT5/IT6.
4. **Publica**: escribe en `$GITHUB_STEP_SUMMARY`, con `if: always()`, un resumen con los cuatro datos
   que exige la constitución (bancos procesados, movimientos escritos, fallos con motivo, duración),
   construido a partir de la salida del proceso — sin lógica de CI dentro del código Python.

El cierre de la iteración exige una **ejecución real exitosa documentada** (roadmap, Iteración 7).

Ver [research.md](research.md) para las 11 decisiones de diseño (workflow separado, hora en el cron,
las dos familias de credenciales, resumen construido desde stdout, propagación del exit code,
concurrencia, validación temprana, exposición de secretos, tests sin red, PSD2 y entorno de ejecución).

---

## Contexto Técnico

**Lenguaje/Versión**: Python 3.12 (sin cambios de runtime). El único artefacto nuevo de producción es
YAML de GitHub Actions; el código Python nuevo es de pruebas.

**Dependencias principales**: **ninguna nueva**. `pyyaml==6.0.3` ya está en `requirements-dev.txt`
(lo usa `tests/unit/test_ci_config.py` desde IT1) y basta para cargar el workflow en los tests
(Anti-patrón #10). En el runner, el workflow instala sólo `requirements.txt` + el paquete
(`pip install -e .`): `cryptography`, `httpx`, `PyJWT`, `gspread`.

**Almacenamiento**: ninguno persistente. Los secretos existen en memoria y en ficheros efímeros del
runner (`.env` en el workspace, `$RUNNER_TEMP/eb/*`), destruidos al terminar la ejecución. No hay
caché, ni artefactos, ni estado entre ejecuciones (Principio VII).

**Testing**: `pytest` con `yaml.safe_load` sobre `.github/workflows/sync.yml`, siguiendo el patrón de
`tests/unit/test_ci_config.py`. 14 invariantes verificadas (contrato § 6), **cero** llamadas a la API
de GitHub ni a ningún servicio (Principio III). La validación funcional real se hace con
`workflow_dispatch` sobre el repositorio (documentada en [quickstart.md](quickstart.md)).

**Plataforma objetivo**: GitHub Actions, `ubuntu-latest`, `actions/checkout@v4` +
`actions/setup-python@v5` (3.12), `timeout-minutes: 10`, `permissions: contents: read`. El cron se
ejecuta sólo desde la rama por defecto (`main`) — validación previa al merge por `workflow_dispatch`
o en local.

**Tipo de proyecto**: infraestructura de ejecución sobre un CLI ya existente (sin cambios en
`src/banking/`).

**Objetivos de rendimiento**: job completo por debajo de 10 minutos (FR-005, SC-006); sincronización
real < 2 minutos (SLO de IT5); fallo por configuración ausente en menos de 1 minuto (FR-009, SC-007).
Concurrencia: una ejecución activa como máximo; el cron diario consume 1 de las 4 peticiones PSD2 por
cuenta y día.

**Restricciones**:
- Sin lógica de CI en el código Python (FR-003): el workflow ejecuta el mismo comando que en local y
  no se añaden flags ni rutas de salida al CLI.
- Ninguna credencial en el YAML, en el repositorio ni en logs/resúmenes (FR-004, FR-010, Principio
  IV); `${{ secrets.* }}` sólo bajo `env:`.
- Ningún test hace red (FR-013, Principio III); ningún test nuevo requiere dependencias.
- `ci.yml` **no se toca** (FR-011): sigue disparándose en `push`/`pull_request` a `main` con sus
  cinco gates.
- Todos los tests nuevos con anotaciones de tipo completas y sin `print()` (Principio VI,
  Anti-patrón #6).
- El propietario es el único operador; sin reintentos automáticos ni recuperación (YAGNI).

**Escala/Alcance**: 1 workflow nuevo (`~80` líneas), 1 fichero de tests nuevo, 1 documento de runbook
(quickstart), actualización de `docs/context.md`. Fuera de alcance: métricas históricas, artefactos,
notificación de fallos de arranque (limitación conocida de IT6), automatización de rotación de
credenciales.

---

## Constitution Check

*GATE: Debe pasar antes de la investigación de Fase 0. Se revalida después del diseño de Fase 1.*

- [x] La especificación existe en `specs/007-scheduler-github-actions/spec.md` y ha pasado la
  validación de calidad sin `[NEEDS CLARIFICATION]` (Principio I)
- [x] Ninguna prueba realiza llamadas de red — `test_sync_workflow.py` sólo lee y parsea YAML con
  `yaml.safe_load`; no invoca la API de GitHub ni el workflow (Principio III)
- [x] No se introduce base de datos ni persistencia local — los secretos viven en ficheros efímeros
  del runner; no hay caché ni artefactos (Principio VII)
- [x] Los secretos fluyen por GitHub Secrets y se materializan en el mecanismo cifrado existente
  (`SecretStore` + `eb-config.json`); ninguno hardcodeado, ninguno interpolado en `run:` (Principio
  IV)
- [x] Los fallos de conector se siguen manejando de forma independiente — el workflow no altera el
  pipeline de IT5 ni el envío agregado de IT6 (Principio V)
- [x] Todas las funciones de test llevarán anotaciones de tipo completas (`mypy src/` no cubre
  `tests/`, pero se respeta el estilo y `ruff` sí lo lintea) (Principio VI)
- [x] Ninguna función superará complejidad ciclomática 10 — los tests son afirmaciones lineales; los
  scripts del workflow son bash declarativo (Principio VI)
- [x] No se añade ninguna dependencia — `pyyaml` ya está pinneado en `requirements-dev.txt`
  (Anti-patrón #10)

**Revalidación post-diseño (Fase 1)**: sin violaciones nuevas.
`contracts/sync-workflow.md` formaliza los disparadores, pasos, invariantes y el contrato de
configuración/resultado; `data-model.md` describe el workflow, el inventario de 14 secretos, la
ejecución y el resumen sin introducir ninguna entidad en el proceso. La única dependencia nueva es
operativa (14 secretos a provisionar), no de código.

**Punto de atención justificado**: el resumen se construye a partir del texto que imprime el CLI
(Decisión 4). Es una dependencia de formato entre workflow y proceso; se mitiga fijando la cabecera
del resumen con los tests existentes de `cli/sync.py` **y** con el test del workflow, de modo que un
cambio de texto rompa ambos a la vez. La alternativa (flag `--summary-json` en el CLI) violaría
FR-003 y se rechaza explícitamente en `research.md`.

---

## Estructura del Proyecto

### Documentación (esta funcionalidad)

```text
specs/007-scheduler-github-actions/
├── plan.md                                ← este fichero (/speckit-plan)
├── tasks.md                               ← salida de /speckit-tasks
├── research.md                            ← salida de Fase 0 (11 decisiones)
├── data-model.md                          ← salida de Fase 1 (workflow, secretos, ejecución, resumen)
├── quickstart.md                          ← salida de Fase 1 (despliegue + runbooks)
├── contracts/
│   └── sync-workflow.md                   ← contrato del workflow (disparadores, pasos, invariantes)
└── checklists/
    └── requirements.md
```

### Código fuente (raíz del repositorio)

```text
.github/
└── workflows/
    ├── ci.yml                             # SIN CAMBIOS: push/PR + 5 gates
    └── sync.yml                           # NUEVO: schedule + workflow_dispatch, 8 pasos

src/banking/                               # SIN CAMBIOS en todo el árbol
tests/
└── unit/
    ├── test_sync_workflow.py              # NUEVO: 14 invariantes del workflow (sin red)
    └── test_ci_config.py                  # SIN CAMBIOS: sigue validando ci.yml

docs/
└── context.md                             # MODIFICADO: IT7 implementada, despliegue y runbook
quickstart.md                              # MODIFICADO: sección IT7 (uso operativo)
```

**Decisión de estructura**: el workflow vive junto al de CI, en `.github/workflows/`, sin tocar
`ci.yml` (FR-011 y compatibilidad con los tests existentes). Los tests del workflow viven en
`tests/unit/` junto a `test_ci_config.py`, que ya estableció el patrón "valida la configuración de
infraestructura como código".

### Flujo de la ejecución

```text
schedule (06:00 UTC)  ─┐
                       ├─→ [concurrency: banking-sync]
workflow_dispatch ─────┘         │
                                 ▼
              1. Validar configuración (14 secretos, sin red)
                                 │ falta → exit ≠ 0 (sin tocar APIs)
                                 ▼
              2. Checkout · 3. Python 3.12 · 4. pip + pip-audit
                                 ▼
              5. Provisionar: .env cifrado (secrets set) + eb-config.json/PEM
                                 ▼
              6. python -m banking sync 2>&1 | tee log  → exit_code = PIPESTATUS[0]
                                 │                        (0 éxito · 1 total · 2 Sheets · 3 parcial · 4 email)
                                 ▼
              7. Publicar resumen en $GITHUB_STEP_SUMMARY (if: always())
                                 ▼
              8. exit $exit_code  → estado del job = estado real del pipeline
                                 │
                                 └─→ fallo → email de IT6 (ya en el proceso)
```

---

## Complexity Tracking

*Sin violaciones que justificar.* No hay código de producción nuevo, ni capas de abstracción nuevas,
ni persistencia, ni dependencias. Los scripts del workflow son bash declarativo de un solo nivel; los
tests son afirmaciones secuenciales sin anidamiento condicional. La complejidad que se evita (parsear
el resultado en YAML/bash con lógica condicional) se resuelve delegando en el formato de salida ya
probado del CLI y en dos pasos bash independientes (resumen y propagación del exit code).
