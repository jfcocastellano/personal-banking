# Plan de Implementación: Sincronización Multi-Banco con Resiliencia Parcial

**Rama**: `005-multi-bank-resilient-sync` | **Fecha**: 2026-08-13 | **Spec**: [spec.md](spec.md)

**Entrada**: Especificación de la funcionalidad desde `specs/005-multi-bank-resilient-sync/spec.md`

---

## Resumen

Extender el pipeline de sincronización de un solo banco (IT4, `sync.py` + `cli/sync.py`) para
orquestar los cuatro bancos en scope del proyecto (ING, Revolut, MyInvestor, Banco Sabadell), cada
uno vía su propio conector Enable Banking/PSD2. Los tres conectores nuevos (Revolut, MyInvestor,
Sabadell) se construyen extrayendo primero la lógica común ya validada por `IngConnector` (IT2) —
JWT RS256, resolución de sesión PSD2, paginación, parseo y mapeo de errores HTTP — a un módulo base
compartido (`banking.connectors.enable_banking`), del que las cuatro clases de banco heredan fijando
solo su nombre y su clave de sesión. `run_sync()` pasa de ejecutar un único conector a iterar los
cuatro en secuencia fija, aislando el fallo de cada uno (Principio V de la constitución), combinando
los movimientos de los bancos exitosos en una sola escritura a la pestaña `YYYY-MM`, y devolviendo un
resumen estructurado que distingue tres estados posibles: éxito completo, fallo parcial (algún
banco falló pero se escribió con los datos disponibles) y fallo total (ningún banco respondió, no se
escribe nada). La capa CLI traduce esos tres estados a códigos de salida distintos, además del ya
existente para un fallo del propio paso de escritura en Sheets.

Ver `research.md` para el detalle de cada decisión de diseño (extracción del conector base
compartido, nomenclatura de secretos de sesión por banco, orquestación y clasificación de
resultado, códigos de salida, y alcance de pruebas).

---

## Contexto Técnico

**Lenguaje/Versión**: Python 3.12 (mismo runtime que IT1-IT4)

**Dependencias principales**: Ninguna nueva. Reutiliza `httpx`, `PyJWT` y `cryptography` (ya
pineados en `requirements.txt` desde IT2) para el conector base compartido; `gspread` (IT3) para la
escritura combinada; `argparse` (stdlib) para la capa CLI, sin cambios de dependencias.

**Almacenamiento**: Ninguno nuevo. Sin persistencia local; los únicos accesos a disco son la
configuración cifrada ya establecida (IT1) y el fichero `eb-config.json` compartido de credenciales
de aplicación Enable Banking (ya usado por IT2, sin cambios de formato).

**Testing**: `pytest` con `pytest-mock`. La lógica común del conector Enable Banking se testea una
sola vez en `test_enable_banking.py` (JWT, paginación, mapeo de errores HTTP); cada conector de
banco (`test_ing.py`, `test_revolut.py`, `test_myinvestor.py`, `test_sabadell.py`) solo verifica su
`BANK_NAME` y su clave de sesión. El núcleo (`test_sync.py`) se testea inyectando `Mock(spec=...)`
para los cuatro conectores y para `SheetsWriter` — no mockea `httpx`/`gspread` de nuevo, esa
cobertura vive en los tests de conector/writer (FR-012). La capa CLI (`test_cli_sync.py`) se testea
invocando `handle()` directamente, mismo patrón que IT4.

**Plataforma objetivo**: Igual que IT1-IT4 — GitHub Actions `ubuntu-latest` para CI; desarrollo
local multiplataforma.

**Tipo de proyecto**: Extensión del CLI existente del paquete `banking` (`src/banking/cli/`) más
generalización del núcleo de orquestación (`src/banking/sync.py`) y del paquete de conectores
(`src/banking/connectors/`).

**Objetivos de rendimiento**: Una ejecución completa de los cuatro bancos en menos de 2 minutos
(SC-006 de la spec), heredado del SLO "Full sync duration (all 4 banks)" ya definido en la
constitución. Sin techo de tiempo adicional por banco a nivel de orquestador (decidido en
`/speckit-clarify`, ver spec.md § Clarifications) — cada conector se apoya en el comportamiento de
timeout ya existente de su cliente HTTP, igual que `IngConnector`.

**Restricciones**:
- `sync.py` (núcleo) NO DEBE llamar a `print()` — solo `cli/sync.py` puede (Anti-patrón #6)
- El pipeline NO DEBE escribir en Sheets si los cuatro conectores fallan (FR-008)
- El pipeline NO DEBE incluir en la escritura movimientos de un banco fallido en la ejecución
  actual, aunque hubiera tenido éxito en una ejecución anterior el mismo día (FR-006)
- Cuatro estados observables distintos desde la capa CLI: éxito completo, fallo total (ningún
  banco), fallo de Sheets (tras al menos un banco exitoso), fallo parcial (algún banco exitoso,
  algún banco fallido, Sheets escrito) — ver Decisión 5 de `research.md`
- Ningún mensaje (resumen, log, error) puede interpolar credenciales, JWT, `session_id` completo,
  ni JSON de cuenta de servicio, para ninguno de los cuatro bancos (FR-004/FR-014)
- Cero llamadas de red reales en cualquier test (Principio III)
- Los tres conectores nuevos DEBEN seguir el mismo contrato público que `IngConnector` ya validado
  (FR-011) — sin duplicar su lógica de autenticación/paginación/mapeo de errores (Principio VII:
  abstracción justificada por duplicación real ≥3 ocurrencias)

**Escala/Alcance**: Cuatro cuentas/entidades (ING, Revolut, MyInvestor, Sabadell), una pestaña
combinada por ejecución. Sin concurrencia (secuencial, según FR-001). Notificación por email ante
fallos queda fuera de alcance (IT6, ver spec.md § Suposiciones).

---

## Constitution Check

*GATE: Debe pasar antes de la investigación de Fase 0. Se revalida después del diseño de Fase 1.*

- [x] La especificación existe en `specs/005-multi-bank-resilient-sync/spec.md` y ha pasado por
  `/speckit-clarify` (Principio I)
- [x] Ninguna prueba realiza llamadas de red reales — FR-012 exige mockear los cuatro conectores y
  `SheetsWriter`; la cobertura de red real (httpx/gspread) vive únicamente en los tests de conector
  base y de writer, ya mockeados (Principio III)
- [x] No se introduce base de datos ni persistencia local — el único fichero nuevo en disco es
  `eb-config.json`, ya existente desde IT2, sin cambio de formato (Principio VII)
- [x] Los secretos fluyen por el mecanismo cifrado existente — cuatro claves `SESSION_ID` (una por
  banco) vía `SecretStore`, mismo `eb-config.json` compartido, mismas credenciales Sheets ya
  gestionadas por IT2/IT3 (Principio IV)
- [x] Los fallos se manejan de forma independiente por conector — cada banco se ejecuta en su propio
  bloque try/except, un fallo no aborta el resto (FR-002); la escritura en Sheets solo se omite si
  fallan los cuatro (FR-008) (Principio V)
- [x] Todas las funciones públicas llevarán anotaciones de tipo completas — exigido por `mypy`
  strict (Principio VI)
- [x] Ninguna función superará complejidad ciclomática 10 — la orquestación de los 4 bancos delega
  en un helper por banco (`_sync_one_bank`) y en un clasificador de estado global (`_classify`),
  separados de `run_sync()` (Principio VI)
- [x] No se añade ninguna dependencia de terceros nueva (Anti-patrón #10 — no aplica, nada que
  pinear)

**Nota sobre capas de abstracción** (Principio VII, máximo 3 capas por slice vertical): el módulo
base compartido `enable_banking.py` no añade una capa vertical nueva — es reutilización horizontal
dentro de la capa "conector" ya existente (los cuatro conectores de banco siguen siendo la misma
capa que en IT2, ahora con su lógica común extraída). El slice sigue siendo conector → servicio
(`sync.py`) → salida (`sheets/writer.py`).

**Revalidación post-diseño (Fase 1)**: Sin violaciones nuevas. `data-model.md` introduce
`BankOutcome` y `SyncSummary` como estructuras de datos puras (sin persistencia, sin lógica),
y `contracts/connector-contract.md` formaliza un contrato ya cumplido por `IngConnector` — no crea
abstracción adicional más allá de lo ya justificado arriba.

---

## Estructura del Proyecto

### Documentación (esta funcionalidad)

```text
specs/005-multi-bank-resilient-sync/
├── plan.md                                ← este fichero (/speckit-plan)
├── research.md                            ← salida de Fase 0
├── data-model.md                          ← salida de Fase 1
├── quickstart.md                          ← salida de Fase 1 (guía de validación)
├── contracts/
│   ├── connector-contract.md              ← contrato común a los 4 conectores de banco
│   ├── cli-sync-interface.md              ← contrato de la interfaz CLI (`banking sync`)
│   └── sync-pipeline-interface.md         ← contrato de la interfaz Python interna (`run_sync`)
└── checklists/
    └── requirements.md
```

### Código fuente (raíz del repositorio)

```text
src/
└── banking/
    ├── __main__.py                        # SIN CAMBIOS: ya registra el subcomando "sync"
    ├── sync.py                            # MODIFICADO: run_sync() orquesta 4 bancos, SyncSummary,
    │                                       #   BankOutcome, AllBanksFailedError, SheetsSyncError
    ├── cli/
    │   ├── secrets.py
    │   └── sync.py                        # MODIFICADO: resumen multi-banco, 4 códigos de salida
    ├── config/
    │   └── secret_store.py
    ├── connectors/
    │   ├── enable_banking.py              # NUEVO: lógica PSD2 compartida (JWT, sesión, paginación,
    │   │                                   #   parseo, mapeo de errores HTTP) — clase base
    │   ├── ing.py                         # MODIFICADO: hereda de EnableBankingConnector
    │   ├── revolut.py                     # NUEVO: hereda de EnableBankingConnector
    │   ├── myinvestor.py                  # NUEVO: hereda de EnableBankingConnector
    │   └── sabadell.py                    # NUEVO: hereda de EnableBankingConnector
    └── sheets/
        └── writer.py                      # SIN CAMBIOS

tests/
└── unit/
    ├── test_main.py                       # SIN CAMBIOS (subcomando ya cubierto)
    ├── test_sync.py                       # MODIFICADO: escenarios todos-ok / un-falla / todos-fallan
    ├── test_cli_sync.py                   # MODIFICADO: resumen multi-banco, 4 códigos de salida
    ├── connectors/
    │   ├── test_enable_banking.py         # NUEVO: JWT, paginación, mapeo de errores (lógica común)
    │   ├── test_ing.py                    # MODIFICADO: reducido a BANK_NAME/clave de sesión
    │   ├── test_revolut.py                # NUEVO: idem
    │   ├── test_myinvestor.py             # NUEVO: idem
    │   └── test_sabadell.py               # NUEVO: idem
    ├── sheets/
    │   └── test_writer.py                 # SIN CAMBIOS
    └── config/
        └── test_secret_store.py           # SIN CAMBIOS
```

**Decisión de estructura**: se mantiene el paquete plano `src/banking/` ya establecido (IT1-IT4);
`connectors/enable_banking.py` vive junto a los conectores de banco (mismo paquete, no un paquete
nuevo) porque es un detalle de implementación interno de esa capa, no una capa adicional — ver la
nota de Constitution Check arriba.

---

## Complexity Tracking

*Sin violaciones que justificar. La única duda evaluada (capas de abstracción del conector base
compartido) se resuelve como reutilización horizontal, no como capa vertical nueva — ver la nota en
Constitution Check.*
