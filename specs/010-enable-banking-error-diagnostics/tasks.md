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

### T003 — Documentar el síntoma en el runbook

`docs/credentials-setup.md`: qué significa un 422, dónde se ve y qué hacer.
Sin inventar códigos de error del proveedor que no hayamos observado.

### T004 — Leer el detalle real de MyInvestor

Volver a correr el sync y leer el cuerpo que ahora sí aparece en el log. Es el
único modo de saber si el consentimiento de MyInvestor venció o si es otra cosa.
Requiere autorización explícita: escribe en la hoja real.

## Fuera de alcance

- La política de exit code del sync parcial (3) y su efecto de alerta diaria.
- Renovar el consentimiento de MyInvestor: depende de lo que diga T004.
- Sabadell: sigue bloqueado del lado del proveedor (ver spec 008).
