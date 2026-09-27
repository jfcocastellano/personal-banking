# Fase 0: Investigación — Sincronización Multi-Banco con Resiliencia Parcial

## Decisión 1: Extraer un conector base compartido para Enable Banking

**Decisión**: Crear `banking.connectors.enable_banking` con toda la lógica común ya validada por
`IngConnector` (IT2) — carga de credenciales (`eb-config.json`), construcción del JWT RS256,
resolución de la cuenta vinculada a la sesión, paginación con `continuation_key`, parseo de
transacciones (`_parse_transaction`), y mapeo de estados HTTP a excepciones
(`ReauthorizationRequiredError`, `RateLimitExceededError`, `EnableBankingAPIError`). Cada banco
expone una clase ligera que fija dos constantes de clase (`BANK_NAME`, `_SESSION_ID_KEY`) y hereda
el resto sin sobrescribir nada: `IngConnector`, `RevolutConnector`, `MyInvestorConnector`,
`SabadellConnector`.

**Rationale**: Construir los tres conectores nuevos copiando `ing.py` (≈330 líneas) produciría
exactamente el patrón de duplicación que el Principio VII de la constitución permite — y en la
práctica exige — resolver con una abstracción: "Add abstractions only when they eliminate real,
present duplication (3+ occurrences)". Aquí hay 3 nuevas ocurrencias reales, no hipotéticas. Extraer
la lógica común también asegura que una futura corrección (p. ej. un cambio en el límite de páginas,
o en cómo se detecta una sesión expirada) se aplique una sola vez a los cuatro bancos, en vez de
tener que replicarse en cuatro ficheros.

**Alternativas consideradas**:
- *Copiar y pegar el módulo 3 veces*: rechazada — duplicación masiva, alto riesgo de que un fix de
  bug no se propague a las cuatro copias, viola directamente Principio VII.
- *Una única clase parametrizada por instancia* (`EnableBankingConnector(bank_name=..., session_key=...)`
  sin subclases): también elimina la duplicación, pero se descarta a favor de subclases finas
  porque (a) preserva la interfaz pública ya usada por `sync.py` y los tests de IT4
  (`IngConnector.BANK_NAME` como atributo de clase, no de instancia), y (b) permite seguir mockeando
  con `Mock(spec=RevolutConnector)` por banco en `test_sync.py`, igual que el patrón ya validado en
  IT4 para `IngConnector`.

## Decisión 2: `IngConnector` pasa a heredar del conector base sin cambiar su interfaz pública

**Decisión**: `IngConnector` se convierte en una subclase de `EnableBankingConnector` que solo fija
`BANK_NAME = "ING España"` y `_SESSION_ID_KEY = "ENABLE_BANKING_SESSION_ID_ING"`. Su interfaz
pública (`BANK_NAME`, `fetch_transactions(start_date, end_date) -> list[Transaction]`) no cambia.

**Rationale**: Ningún consumidor externo del conector (CLI, `sync.py`, tests que mockean
`IngConnector`) necesita cambios de firma — el refactor es transparente. Los tests de bajo nivel que
hoy viven en `test_ing.py` (construcción del JWT, paginación, mapeo de errores HTTP) se trasladan y
generalizan a `test_enable_banking.py`, ejecutándose una sola vez contra la clase base (usando una
subclase de prueba mínima o directamente `IngConnector` como banco de referencia). `test_ing.py`
queda reducido a verificar que las dos constantes de clase son las correctas.

**Alternativas consideradas**: mantener `IngConnector` como está (sin heredar) e implementar
Revolut/MyInvestor/Sabadell por composición (delegando en una función compartida en vez de herencia)
— descartada por added indirection sin beneficio claro sobre la herencia simple, dado que las cuatro
clases no necesitan comportamiento adicional propio en esta iteración (YAGNI).

## Decisión 3: Nomenclatura de secretos de sesión por banco; credenciales de aplicación compartidas

**Decisión**: Cada banco usa su propia clave de sesión PSD2 en el `SecretStore`:
`ENABLE_BANKING_SESSION_ID_ING`, `ENABLE_BANKING_SESSION_ID_REVOLUT`,
`ENABLE_BANKING_SESSION_ID_MYINVESTOR`, `ENABLE_BANKING_SESSION_ID_SABADELL`. Las credenciales de
aplicación (`app_id` + clave privada RSA, en `eb-config.json`) se mantienen compartidas entre los
cuatro bancos — identifican la aplicación TPP registrada ante Enable Banking, no un banco
individual, y no cambian de formato ni de ubicación respecto a IT2.

**Rationale**: En el modelo PSD2 de Enable Banking, el `session_id` es el resultado de un
consentimiento de usuario específico de una cuenta bancaria concreta (un consentimiento por banco),
mientras que `app_id`/clave privada autentican la aplicación TPP en su conjunto ante la plataforma
Enable Banking — un único registro de aplicación cubre las llamadas a cualquier ASPSP soportado.
Esto ya es observable en el propio `IngConnector` de IT2: `_load_signing_credential` no depende del
banco, solo `_SESSION_ID_KEY` (implícitamente `"ENABLE_BANKING_SESSION_ID"`) sí.

**Alternativas consideradas**: un `eb-config.json` por banco — rechazada, no hay necesidad real (las
credenciales de aplicación son las mismas), añadiría complejidad de configuración sin ningún
beneficio (Principio VII).

**Nota de migración**: la clave de sesión de ING ya existente en producción/local,
`ENABLE_BANKING_SESSION_ID` (sin sufijo), se renombra a `ENABLE_BANKING_SESSION_ID_ING`. Se
documenta como paso manual en `quickstart.md` (reescribir esa entrada en el `.env` cifrado); no
requiere migración de código porque `SecretStore` no versiona claves.

## Decisión 4: Orquestación multi-banco y clasificación del resultado global

**Decisión**: `run_sync()` itera una lista fija de 4 conectores en el orden ya establecido por la
constitución (ING, Revolut, MyInvestor, Sabadell). Cada iteración se ejecuta en su propio bloque
try/except y produce un `BankOutcome` (éxito con el recuento de movimientos, o fallo con una
categoría de motivo). Tras las 4 iteraciones:

- Si los 4 fallaron → se lanza `AllBanksFailedError` (subclase de `Exception`, sin llamar al
  `SheetsWriter`).
- Si al menos 1 tuvo éxito → se combinan los movimientos de los bancos exitosos, se escriben en la
  pestaña `YYYY-MM`, y se devuelve un `SyncSummary` cuyo `overall_status` es `FULL_SUCCESS` (los 4
  exitosos) o `PARTIAL_FAILURE` (al menos 1 exitoso y al menos 1 fallido). Un fallo del propio paso
  de escritura en este punto lanza `SheetsSyncError` (ya existente desde IT4, sin cambios de
  semántica).

**Rationale**: Modela FR-001 a FR-010 sin estado mutable compartido innecesario; cada llamada a
conector queda aislada, igual que el patrón try/except que IT4 ya usaba para ING (ahora repetido 4
veces dentro de un bucle, no 4 bloques distintos copiados).

**Alternativas consideradas**: paralelizar los 4 conectores (asyncio o hilos) — rechazada, la
especificación exige secuencia explícita (FR-001) y el límite PSD2 de 4 peticiones/cuenta/día no se
beneficia de paralelismo; introduciría complejidad de concurrencia no solicitada (Principio VII).

## Decisión 5: Códigos de salida CLI para los cuatro estados observables

**Decisión**: `cli/sync.py` devuelve:

| Código | Estado |
|---|---|
| `0` | Éxito completo — los 4 bancos sincronizados |
| `1` | Fallo total — los 4 bancos fallaron, nada escrito en Sheets |
| `2` | Fallo de Sheets — al menos 1 banco tuvo éxito, pero la escritura combinada falló |
| `3` | Fallo parcial — al menos 1 banco falló, al menos 1 tuvo éxito, y los datos disponibles se escribieron correctamente |

**Rationale**: FR-010 exige que un proceso externo (el futuro notificador de IT6) distinga los
estados de una ejecución sin interpretar el texto del resumen. Los códigos `0`/`1`/`2` conservan el
significado ya establecido en IT4 (reinterpretados como "fallo total de obtención de datos" y "fallo
de Sheets" respectivamente, ahora que hay más de un banco); `3` es un estado nuevo que distingue
"éxito degradado, con datos" de "fallo total, sin datos" — una distinción explícitamente requerida
por FR-010 y necesaria para que un scheduler futuro dosifique la urgencia de una alerta.

**Alternativas consideradas**: un único código no-cero para cualquier fallo (parcial o total) —
rechazada, pierde exactamente la distinción que FR-010 exige.

## Decisión 6: Alcance de pruebas automatizadas

**Decisión**: `test_enable_banking.py` cubre una sola vez la lógica común (JWT, resolución de
sesión, paginación, mapeo de errores HTTP) contra la clase base. Cada `test_<banco>.py` se reduce a
verificar `BANK_NAME` y la clave de sesión de ese banco. `test_sync.py` cubre los tres escenarios
obligatorios de la spec (FR-013) inyectando `Mock(spec=<Connector>)` para los 4 conectores y
`Mock(spec=SheetsWriter)`, sin tocar `httpx`/`gspread` (esa cobertura vive en
`test_enable_banking.py`/`test_writer.py`, ya existente). `test_cli_sync.py` cubre los 4 códigos de
salida invocando `handle()` con `run_sync` mockeado.

**Rationale**: Evita cuadruplicar ~15 tests de bajo nivel de JWT/paginación/errores HTTP; cumple
Principio III (mocks, cero red real en cualquier test) sin perder cobertura — cada capa se testea
exactamente en el nivel donde vive su lógica.

**Alternativas consideradas**: repetir la suite completa de `test_ing.py` para cada banco nuevo —
rechazada, duplicación de test sin valor incremental una vez que la lógica común está probada en un
solo sitio.
