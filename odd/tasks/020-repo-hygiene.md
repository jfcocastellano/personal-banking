# 020 — Higiene de repositorio: cabeceras de spec, README y ramas muertas

Status: closed (2026-11-19).

## Por qué

Al cerrar la tarea 019 se auditó el repositorio contra la pregunta «¿está todo al
día?». El código y la documentación lo estaban; lo que fallaba era la superficie:

- Siete specs (`002`-`007`) y la `016` seguían rotuladas «Borrador» / «Draft» con
  su trabajo implementado y fusionado hacía meses. La `008` decía „Draft" en inglés.
- No había `README.md`: quien llegaba al repositorio veía una lista de ficheros y
  tenía que adivinar que la puerta de entrada era `quickstart.md`.
- Diez ramas remotas de PRs ya fusionados seguían en `origin`, más `develop`, que
  es ancestro de `main`. Encontrar la rama que importa costaba más de lo que debería.

Nada de esto rompe nada, y ese es justo el problema: es el tipo de deuda que nadie
paga porque no duele.

## Alcance

- **Cabeceras de spec**: `**Estado**: Implementada` en `specs/002`-`specs/007` y
  `**Status**: Implemented` en `specs/008` y `specs/016`. Se respeta el idioma de
  cada documento en vez de homogeneizarlo: el valor tiene que decir la verdad, no
  imponer un estilo.
- **`docs/context.md`**: desaparece el párrafo de «deuda conocida de documentación»,
  que ya no es cierto, y se sustituye por lo que sí sigue vigente: las specs
  describen el contrato de su iteración, y el estado vive en la tabla de iteraciones.
  `specs/010` sigue sin cabecera porque solo tiene `tasks.md`.
- **`README.md`**: puerta de entrada. Qué hace, con qué bancos, cómo se corre, cómo
  se levanta el entorno, cuáles son los límites conocidos (categoría manual, saldos
  como foto, cuota PSD2), la frontera de PII y un mapa de la documentación.
- **Ramas remotas**: borradas las diez de PRs fusionados. `develop` se conserva
  hasta confirmar con el owner: es ancestro de `main` y no aparece en ningún
  workflow, pero es una decisión suya, no del mantenimiento.

## Verificación

- Las ocho cabeceras dicen lo mismo que `docs/context.md`; `grep -ri 'draft\|borrador' specs/`
  no devuelve nada.
- Los números del README son los medidos, no los deseados: 374 tests, cron
  `0 6 * * *`, `0/44` y `0/9` de MCC, cuatro bancos con dos sin sesión PSD2, el
  nombre real del workflow (`Sync diaria`).
- `pytest`, `ruff check`, `ruff format --check` y `mypy src` sin cambios: esta tarea
  no toca código de producción.

## Riesgos

- Un README envejece. Los datos que lo harían mentir (bancos activos, cifras de
  tests, nombre del workflow) están copiados de `docs/context.md`, así que si se
  cambian allí hay que cambiarlos aquí. Es el precio de tener puerta de entrada.
