# 010 — Diagnóstico de errores de Enable Banking

## Contexto

El workflow `sync` está rojo desde su creación (2026-10-17, 17 corridas, 17
fallos) porque `MyInvestor` y `Banco Sabadell` devuelven HTTP 422. El mensaje
que producen es:

```
Enable Banking returned an unexpected HTTP status: 422.
```

`_check_session_usable` sólo reconoce 403 (sesión rechazada) y 429 (límite
PSD2); cualquier otro código cae en un error genérico que **descarta el cuerpo
de la respuesta**. Enable Banking manda un cuerpo estructurado con el motivo, y
quien esté delante (proxy, CDN) puede mandar HTML. Como el cuerpo se tira, la
causa real de esos 422 es hoy invisible desde los logs de Actions.

El detalle no es cosmético: el 422 aparece en las tres llamadas
(`GET /sessions/{id}`, movimientos y saldos), y en las dos últimas el
estrangulamiento real está en la primera — la búsqueda de sesión falla antes de
llegar al endpoint específico.

## Alcance

Sólo observabilidad. No cambia el comportamiento de negocio, no reintenta, no
interpreta códigos de error del proveedor como veredictos.

## Tareas

### T001 — Incluir el detalle del proveedor en los errores HTTP

`_provider_detail(response)` devuelve un extracto compacto de una sola línea:

- Cuerpo JSON: concatena los campos de texto conocidos (`error`, `message`,
  `detail`, `error_description`, `title`) sin duplicados.
- Cuerpo no JSON (HTML de un proxy): usa el texto crudo.
- Nunca lanza, nunca supera 300 caracteres, colapsa espacios y saltos de línea
  porque termina en un log.
- Cuerpo vacío: no agrega sufijo, para que el mensaje no quede con "detalle: ".

El sufijo se agrega a las cuatro ramas de `_check_session_usable` (403, 429,
200 con `status: expired`, y el error genérico).

**Aceptación**: hay tests de detalle presente, cuerpo vacío, cuerpo no JSON y
cuerpo enorme truncado; ningún test existente cambia de expectativa.

### T002 — Mensaje accionable para 422

Una rama propia para 422 que dice qué suele significar y qué hacer, señalando
el runbook. El tipo de excepción sigue siendo `EnableBankingAPIError`: nada en
el sistema distingue `ReauthorizationRequiredError` de un error genérico — el
texto es el único canal hacia el usuario y hacia el resumen del workflow.

**Aceptación**: el mensaje de un 422 en la búsqueda de sesión incluye el
detalle del proveedor y la indicación de reautorizar.

**Corrección posterior a T004**: la primera redacción afirmaba que un 422 en la
búsqueda de sesión "casi siempre" significa consentimiento vencido. La
evidence la desmintió: el proveedor responde `WRONG_REQUEST_PARAMETERS`, es
decir que rechaza un parámetro, no el consentimiento. El texto se reescribió
para decir lo que se sabe — la firma se aceptó, un parámetro está mal — y para
ofrecer la reautorización como condición, no como diagnóstico.

### T003 — Documentar el síntoma en el runbook

`docs/credentials-setup.md` § 10.1: qué significa un 422, cómo se lee el
mensaje y qué hacer según lo que muestre. Incluye el caso `InvalidURL` que
descubrió T005.

### T005 — Describir la forma del `session_id` sin revelarlo

Un 422 en la búsqueda de sesión sólo puede estar rechazando el `session_id`, que
es el único parámetro de esa llamada. El mensaje ahora incluye
`length`, `empty`, `surrounding-whitespace` y `non-ascii` — nunca el valor —
para distinguir un secreto mal cargado de un consentimiento que el banco ya no
reconoce.

**Aceptación**: hay tests de una sesión con espacios alrededor y de una limpia;
ninguno de los dos mensajes contiene el valor del secreto.

### T006 — Reconocer el valor inerte `unconfigured`

**Hallazgo del diagnóstico**: el 422 no era un consentimiento vencido ni un
secreto mal cargado. Los dos secretos seguían con el centinela documentado en
§ 6 — 12 caracteres, el mismo largo en ambos bancos — y el conector lo mandaba
al proveedor como si fuera una sesión.

Ahora `_is_unconfigured_session()` lo detecta antes de la primera llamada y
levanta `ConnectorConfigError` con la acción concreta. Efectos: no se gasta
cuota PSD2 (4 requests por cuenta por día), el resumen nombra la causa real, y
el tipo de excepción pasa a ser el que describe el problema.

**Aceptación**: tests de que no sale ninguna petición HTTP, de que el centinela
se reconoce con mayúsculas y espacios, y de que una sesión real sigue viajando.

## Evidencia

- Commit `45cbcd0` — cuerpo del proveedor en las cuatro ramas de error + rama
  propia para 422.
- Commit siguiente — corrección de redacción, `_describe_session_id` y runbook.
- `269 passed`, `ruff check`, `ruff format --check`, `mypy src` limpios.
- Corrida real del sync sobre la rama (`41299786210`), que por primera vez
  informó la causa:

  ```
  MyInvestor: WRONG_REQUEST_PARAMETERS: Wrong request parameters
  Banco Sabadell: WRONG_REQUEST_PARAMETERS: Wrong request parameters
  ```

### T004 — Leer el detalle real de MyInvestor

**Hecho**, y el resultado desarmó la premisa de la unidad: el proveedor
rechazaba los parámetros porque los parámetros eran `unconfigured`. MyInvestor y
Sabadell nunca tuvieron sesión; el sync parcial que se veía como incidente es el
estado documentado en § 6. Ver T006.

## Seguimiento detectado

- `httpx.InvalidURL` por un salto de línea en el secreto no se traduce a un
  mensaje propio: sale como excepción del cliente. Es raro y ruidoso, pero no
  es esta unidad.
- La política de exit code: el sync parcial sale 3 y el workflow lo trata como
  fallo, así que la alerta diaria de IT6 se repite desde el 2026-10-17. Vale
  decidir si un parcial conocido debe seguir siendo rojo todos los días.

## Fuera de alcance

- La política de exit code del sync parcial (3) y su efecto de alerta diaria.
- Renovar el consentimiento de MyInvestor: depende de lo que diga T004.
- Sabadell: sigue bloqueado del lado del proveedor (ver spec 008).
