# Plan de Implementación: Pipeline de Sincronización ING → Google Sheets

**Rama**: `004-ing-sheets-sync` | **Fecha**: 2026-08-09 | **Spec**: [spec.md](spec.md)

**Entrada**: Especificación de la funcionalidad desde `specs/004-ing-sheets-sync/spec.md`

---

## Resumen

Implementar el pipeline que conecta el conector ING España (`IngConnector`,
IT2) con el escritor de Google Sheets (`SheetsWriter`, IT3): dado el mes en
curso, obtiene los movimientos liquidados desde el día 1 hasta la fecha de
ejecución, los transforma a filas con el esquema fijo (fecha de
liquidación, banco, descripción, importe, divisa) y los escribe en la
pestaña `YYYY-MM` correspondiente, sobrescribiéndola por completo
(idempotente el mismo día, reutilizando el comportamiento ya provisto por
IT3). Expone un punto de entrada CLI (`python -m banking sync`) que
imprime un resumen en éxito y sale con un código de salida distinto por
sistema responsable en fallo (`1` = ING, `2` = Sheets). No introduce
protocolo externo nuevo — solo orquesta los dos componentes ya fusionados.

Ver `research.md` para las decisiones de diseño clave (separación
núcleo/CLI, inyección de dependencias, extensión mínima de `IngConnector`
para exponer el nombre del banco, transformación de tipos, categorización
de fallos).

---

## Contexto Técnico

**Lenguaje/Versión**: Python 3.12 (mismo runtime que IT1-IT3)

**Dependencias principales**: Ninguna nueva. Reutiliza `IngConnector`
(`banking.connectors.ing`, IT2) y `SheetsWriter` (`banking.sheets.writer`,
IT3) ya presentes; `argparse` (stdlib) para el subcomando CLI, mismo
patrón que `cli/secrets.py` (IT1).

**Almacenamiento**: Ninguno. Sin persistencia local; los únicos accesos a
disco son la configuración cifrada ya establecida (IT1-IT3).

**Testing**: `pytest` con `pytest-mock`; el núcleo (`sync.py`) se testea
inyectando `Mock(spec=IngConnector)` y `Mock(spec=SheetsWriter)` — no
mockea `httpx`/`gspread` de nuevo, esa cobertura ya existe en IT2/IT3
(FR-010). La capa CLI (`cli/sync.py`) se testea invocando `handle()`
directamente con un `argparse.Namespace`, mismo patrón que
`test_cli_secrets.py` (IT1).

**Plataforma objetivo**: Igual que IT1-IT3 — GitHub Actions `ubuntu-latest`
para CI; desarrollo local multiplataforma.

**Tipo de proyecto**: Extensión del CLI existente del paquete `banking`
(`src/banking/cli/`) más un nuevo módulo núcleo de orquestación
(`src/banking/sync.py`). Primer punto de entrada funcional de extremo a
extremo del sistema.

**Objetivos de rendimiento**: Una ejecución completa en menos de 2 minutos
(SC-006), heredado del presupuesto de sincronización completa ya definido
en la constitución — no es un umbral nuevo.

**Restricciones**:
- `sync.py` (núcleo) NO DEBE llamar a `print()` — solo `cli/sync.py` puede
  (Anti-patrón #6)
- El pipeline NO DEBE escribir en Sheets si falla la obtención de
  movimientos de ING (FR-007)
- Códigos de salida distintos por sistema responsable: `1` = ING, `2` =
  Sheets (decidido en `/speckit-clarify`)
- Ningún mensaje (resumen, log, error) puede interpolar credenciales, JWT,
  `session_id` completo, ni JSON de cuenta de servicio (FR-012) — se
  cumple por composición, reutilizando excepciones ya seguras de IT2/IT3
- Cero llamadas de red reales en cualquier test (Principio III)

**Escala/Alcance**: Una única cuenta/entidad (ING España), una pestaña por
ejecución. Sin concurrencia. Orquestar varios bancos con resiliencia
parcial es IT5.

---

## Constitution Check

*GATE: Debe pasar antes de la investigación de Fase 0. Se revalida después del diseño de Fase 1.*

- [x] La especificación existe en `specs/004-ing-sheets-sync/spec.md` y ha pasado por `/speckit-clarify` (Principio I)
- [x] Ninguna prueba realiza llamadas de red reales — FR-010 exige mockear tanto `IngConnector` como `SheetsWriter`; ambos ya se inyectan por diseño desde IT2/IT3 (Principio III)
- [x] No se introduce base de datos ni persistencia local — no hay E/S de disco nueva más allá de la configuración cifrada ya existente (Principio VII)
- [x] Los secretos fluyen por el mecanismo cifrado existente — `GOOGLE_SHEET_ID` vía `SecretStore`, mismas credenciales ING/Sheets ya gestionadas por IT2/IT3 (Principio IV)
- [x] Los fallos se manejan de forma independiente por sistema responsable — `IngSyncError`/`SheetsSyncError` con códigos de salida distintos (FR-007/FR-008); la resiliencia *entre varios bancos* queda fuera de alcance (IT5) (Principio V)
- [x] Todas las funciones públicas llevarán anotaciones de tipo completas — exigido por `mypy` strict (Principio VI)
- [x] Ninguna función superará complejidad ciclomática 10 — `run_sync()` delega transformación (`_transform`) y construcción de dependencias por defecto en funciones pequeñas separadas (Principio VI)
- [x] No se añade ninguna dependencia de terceros nueva (Anti-patrón #10 — no aplica, nada que pinear)

**Revalidación post-diseño (Fase 1)**: Sin violaciones nuevas. El diseño en
`data-model.md` y `contracts/` no introduce persistencia ni una capa
adicional de abstracción más allá de la separación núcleo/CLI ya
justificada (Decisión 1 de `research.md`); la única extensión a un módulo
ya fusionado (`IngConnector.BANK_NAME`) es un atributo de clase que
reexpone una constante existente, sin tocar lógica de negocio de IT2.

---

## Estructura del Proyecto

### Documentación (esta funcionalidad)

```text
specs/004-ing-sheets-sync/
├── plan.md                           ← este fichero (/speckit-plan)
├── research.md                       ← salida de Fase 0
├── data-model.md                     ← salida de Fase 1
├── quickstart.md                     ← salida de Fase 1 (guía de validación)
├── contracts/
│   ├── cli-sync-interface.md         ← contrato de la interfaz CLI (`banking sync`)
│   └── sync-pipeline-interface.md    ← contrato de la interfaz Python interna (`run_sync`)
└── checklists/
    └── requirements.md
```

### Código fuente (raíz del repositorio)

```text
src/
└── banking/
    ├── __main__.py                    # MODIFICADO: registra el subcomando "sync"
    ├── sync.py                        # NUEVO: run_sync(), SyncResult, IngSyncError, SheetsSyncError
    ├── cli/
    │   ├── secrets.py
    │   └── sync.py                    # NUEVO: add_parser(), handle() — adaptador CLI, print + exit code
    ├── config/
    │   └── secret_store.py
    ├── connectors/
    │   └── ing.py                     # MODIFICADO: + IngConnector.BANK_NAME (atributo de clase público)
    └── sheets/
        └── writer.py

tests/
└── unit/
    ├── test_main.py                   # MODIFICADO: cubre el subcomando "sync" registrado
    ├── test_sync.py                   # NUEVO: run_sync() con IngConnector/SheetsWriter mockeados
    ├── test_cli_sync.py               # NUEVO: cli/sync.py — resumen, mensajes de error, códigos de salida
    ├── connectors/
    │   └── test_ing.py                # MODIFICADO: + test de IngConnector.BANK_NAME
    ├── sheets/
    │   └── test_writer.py
    └── config/
        └── test_secret_store.py
```

**Decisión de estructura**: `sync.py` vive directamente bajo `src/banking/`
(no dentro de `connectors/` ni `sheets/`, que son específicos de un
sistema externo cada uno) porque orquesta ambos — es el primer módulo que
opera "entre" componentes, no dentro de uno. `cli/sync.py` sigue
exactamente el patrón ya establecido por `cli/secrets.py` (IT1): un
adaptador fino que traduce `argparse.Namespace` ↔ llamada a la función
núcleo ↔ `print()`/código de salida. No se introduce ninguna capa
"servicio" adicional — dos módulos nuevos (núcleo + CLI) son suficientes
(YAGNI, Principio VII).

---

## Complexity Tracking

> Solo se completa si el Constitution Check tiene violaciones que justificar.

Ninguna violación. Dos módulos nuevos (`sync.py`, `cli/sync.py`) más una
extensión de un atributo de clase en `ing.py` — sin capas adicionales.

---

## Decisiones de Diseño (resumen de Fase 0)

Racional completo y alternativas en `research.md`.

| Decisión | Elección | Razón clave |
|----------|----------|--------------|
| Separación núcleo/CLI | `sync.py` (lógica, sin `print()`) + `cli/sync.py` (adaptador CLI) | Mismo patrón que `cli/secrets.py` (IT1); cumple Anti-patrón #6 |
| Inyección de dependencias | `run_sync(connector=, writer=, document_id=, today=)`, todos opcionales | Mismo patrón que `IngConnector`/`SheetsWriter`; tests sin tocar `SecretStore` real para el núcleo |
| Nombre del banco | `IngConnector.BANK_NAME` (atributo de clase público nuevo) | Decidido en `/speckit-clarify` (FR-011); extensión mínima, reexpone constante ya existente |
| Transformación de importe | `float(tx.amount)`, no `str(...)` | `SheetsWriter` solo acepta primitivos JSON-serializables (IT3); `float` preserva capacidad de fórmulas de suma en Sheets |
| Rango de fechas | `execution_date.replace(day=1)` → `execution_date` | FR-002; `IngConnector.fetch_transactions` ya trata el rango como inclusivo (IT2) |
| Categorización de fallos | `IngSyncError` (código `1`) / `SheetsSyncError` (código `2`), planas, sin jerarquía compartida | Decidido en `/speckit-clarify` (FR-007/FR-008); mismo patrón plano que `ing.py`/`writer.py` |
| Logging a nivel de pipeline | `run_sync()` emite su propio `INFO`/`ERROR`, además de lo que ya registran `IngConnector`/`SheetsWriter` | FR-006; útil para IT6 (email) e IT7 (resumen de Actions) sin reconstruir el estado desde logs internos |
| Secreto del documento | `GOOGLE_SHEET_ID` vía `SecretStore`, con fallback inyectable `document_id` | Consume por primera vez un secreto ya reservado desde IT1 |
