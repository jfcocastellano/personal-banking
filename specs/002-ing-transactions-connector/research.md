# Investigación: Conector de Movimientos ING España (Enable Banking)

**Salida de Fase 0 para**: `specs/002-ing-transactions-connector/plan.md`
**Fecha**: 2026-08-03

> **Nota sobre fuentes**: `CLAUDE.md` referencia una skill `/enable-banking-api`
> para conocimiento de dominio de Enable Banking (autenticación PSD2, ciclo de
> vida de sesión, límites de tasa, estructura de transacciones, códigos de
> error). Esa skill no está instalada en este repositorio en el momento de
> escribir este documento. Las decisiones de protocolo de abajo se basan en
> `docs/context.md` (fuente de verdad del proyecto) y en las convenciones
> públicas conocidas de agregadores PSD2/Berlin Group. Los puntos marcados
> **[verificar contra documentación real]** deben confirmarse contra la
> documentación oficial de Enable Banking antes de la primera ejecución no
> mockeada (local, con sesión real), y están aislados en funciones/constantes
> puntuales de `ing.py` para que un ajuste no afecte el resto del conector.

---

## Decisión 1: Cliente HTTP

**Decisión**: `httpx.Client` (síncrono).

**Racional**: `docs/context.md` ya documenta `httpx` como la librería
principal para llamadas a la API de Enable Banking. `httpx` ofrece
`httpx.MockTransport`, que permite construir un cliente que nunca abre un
socket real y responde con fixtures deterministas — exactamente lo que exige
FR-014 (todas las llamadas HTTP mockeadas en tests) sin añadir una librería
de mocking adicional.

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| `requests` | No tiene transporte de mock nativo; requeriría `responses` o `requests-mock` como dependencia extra |
| `aiohttp` / cliente async | No hay ningún requisito de concurrencia en el spec; añadiría complejidad de runtime async sin beneficio (Principio VII, YAGNI) |
| `urllib` (stdlib) | Manejo manual de JSON, timeouts y reintentos; `httpx` ya está previsto en `docs/context.md` |

---

## Decisión 2: Generación del JWT (RS256)

**Decisión**: `PyJWT` (`jwt.encode(claims, private_key, algorithm="RS256",
headers={"kid": app_id})`), usando un objeto de clave privada RSA cargado con
`cryptography.hazmat.primitives.serialization.load_pem_private_key`.

**Actualización 2026-08-09 — verificado contra API real**: la suposición
inicial (`PS256`, con `iss`/`aud` derivados del `app_id`/URL base) era
incorrecta y producía `401 Unauthorized` contra `GET /aspsps` real. La
documentación oficial (`docs.enablebanking.com/api/quick-start/`) especifica
`RS256`, no `PS256`. `docs/context.md` (que motivó la decisión original)
debe corregirse igualmente.

**Racional**: `PyJWT` soporta `RS256` de forma nativa cuando se le pasa una
clave RSA cargada vía `cryptography` (ya dependencia del proyecto desde
IT1). No se necesita ninguna librería JWT adicional.

**Claims del JWT (verificados contra API real)**:
- `iss`: literal fijo `"enablebanking.com"` — **no** el `app_id`.
- `aud`: literal fijo `"api.enablebanking.com"` — **no** la URL base con
  esquema.
- `iat`, `exp`: timestamps Unix, vida corta (el conector usa 300 s).
- Cabecera JWT (no es un claim del payload): `kid` = `app_id` de
  `eb-config.json`.

El nombre exacto de cada claim se aísla en una única función `_build_jwt()`
dentro de `ing.py`, de forma que futuros ajustes de protocolo no afecten al
resto del conector.

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| `python-jose` | Librería adicional; `PyJWT` ya es la elección documentada del proyecto |
| Firma manual con `cryptography` (sin librería JWT) | Reinventa la codificación/serialización JWT (header, payload, base64url); alto riesgo de error, sin beneficio |

---

## Decisión 3: Detección de sesión inutilizable (re-autorización manual)

**Decisión**: El conector considera que la sesión requiere re-autorización
manual cuando ocurre **cualquiera** de estas dos condiciones, verificadas en
un único punto (`_check_session_usable()`) antes de devolver cualquier dato:

1. La API responde con **HTTP 403** a cualquier petición del conector.
2. La respuesta de la API incluye un campo de estado de sesión cuyo valor es
   literalmente `"expired"` **[verificar contra documentación real: nombre
   exacto del campo — se asume algo equivalente a `status` en el cuerpo de la
   respuesta de error o en un endpoint de estado de sesión]**.

Ambas condiciones lanzan el mismo tipo de excepción,
`ReauthorizationRequiredError`, con un mensaje que indica explícitamente que
se requiere el flujo de consentimiento manual por navegador (FR-004).

**Racional**: `docs/context.md` confirma que Enable Banking no tiene
mecanismo de refresh token y que la única recuperación es la
re-autorización manual — esto es una restricción de negocio estable,
independiente del nombre exacto del campo de estado en el JSON de respuesta.
Aislar la verificación del campo en una sola función permite corregir el
nombre del campo, si difiere de lo asumido, sin tocar el resto del conector.

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| Solo comprobar HTTP 403 | No cubre el caso donde la API devuelve 200 con un cuerpo indicando `expired` (mencionado explícitamente en la descripción original de la funcionalidad) |
| Reintentar automáticamente ante 403 | No existe refresh token; reintentar sin re-autorización manual nunca tendría éxito (violaría FR-003) |

---

## Decisión 4: Detección del límite de peticiones PSD2

**Decisión**: Cualquier respuesta **HTTP 429** (en la petición inicial o en
cualquier petición de paginación posterior) lanza `RateLimitExceededError`,
con un mensaje que indica explícitamente que se ha superado el límite de 4
peticiones/cuenta/día. Esta excepción es de un tipo distinto a
`ReauthorizationRequiredError`.

**Racional**: FR-008 exige un error descriptivo y diferenciado; `docs/context.md`
confirma el límite regulatorio como una restricción dura de la API, no un
detalle de implementación del conector — el conector solo necesita
reconocer la señal (429) y traducirla a un mensaje claro, no implementar
lógica de recuento propia (el límite lo aplica la API, no el conector).

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| Llevar un contador local de peticiones/día | Duplica lógica que la API ya aplica; añade estado persistente que FR-009 prohíbe (contadores tendrían que sobrevivir entre invocaciones) |
| Reintentar automáticamente tras backoff | El límite es diario, no de ráfaga; un backoff corto no resolvería el 429 y ocultaría el problema real al operador |

---

## Decisión 5: Paginación vía `continuation_key`

**Decisión**: Bucle que repite la petición de transacciones pasando el
`continuation_key` de la respuesta anterior, hasta que la respuesta no
incluya uno. Se aplica un límite máximo de páginas por invocación
(constante `MAX_PAGES`, valor inicial 100) como salvaguarda; si se alcanza
sin agotar la paginación, se lanza `PaginationLimitExceededError` en lugar de
continuar indefinidamente.

**Racional**: FR-005 exige recuperar todas las páginas; el Caso Límite de
paginación infinita exige un límite razonable en vez de un bucle sin fin. El
valor de `MAX_PAGES` es una salvaguarda interna, no configurable por el
usuario en v1 (Suposición del spec).

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| Sin límite de páginas | Un fallo o bug en la API (o en el parseo del `continuation_key`) podría causar un bucle infinito real |
| Límite configurable por variable de entorno | Complejidad innecesaria para v1 (YAGNI); un valor fijo generoso (100 páginas) cubre cualquier rango de fechas razonable para una sola cuenta |

---

## Decisión 6: Deduplicación de transacciones

**Decisión**: Clave de deduplicación = tupla `(fecha_liquidación, importe,
descripción/contraparte)`. Se mantiene un `set` de claves vistas durante la
recopilación de páginas; una transacción cuya clave ya fue vista se descarta
silenciosamente (no es un error, es el comportamiento esperado ante solape de
página).

**Racional**: Decidido explícitamente en `/speckit-clarify` (no se asume que
la API entregue un identificador propio de transacción).

---

## Decisión 7: Redacción de secretos en logs

**Decisión**: Ninguna llamada a `logging` en `ing.py` interpola la clave
privada RSA, el JWT firmado (completo o parcial) ni el `session_id` completo.
Los logs de error usan únicamente: nombre del banco (`"ING España"`), rango
de fechas solicitado, número de registros (en éxito) o una descripción corta
y no sensible del motivo del fallo (p. ej. `"HTTP 403 — reautorización
manual requerida"`, `"HTTP 429 — límite de peticiones PSD2 excedido"`).

**Racional**: Decidido explícitamente en `/speckit-clarify` (FR-015).

**Mecánica de aplicación**: Ninguna excepción personalizada del módulo
(`ReauthorizationRequiredError`, `RateLimitExceededError`,
`EnableBankingAPIError`, `ConnectorConfigError`, `InvalidDateRangeError`,
`PaginationLimitExceededError`) acepta ni almacena en su mensaje la clave
privada, el JWT o el `session_id`; solo códigos de estado HTTP y texto
descriptivo fijo.

---

## Decisión 8: Formato de logging estructurado

**Decisión**: Se reutiliza el `logging` estándar de Python ya configurado por
el proyecto (formato `%(asctime)s %(levelname)s %(name)s: %(message)s`, por
constitución). El conector emite:
- Un log `INFO` al final de una invocación exitosa: banco, inicio, fin,
  número de registros, estado `success`.
- Un log `ERROR` al final de una invocación fallida: banco, inicio, fin,
  estado `error`, motivo (sin datos sensibles, ver Decisión 7).
- Un log `WARNING` por cada registro de transacción omitido por campos
  faltantes (FR-012).

**Racional**: Reutiliza el mecanismo ya establecido por la constitución
(Performance & Observability) y por IT1; no se introduce un formato o
librería de logging nueva.

---

## Decisión 9: Configuración local reutilizada de IT1

**Decisión**: El conector lee `~/.config/banca-personal/eb-config.json`
(campos `app_id`, `private_key_path`) tal como IT1 ya lo documentó y
preparó en `quickstart.md` (paso 9) y `data-model.md` (Entidad 4). El
`session_id` se lee vía `SecretStore.get("ENABLE_BANKING_SESSION_ID")`
(mecanismo ya implementado en IT1, `contracts/secret-store-format.md`). No
se introduce ningún fichero de configuración nuevo.

**Racional**: Evita duplicar el trabajo ya hecho en IT1; sigue exactamente el
contrato que esa iteración dejó preparado para esta.

**Manejo de ausencia/error**: Si `eb-config.json` no existe, no es JSON
válido, o le falta `app_id` o `private_key_path` — o si el fichero de clave
privada referenciado no existe o no es una clave RSA válida — el conector
lanza `ConnectorConfigError` antes de cualquier llamada de red (Caso Límite
del spec).

---

## Decisión 10: Nuevas dependencias pineadas

**Decisión**: Añadir `httpx` y `PyJWT` a `requirements.txt` con versión exacta
(mismo método que IT1: `pip install` seguido de `pip freeze`), durante la
fase de implementación (`/speckit-tasks` → `/speckit-implement`), no en este
documento de planificación.

**Racional**: Ambas ya estaban previstas como dependencias principales del
proyecto en `docs/context.md`; esta es la iteración que las introduce
efectivamente en `requirements.txt`. Cumple el Anti-patrón #10 (sin rangos de
versión abiertos).
