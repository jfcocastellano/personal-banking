# Investigación: Escritor Genérico de Google Sheets

**Salida de Fase 0 para**: `specs/003-google-sheets-writer/plan.md`
**Fecha**: 2026-08-09

> **Nota sobre fuentes**: `docs/context.md` (fuente de verdad del proyecto) ya
> fija `gspread` y `google-auth` como librerías principales para Google
> Sheets. Las decisiones de superficie exacta de API de abajo (nombres de
> método, excepciones) se han verificado contra la documentación oficial de
> `docs.gspread.org` el 2026-08-09 (no contra una llamada real, que queda
> para la validación manual opcional de `quickstart.md`), aprendiendo de IT2
> — donde una suposición de protocolo no verificada (JWT PS256) produjo un
> `401` real y hubo que corregirla después de implementar.

---

## Decisión 1: Librería de acceso a Google Sheets

**Decisión**: `gspread`, autenticado vía `gspread.service_account_from_dict(info)`,
donde `info` es el JSON de la cuenta de servicio ya deserializado (`dict`).

**Racional**: `docs/context.md` ya documenta `gspread` como librería principal.
`service_account_from_dict()` acepta directamente un `dict` en memoria — no
requiere escribir el JSON de la cuenta de servicio a un fichero temporal en
disco, lo cual encaja mejor con el mecanismo de secretos cifrados ya
existente (`SecretStore`, IT1), que devuelve el secreto como cadena en
memoria. Verificado contra `docs.gspread.org/en/latest/oauth2.html`
(2026-08-09): usa por defecto `gspread.auth.DEFAULT_SCOPES` (Sheets + Drive
de lectura/escritura), suficiente para crear/sobrescribir pestañas sin
configuración de scopes adicional.

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| `google-auth` (`Credentials.from_service_account_info`) + `googleapiclient.discovery.build("sheets", "v4", ...)` | Requiere manejar directamente la forma cruda de la API de Sheets (`spreadsheets.values.update`, `batchUpdate` para crear pestañas); `gspread` ya envuelve exactamente esas operaciones con una interfaz más simple, sin sacrificar capacidad — usar la API cruda sería reinventar lo que `gspread` ya ofrece (YAGNI, Principio VII) |
| `Credentials.from_service_account_file(path)` + `gspread.authorize()` | Requiere un fichero en disco; el proyecto ya tiene un mecanismo de secretos en memoria (`SecretStore`) que evita escribir credenciales sensibles a disco fuera de lo estrictamente necesario |

**Nota sobre `docs/context.md`**: Esa fuente de verdad lista `google-auth`
como librería principal separada, anticipando el patrón de credenciales
manual (alternativa rechazada arriba). Con `service_account_from_dict()`,
`google-auth` se usa igualmente pero como dependencia transitiva de
`gspread` — no se importa directamente en este componente. `requirements.txt`
solo necesita pinear `gspread`. Se recomienda ajustar `docs/context.md` en
esta misma iteración para reflejarlo (ver Fase 1 / Constitution Check).

---

## Decisión 2: Secreto de la cuenta de servicio — clave reutilizada de IT1

**Decisión**: El JSON de la cuenta de servicio se lee vía
`SecretStore.get("GOOGLE_SHEETS_CREDENTIALS")`, deserializado con
`json.loads()` antes de pasarlo a `gspread.service_account_from_dict()`.

**Racional**: IT1 ya reservó exactamente esta clave en
`contracts/secret-store-format.md` y en el `.env.example` committeado
(`GOOGLE_SHEETS_CREDENTIALS=enc:placeholder`). Reutilizarla evita introducir
una segunda convención de nombres de secreto para el mismo propósito.

**Manejo de ausencia/error** (Caso Límite del spec): Si la clave no existe
en el `SecretStore`, el JSON almacenado no es válido, o le faltan campos
requeridos por `gspread`/Google (p. ej. `client_email`, `private_key`), el
componente lanza `SheetsConfigError` antes de cualquier llamada de red.

---

## Decisión 3: Identificador de documento y nombre de pestaña — parámetros, no secretos

**Decisión**: El ID del documento (`document_id`) y el nombre de la pestaña
(`tab_name`) son parámetros de entrada de la función pública del componente
(FR-002), no se leen desde `SecretStore` dentro de este componente.

**Racional**: El spec es explícito (Suposiciones): este componente es
genérico y no orquesta nada; decidir qué documento y qué pestaña usar es
responsabilidad del proceso llamador (IT4+). Nótese que IT1 también reservó
una clave `GOOGLE_SHEET_ID` en `secret-store-format.md` — esa clave la leerá
el proceso llamador de IT4 para obtener el `document_id` real antes de
invocar a este componente; no la lee este módulo.

---

## Decisión 4: Crear pestaña vs. sobrescribir — superficie de `gspread` verificada

**Decisión**: Secuencia de llamadas, verificada contra
`docs.gspread.org/en/latest/api/models/client.html` y
`.../spreadsheet.html` (2026-08-09):

1. `client.open_by_key(document_id)` → `Spreadsheet`. Si el documento no
   existe o la cuenta de servicio no tiene acceso, `gspread` lanza
   `gspread.exceptions.SpreadsheetNotFound` **[verificar contra API real: la
   documentación describe esta excepción como cubriendo ambos casos —
   "non-existent or inaccessible" — para `open()`; para `open_by_key()` en
   concreto no se ha confirmado con una llamada real si un 403 de permisos
   se traduce en la misma excepción o en un `gspread.exceptions.APIError`
   con `response.status_code == 403`]**. El componente captura ambas
   posibilidades y las traduce a `SheetsAccessError`.
2. `spreadsheet.worksheet(tab_name)` → `Worksheet` si existe; lanza
   `gspread.exceptions.WorksheetNotFound` si no. Esta excepción se captura
   internamente como señal (no es un error de cara al llamador) para pasar
   al paso de creación.
3. Si no existe: `spreadsheet.add_worksheet(title=tab_name, rows=<mínimo 1>,
   cols=<nº columnas de la cabecera>)` → `Worksheet` nueva.
4. Si ya existe: `worksheet.clear()` — borra la totalidad del contenido
   (FR-004), antes de escribir nada nuevo.
5. En ambos casos: `worksheet.update(values=[headers, *rows])` — un único
   `update` con la fila de cabeceras seguida de las filas de datos, sin
   pasar `range_name` (por defecto escribe desde `A1`, cumpliendo FR-005).

**Racional**: Un único `update()` con todos los valores evita una llamada
por fila (más lento, más peticiones contra la cuota de la API) y evita
dejar la pestaña en un estado a medio escribir durante más tiempo del
necesario — aunque, como documenta el spec (Casos Límite), no hay garantía
transaccional completa entre `clear()` y `update()`.

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| `update_cells()` con una lista de objetos `Cell` | Requiere construir manualmente cada celda; `update()` con una lista de listas ya expresa exactamente la forma de entrada del componente (FR-002) sin transformación adicional |
| Comprobar existencia de la pestaña listando todas las pestañas (`spreadsheet.worksheets()`) y buscando por nombre | Una llamada adicional innecesaria; `worksheet(title)` ya hace esa búsqueda del lado del servidor y expone el caso "no existe" mediante una excepción clara |

---

## Decisión 5: Tipos de valor aceptados

**Decisión**: Solo primitivos JSON-serializables (`str`, `int`, `float`,
`bool`, `None`) en la fila de cabeceras y en las filas de datos, pasados a
`worksheet.update()` sin transformación (decidido en `/speckit-clarify`).

**Racional**: `gspread.update()` acepta directamente estos tipos y los
traduce a valores de celda de Sheets. Tipos más ricos (`Decimal`, `date`)
quedan fuera: es responsabilidad del proceso llamador convertirlos (p. ej.
`str(monto)`, `fecha.isoformat()`) antes de invocar a este componente —
mantiene el componente sin ningún conocimiento de tipos de dominio (FR-010).

---

## Decisión 6: Jerarquía de excepciones por categoría

**Decisión**: Cuatro excepciones planas (sin clase base compartida),
mismo patrón que `src/banking/connectors/ing.py` (decidido en
`/speckit-clarify`):

| Excepción | Categoría (FR-008) | Se lanza cuando |
|-----------|---------------------|------------------|
| `SheetsConfigError` | (a) configuración/autenticación | Secreto de cuenta de servicio ausente, JSON inválido, o `gspread` rechaza las credenciales al autenticar |
| `SheetsAccessError` | (b) documento/pestaña inaccesible | `gspread.exceptions.SpreadsheetNotFound`, o `APIError` con `response.status_code` en `{403, 404}` al abrir el documento |
| `SheetsQuotaExceededError` | (c) límite de cuota | `gspread.exceptions.APIError` con `response.status_code == 429` |
| `SheetsAPIError` | (d) error de API genérico | Cualquier otro `gspread.exceptions.APIError`, o cualquier excepción inesperada de `gspread` no cubierta arriba |

**Racional**: FR-008 exige distinguir la causa; replicar el patrón ya
validado en IT2 evita introducir una convención nueva de manejo de errores
en el mismo proyecto.

---

## Decisión 7: Logging estructurado

**Decisión**: Reutiliza `logging` estándar (mismo formato que IT1/IT2).
- `INFO` al finalizar con éxito: nombre de pestaña, número de filas de datos
  escritas (sin contar la cabecera), duración en segundos.
- `ERROR` al fallar: nombre de pestaña objetivo, categoría del fallo
  (nombre de la excepción), motivo (mensaje corto, sin el JSON de la cuenta
  de servicio ni ningún token derivado — FR-012).

**Racional**: FR-007/FR-008; mismo mecanismo ya establecido por la
constitución (Performance & Observability) e IT2.

---

## Decisión 8: Forma de la interfaz pública

**Decisión**: Una clase `SheetsWriter` con un cliente `gspread.Client`
inyectable por constructor — mismo patrón que `IngConnector` (IT2) y
`SecretStore` (IT1):

```python
class SheetsWriter:
    def __init__(self, client: gspread.Client | None = None) -> None: ...
    def write(
        self,
        document_id: str,
        tab_name: str,
        headers: list[CellValue],
        rows: list[list[CellValue]],
    ) -> None: ...
```

**Racional**: Permite inyectar en los tests un doble de prueba
(`unittest.mock.Mock(spec=gspread.Client)`, o un objeto construido a mano
que implemente la misma superficie mínima) en vez de un `gspread.Client`
real — sin ninguna llamada de red (FR-011). Es el mismo punto de extensión
que IT2 usó con `httpx.Client(transport=MockTransport(...))`; `gspread` no
ofrece un transporte de mock nativo, así que el punto de inyección aquí es
el cliente completo, no un transporte HTTP.

**Alternativas consideradas**:

| Opción | Por qué se rechazó |
|--------|---------------------|
| Mockear a nivel de `requests`/HTTP subyacente (p. ej. interceptando la sesión `requests` que usa `gspread` internamente) | Acopla los tests a detalles internos de implementación de `gspread` (qué librería HTTP usa por debajo); inyectar el `Client` de `gspread` directamente es la superficie pública documentada de la librería y es más estable ante cambios internos de `gspread` |
| Función libre en vez de clase | El proyecto ya usa el patrón de clase con dependencia inyectable en dos componentes previos (`SecretStore`, `IngConnector`); mantener el mismo patrón reduce la carga cognitiva del único mantenedor |

---

## Decisión 9: Nueva dependencia pineada

**Decisión**: Añadir `gspread` a `requirements.txt` con versión exacta,
durante la fase de implementación (`pip install` + `pip freeze`, mismo
método que IT1/IT2), no en este documento. `google-auth` no se añade como
dependencia directa (Decisión 1) — llega transitivamente vía `gspread`.

**Racional**: Cumple el Anti-patrón #10 (sin rangos de versión abiertos).
