# Plan de Implementación: Escritor Genérico de Google Sheets

**Rama**: `003-google-sheets-writer` | **Fecha**: 2026-08-09 | **Spec**: [spec.md](spec.md)

**Entrada**: Especificación de la funcionalidad desde `specs/003-google-sheets-writer/spec.md`

---

## Resumen

Implementar un componente Python (`banking.sheets.writer.SheetsWriter`) que
se autentica ante la API de Google Sheets mediante una cuenta de servicio
de Google Cloud (JSON leído del `SecretStore` cifrado existente, clave
`GOOGLE_SHEETS_CREDENTIALS` ya reservada por IT1) usando `gspread`. Dado un
ID de documento, un nombre de pestaña, una fila de cabeceras y una lista de
filas de datos genéricas (primitivos JSON-serializables), crea la pestaña
si no existe o borra por completo su contenido si ya existe, y escribe los
datos desde `A1` en una sola operación. No tiene conocimiento del dominio
bancario: el formato de columnas lo decide quien lo invoque (IT4+). Emite
un log estructurado por invocación (pestaña, filas escritas, duración en
éxito; categoría y motivo en fallo) usando cuatro excepciones distintas por
categoría de causa, replicando el patrón ya validado en el conector ING
(IT2). Ningún test realiza llamadas de red reales.

Ver `research.md` para las decisiones de diseño clave (librería de acceso a
Sheets, secuencia exacta de llamadas verificada contra la documentación de
`gspread`, jerarquía de excepciones, forma de la interfaz pública).

---

## Contexto Técnico

**Lenguaje/Versión**: Python 3.12 (mismo runtime que IT1/IT2)

**Dependencias principales**:
- `gspread` — cliente de Google Sheets, autenticación por cuenta de
  servicio y operaciones de pestaña/celda (producción)
- `google-auth` — ya se obtiene como dependencia transitiva de `gspread`;
  no se importa directamente en este componente (ver `research.md`,
  Decisión 1)
- `cryptography` — ya presente desde IT1; sin uso nuevo en esta iteración
- `pytest` + `pytest-mock` — tests (dev, ya presentes)
- `unittest.mock.Mock(spec=gspread.Client)` — mockeo de toda interacción
  con Google Sheets en tests, sin dependencia adicional (`gspread` no
  ofrece un transporte de mock nativo como `httpx.MockTransport`)

**Almacenamiento**: Ninguno. Sin persistencia local de los datos tabulares
(FR-009); Google Sheets es el único destino de escritura. La única lectura
de disco es la configuración cifrada ya establecida en IT1 (`.env` vía
`SecretStore`).

**Testing**: `pytest` con `pytest-mock`; toda interacción con `gspread`
mockeada mediante un `Client` inyectado (FR-011); ninguna prueba realiza
una llamada de red real; el pipeline de CI existente (`ci.yml`, IT1) ya
falla ante cualquier intento de red no mockeado detectado por revisión de
test.

**Plataforma objetivo**: Igual que IT1/IT2 — GitHub Actions `ubuntu-latest`
para CI; desarrollo local multiplataforma (Python 3.12+).

**Tipo de proyecto**: Módulo dentro del paquete existente `banking`
(`src/banking/sheets/`). Esta iteración no añade una nueva interfaz CLI; el
componente se invoca de forma programática (Python), como corresponde a un
componente reutilizable que un futuro pipeline (IT4) llamará junto a los
conectores bancarios.

**Objetivos de rendimiento**: Una invocación de escritura se completa en
menos de 30 segundos (SC-006), heredado directamente del SLO ya definido en
la constitución del proyecto para "escritura en Google Sheets por pestaña
mensual" — decidido explícitamente en `/speckit-clarify`, no es un umbral
nuevo introducido por este plan.

**Restricciones**:
- Sin formato visual de celdas ni reintento/backoff ante cuota en esta
  iteración (Suposiciones del spec)
- JSON de la cuenta de servicio y cualquier token derivado NUNCA deben
  aparecer en ningún log (FR-012)
- Cuatro categorías de excepción distintas exigidas por FR-008 (config,
  acceso, cuota, API genérica) — no una excepción única
- Cero llamadas de red reales en cualquier test (Principio III, no
  negociable)

**Escala/Alcance**: Un único documento y una única pestaña por invocación.
Sin concurrencia. Volumen esperado: uso personal (decenas/cientos de filas
por pestaña mensual), sin límite explícito de filas/columnas impuesto por
el componente. Orquestar múltiples bancos, documentos o pestañas es
responsabilidad de un proceso llamador fuera de esta funcionalidad.

---

## Constitution Check

*GATE: Debe pasar antes de la investigación de Fase 0. Se revalida después del diseño de Fase 1.*

- [x] La especificación existe en `specs/003-google-sheets-writer/spec.md` y ha pasado por `/speckit-clarify` (Principio I)
- [x] Ninguna prueba realiza llamadas de red reales — FR-011 exige mockear cada interacción con `gspread`; el punto de inyección es el `Client` completo (Principio III)
- [x] No se introduce base de datos ni persistencia local — FR-009 prohíbe explícitamente persistir los datos tabulares; la única E/S de disco es la configuración cifrada ya existente de IT1 (Principio VII)
- [x] Los secretos fluyen por el mecanismo cifrado existente — el JSON de la cuenta de servicio se lee vía `SecretStore.get("GOOGLE_SHEETS_CREDENTIALS")`, clave ya reservada por IT1 (Principio IV)
- [x] Los fallos se manejan de forma independiente — este componente lanza excepciones específicas por categoría (FR-008) y deja la política de "no abortar el pipeline completo" a un futuro orquestador (IT4+, fuera de alcance aquí) (Principio V)
- [x] Todas las funciones públicas llevarán anotaciones de tipo completas — exigido por `mypy` strict en la CI existente (Principio VI)
- [x] Ninguna función superará complejidad ciclomática 10 — la secuencia crear/sobrescribir se divide en pasos pequeños (ver `research.md`, Decisión 4); no se anticipa una función monolítica (Principio VI)
- [x] Nueva dependencia de terceros (`gspread`) se añadirá con pin exacto a `requirements.txt`, siguiendo la metodología de IT1/IT2 (`pip install` + `pip freeze`) (Anti-patrón #10)

**Nota sobre `docs/context.md` (Principio I)**: `docs/context.md` lista
`gspread` y `google-auth` como librerías principales separadas, anticipando
un patrón de autenticación manual con `google-auth.Credentials`. La
Decisión 1 de `research.md` opta por `gspread.service_account_from_dict()`,
que cubre la autenticación sin importar `google-auth` directamente (llega
transitivamente). Esta es una simplificación (una dependencia directa en
vez de dos) justificada por YAGNI, no un cambio de comportamiento; se
recomienda una actualización menor de `docs/context.md` en esta misma
iteración para reflejarlo.

**Revalidación post-diseño (Fase 1)**: Sin violaciones nuevas. El diseño en
`data-model.md` y `contracts/` no introduce persistencia, no añade una capa
"servicio" adicional (un único módulo `SheetsWriter`, sin cliente genérico
"Google" separado del escritor — YAGNI, Principio VII), y aísla el único
punto de incertidumbre real (si un 403 de permisos se traduce siempre en
`SpreadsheetNotFound` o a veces en `APIError`) detrás de un manejo que
captura ambas posibilidades, documentado en `research.md` Decisión 4 y
`contracts/google-sheets-api.md`.

---

## Estructura del Proyecto

### Documentación (esta funcionalidad)

```text
specs/003-google-sheets-writer/
├── plan.md                          ← este fichero (/speckit-plan)
├── research.md                      ← salida de Fase 0
├── data-model.md                    ← salida de Fase 1
├── quickstart.md                    ← salida de Fase 1 (guía de validación)
├── contracts/
│   ├── google-sheets-api.md         ← contrato de la API externa consumida (vía gspread)
│   └── sheets-writer-interface.md   ← contrato de la interfaz Python pública
└── checklists/
    └── requirements.md
```

### Código fuente (raíz del repositorio)

```text
src/
└── banking/
    ├── __init__.py
    ├── __main__.py
    ├── cli/
    │   ├── __init__.py
    │   └── secrets.py
    ├── config/
    │   ├── __init__.py
    │   └── secret_store.py
    ├── connectors/
    │   ├── __init__.py
    │   └── ing.py
    └── sheets/                       # NUEVO en esta funcionalidad
        ├── __init__.py
        └── writer.py                 # SheetsWriter: auth cuenta de servicio,
                                       # crear/sobrescribir pestaña, escritura,
                                       # excepciones propias, logging estructurado

tests/
└── unit/
    ├── conftest.py
    ├── test_main.py
    ├── config/
    │   ├── __init__.py
    │   └── test_secret_store.py
    ├── connectors/
    │   ├── __init__.py
    │   └── test_ing.py
    └── sheets/                       # NUEVO en esta funcionalidad
        ├── __init__.py
        └── test_writer.py            # Toda interacción con gspread mockeada

requirements.txt                      # + gspread (pin exacto, esta funcionalidad)
```

**Decisión de estructura**: Un único módulo `src/banking/sheets/writer.py`
concentra toda la lógica (autenticación, resolución de pestaña,
crear/sobrescribir, escritura, excepciones). No se introduce una capa
"servicio" ni un cliente "Google" genérico separado del escritor: solo
existe un destino de salida (Google Sheets) en el proyecto, y el Principio
VII (YAGNI) exige evidencia de duplicación real antes de generalizar. Los
tests reflejan la misma estructura 1:1 bajo `tests/unit/sheets/`, en
paralelo a `tests/unit/connectors/` (IT2).

---

## Complexity Tracking

> Solo se completa si el Constitution Check tiene violaciones que justificar.

Ninguna violación. La única capa nueva es el propio módulo `sheets/`, ya
anticipado por la estructura de directorios de `docs/context.md`
(§ Librerías principales) y consistente con el patrón de `connectors/`
introducido en IT2. No se añade ninguna capa "servicio" u "output"
adicional en esta iteración.

---

## Decisiones de Diseño (resumen de Fase 0)

Racional completo y alternativas en `research.md`.

| Decisión | Elección | Razón clave |
|----------|----------|--------------|
| Librería de acceso a Sheets | `gspread`, vía `service_account_from_dict()` | Ya documentada en `docs/context.md`; acepta el JSON de la cuenta de servicio como `dict` en memoria, sin escribirlo a disco |
| Dependencia `google-auth` | No se añade como dependencia directa | Llega transitivamente vía `gspread`; simplificación justificada por YAGNI frente al plan original de `docs/context.md` |
| Secreto de cuenta de servicio | `SecretStore.get("GOOGLE_SHEETS_CREDENTIALS")` | Clave ya reservada por IT1 en `contracts/secret-store-format.md`; evita una segunda convención de nombres |
| Documento/pestaña como parámetros | `document_id` y `tab_name` son argumentos de `write()`, no secretos | FR-002; el componente es genérico, la orquestación (qué documento/pestaña) es responsabilidad de IT4+ |
| Secuencia crear/sobrescribir | `open_by_key` → `worksheet` (o `add_worksheet` si `WorksheetNotFound`) → `clear()` si ya existía → `update(values=...)` sin `range_name` | Verificado contra `docs.gspread.org` (2026-08-09); un único `update()` evita múltiples peticiones y escribe desde `A1` por defecto (FR-005) |
| Tipos de valor aceptados | Primitivos JSON-serializables (`str`, `int`, `float`, `bool`, `None`) | Decidido en `/speckit-clarify`; conversión de tipos más ricos (`Decimal`, fechas) es responsabilidad del llamador (FR-010) |
| Jerarquía de excepciones | 4 excepciones planas por categoría: `SheetsConfigError`, `SheetsAccessError`, `SheetsQuotaExceededError`, `SheetsAPIError` | Decidido en `/speckit-clarify`; mismo patrón que `ing.py` (IT2), permite reaccionar por tipo sin parsear mensajes |
| Forma de la interfaz pública | Clase `SheetsWriter` con `gspread.Client` inyectable | Permite inyectar un doble de prueba (`Mock(spec=gspread.Client)`) en tests (FR-011); mismo patrón que `IngConnector` (IT2) y `SecretStore` (IT1) |
| Umbral de rendimiento | < 30 s por invocación (SC-006) | Decidido en `/speckit-clarify`; heredado del SLO ya existente en la constitución, no un valor nuevo |
| Redacción de logs | Ningún log interpola el JSON de la cuenta de servicio ni tokens derivados | FR-012, mismo mecanismo que FR-015 de IT2 |
| Nueva dependencia | `gspread` pineada exacta en `requirements.txt` | Mismo método que IT1/IT2 (`pip install` + `pip freeze`); durante la fase de implementación, no en este plan |
