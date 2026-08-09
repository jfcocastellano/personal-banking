# Plan de Implementación: Conector de Movimientos ING España (Enable Banking)

**Rama**: `002-ing-transactions-connector` | **Fecha**: 2026-08-03 | **Spec**: [spec.md](spec.md)

**Entrada**: Especificación de la funcionalidad desde `specs/002-ing-transactions-connector/spec.md`

---

## Resumen

Implementar un conector Python (`banking.connectors.ing`) que se autentica ante
la API de Enable Banking mediante un JWT firmado con RS256 (clave RSA privada
leída de `~/.config/banca-personal/eb-config.json`) y el `session_id` PSD2
almacenado en el SecretStore cifrado existente (IT1). Dado un rango de fechas,
recupera todas las páginas vía `continuation_key`, filtra solo transacciones
`BOOK`, normaliza importe/divisa y deduplica por una clave compuesta
(fecha de liquidación + importe + descripción). No persiste nada: devuelve una
lista en memoria. Detecta de forma explícita las dos condiciones de fallo
documentadas del protocolo PSD2 — sesión inutilizable (HTTP 403 / estado
`expired`) y límite de peticiones excedido (HTTP 429) — lanzando errores
distintos y descriptivos para cada una. Ningún test realiza llamadas HTTP
reales.

Ver `research.md` para las decisiones de diseño clave (librería HTTP, librería
JWT, mecánica de paginación/detección de expiración/límite de tasa, formato
de logging).

---

## Contexto Técnico

**Lenguaje/Versión**: Python 3.12 (mismo runtime que IT1)

**Dependencias principales**:
- `httpx` — cliente HTTP síncrono para la API de Enable Banking (producción)
- `PyJWT` — generación de JWT firmados con RS256 usando el backend de `cryptography` (producción)
- `cryptography` — ya presente desde IT1; se reutiliza para cargar la clave privada RSA (`load_pem_private_key`)
- `pytest` + `pytest-mock` — tests (dev, ya presentes)
- `httpx.MockTransport` (o equivalente basado en `unittest.mock`) — mockeo de todas las llamadas HTTP en tests, sin dependencia adicional

**Almacenamiento**: Ninguno. Sin persistencia de transacciones (FR-009); la
única lectura de disco es la configuración ya establecida en IT1
(`eb-config.json`, `.env` cifrado vía SecretStore).

**Testing**: `pytest` con `pytest-mock`; toda interacción HTTP mockeada
(FR-014); ninguna prueba realiza una llamada de red real; el pipeline de CI
existente (`ci.yml`, IT1) ya falla ante cualquier intento de red no mockeado
detectado por revisión de test.

**Plataforma objetivo**: Igual que IT1 — GitHub Actions `ubuntu-latest` para CI;
desarrollo local multiplataforma (Python 3.12+).

**Tipo de proyecto**: Módulo conector dentro del paquete existente `banking`
(`src/banking/connectors/`). Esta iteración no añade una nueva interfaz CLI;
el conector se invoca de forma programática (Python), como corresponde a un
componente que un futuro orquestador de sincronización (IT3+) llamará junto a
los conectores de Revolut y MyInvestor.

**Objetivos de rendimiento**: Sin SLA propio más allá del presupuesto global de
sincronización completa (constitución: <2 min end-to-end con las 3 entidades).
El límite real que domina el rendimiento es el límite duro de la API: 4
peticiones/cuenta/día — el conector debe respetarlo, no optimizarlo.

**Restricciones**:
- Sin flujo de refresh token (FR-003); el `session_id` es la única credencial
- Clave privada RSA, JWT firmado y `session_id` completo NUNCA deben aparecer
  en ningún log (FR-015)
- Límite superior de páginas por invocación como salvaguarda ante paginación
  infinita (Casos Límite del spec)
- Cero llamadas de red reales en cualquier test (Principio III, no negociable)

**Escala/Alcance**: Una única cuenta (ING España), una invocación cubre un
único rango de fechas contiguo. Sin concurrencia. Orquestar múltiples bancos o
rangos es responsabilidad de un proceso llamador fuera de esta funcionalidad.

---

## Constitution Check

*GATE: Debe pasar antes de la investigación de Fase 0. Se revalida después del diseño de Fase 1.*

- [x] La especificación existe en `specs/002-ing-transactions-connector/spec.md` y ha pasado por `/speckit-clarify` (Principio I)
- [x] Ninguna prueba realiza llamadas HTTP reales — FR-014 exige mockear toda interacción con Enable Banking (Principio III)
- [x] No se introduce base de datos ni persistencia local — FR-009 prohíbe explícitamente persistir transacciones; la única E/S de disco es la configuración ya existente de IT1 (Principio VII)
- [x] Los secretos fluyen por el mecanismo cifrado existente — el `session_id` se lee vía SecretStore (`.env` cifrado, IT1); ver nota sobre la clave RSA privada más abajo (Principio IV)
- [x] Los fallos de conector se manejan de forma independiente — este conector lanza excepciones específicas y deja la política de "no abortar la sincronización completa" a un futuro orquestador (fuera de alcance aquí, ver Suposiciones del spec) (Principio V)
- [x] Todas las funciones públicas llevarán anotaciones de tipo completas — exigido por `mypy` strict en la CI existente (Principio VI)
- [x] Ninguna función superará complejidad ciclomática 10 — ver desglose de funciones en Estructura del Proyecto; el mapeo de errores HTTP se divide en funciones pequeñas por código de estado (Principio VI)
- [x] Nueva dependencia de terceros (`httpx`, `PyJWT`) se añadirá con pin exacto a `requirements.txt`, siguiendo la metodología de IT1 (`pip install` + `pip freeze`) (Anti-patrón #10)

**Nota sobre la clave privada RSA (Principio IV)**: La clave privada vive en
`~/.config/banca-personal/private.pem`, fuera del repositorio, tal como IT1 ya
estableció en su `quickstart.md` (paso 9) y documentó en su `data-model.md`
(Entidad 4). Este plan no cambia ese modelo: el conector solo lee y usa la
clave, no decide dónde ni cómo se protege en disco. En CI, ningún test toca
una clave real — todas las llamadas HTTP están mockeadas (FR-014) y cualquier
clave usada en fixtures de test es generada efímeramente para el test, nunca
una credencial real. El uso de esta clave en una ejecución programada real
(GitHub Actions, producción) es responsabilidad de una iteración futura de
orquestación, no de este conector.

**Revalidación post-diseño (Fase 1)**: Sin violaciones nuevas. El diseño en
`data-model.md` y `contracts/` no introduce persistencia, no añade una capa
de abstracción adicional (conector único, sin capa "servicio" intermedia
todavía — YAGNI, Principio VII), y aísla los dos puntos de incertidumbre del
protocolo real (endpoints exactos, campo de estado de expiración) detrás de
constantes/funciones pequeñas y bien nombradas en `ing.py`, documentado en
`research.md`.

---

## Estructura del Proyecto

### Documentación (esta funcionalidad)

```text
specs/002-ing-transactions-connector/
├── plan.md                          ← este fichero (/speckit-plan)
├── research.md                      ← salida de Fase 0
├── data-model.md                    ← salida de Fase 1
├── quickstart.md                    ← salida de Fase 1 (guía de validación)
├── contracts/
│   ├── enable-banking-api.md        ← contrato de la API externa consumida
│   └── ing-connector-interface.md   ← contrato de la interfaz Python pública
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
    └── connectors/                   # NUEVO en esta funcionalidad
        ├── __init__.py
        └── ing.py                    # IngConnector: auth JWT, sesión, paginación,
                                       # filtrado, normalización, deduplicación,
                                       # excepciones propias, logging estructurado

tests/
└── unit/
    ├── conftest.py
    ├── test_main.py
    ├── config/
    │   ├── __init__.py
    │   └── test_secret_store.py
    └── connectors/                   # NUEVO en esta funcionalidad
        ├── __init__.py
        └── test_ing.py               # Toda la API de Enable Banking mockeada

requirements.txt                      # + httpx, PyJWT (pin exacto, esta funcionalidad)
```

**Decisión de estructura**: Un único módulo `src/banking/connectors/ing.py`
concentra toda la lógica (autenticación, sesión, paginación, filtrado,
normalización, deduplicación, excepciones). No se introduce una capa
"servicio" ni un cliente genérico "Enable Banking" separado del conector de
ING: solo existe una entidad bancaria en esta iteración, y el Principio VII
(YAGNI) exige evidencia de duplicación real (3+ ocurrencias) antes de
generalizar. Cuando IT3+ añada Revolut/MyInvestor sobre Enable Banking, ese
será el momento de extraer la parte común (JWT + paginación + detección de
403/429) a un módulo compartido — no antes. Los tests reflejan la misma
estructura 1:1 bajo `tests/unit/connectors/`.

---

## Complexity Tracking

> Solo se completa si el Constitution Check tiene violaciones que justificar.

Ninguna violación. La única capa nueva es el propio módulo conector, ya
presente en el árbol de directorios previsto por IT1 (`src/banking/`). No se
añade una capa "servicio" ni "output" adicional en esta iteración.

---

## Decisiones de Diseño (resumen de Fase 0)

Racional completo y alternativas en `research.md`.

| Decisión | Elección | Razón clave |
|----------|----------|-------------|
| Cliente HTTP | `httpx.Client` (síncrono) | Ya documentado como librería principal en `docs/context.md`; soporta `MockTransport` nativo para tests sin dependencia extra |
| Librería JWT | `PyJWT` con backend `cryptography` (RS256) | Verificado contra API real 2026-08-09 (la suposición inicial PS256 daba 401); `PyJWT` soporta RS256 directamente con una clave `cryptography` ya cargada |
| Forma de la interfaz pública | Clase `IngConnector` con cliente HTTP inyectable | Permite inyectar un `httpx.Client(transport=MockTransport(...))` en tests (FR-014), mismo patrón de clase que `SecretStore` (IT1) |
| Detección de sesión inutilizable | HTTP 403 **o** campo de estado con valor `expired` en la respuesta, verificado en un único punto antes de cualquier retorno de datos | FR-004; aísla la incertidumbre sobre el nombre exacto del campo en una sola función, ajustable sin tocar el resto del conector |
| Detección de límite de tasa | HTTP 429 en cualquier petición (inicial o de paginación) | FR-008; distinto del error de re-autorización |
| Clave de deduplicación | `(fecha_liquidación, importe, descripción/contraparte)` | Decidido en `/speckit-clarify`; no se asume un ID de transacción propio de la API |
| Paginación | Bucle sobre `continuation_key` con límite máximo de páginas configurable (salvaguarda) | Evita bucle infinito ante una API que nunca deja de devolver `continuation_key` (Casos Límite) |
| Redacción de logs | Ningún log interpola clave privada, JWT o `session_id` completo; solo metadatos (banco, rango, conteo, motivo) | FR-015, decidido en `/speckit-clarify` |
| Nuevas dependencias | `httpx`, `PyJWT` pineadas exactas en `requirements.txt` | Mismo método que IT1 (`pip install` + `pip freeze`); ambas ya previstas en `docs/context.md` |
