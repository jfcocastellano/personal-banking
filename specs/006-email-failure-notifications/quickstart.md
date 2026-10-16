# Quickstart: Validación de la notificación de errores por email

## Prerrequisitos

- Entorno ya configurado desde IT1-IT5: `BANKING_MASTER_KEY` en el entorno del SO, `.env` cifrado
  con `GOOGLE_SHEET_ID`, `GOOGLE_SHEETS_CREDENTIALS` y las cuatro claves
  `ENABLE_BANKING_SESSION_ID_<BANCO>`.
- **Nueva configuración SMTP** (una sola vez, ver `research.md` Decisión 3) — contraseña de
  aplicación de Gmail (requiere 2FA activo en la cuenta Google):

  ```
  python -m banking secrets set SMTP_HOST smtp.gmail.com
  python -m banking secrets set SMTP_PORT 465
  python -m banking secrets set SMTP_USER <tu-cuenta>@gmail.com
  python -m banking secrets set SMTP_PASSWORD <contraseña de aplicación de 16 caracteres>
  python -m banking secrets set NOTIFY_EMAIL_TO <tu-cuenta>@gmail.com
  ```

  En CI (IT7) estas cinco claves se mapearán a GitHub Secrets; ninguna va en el YAML ni en el
  código (Principio IV).

## Validación automatizada (CI, sin red real)

```
pytest tests/unit -q
ruff check .
ruff format --check .
mypy src
```

Confirma en particular:
- `tests/unit/test_notify.py` — contenido del email (asunto por desenlace, líneas por banco, sin
  secretos), interacción SMTP mockeada (`Mock(spec=smtplib.SMTP)`), y los tres estados de entrega
  (`SENT`/`SKIPPED`/`FAILED`) — ver `contracts/notify-interface.md`.
- `tests/unit/test_cli_sync.py` — los 5 códigos de salida (0/1/2/3/4, ver
  `contracts/cli-sync-interface.md`), notificador invocado solo en ramas fallidas, y el caso
  combinado banco+escritura.
- `tests/unit/test_sync.py` — las excepciones `AllBanksFailedError`/`SheetsSyncError` llevan
  `outcomes` y `tab_name` rellenos.

## Validación manual end-to-end (opcional, contra Gmail real)

1. **Camino feliz — sin email**: ejecutar `python -m banking sync` con las cuatro sesiones válidas.
   Confirmar: resumen `Sincronización completada: 4/4 bancos`, exit code `0`, y **ningún email** en
   el buzón (FR-003).

2. **Fallo parcial — email con detalle**: forzar el fallo de un solo banco (p. ej. dejar expirar la
   sesión de Revolut) y volver a ejecutar. Confirmar: resumen `Sincronización parcial: 3/4 bancos`
   con exit code `3`, y **un email** cuyo asunto dice `Sincronización parcial: 3/4 bancos — fallo
   en <YYYY-MM>` y cuyo cuerpo lista el banco fallido con su motivo y los tres exitosos con sus
   recuentos (US1).

3. **Fallo de Sheets — email con causa principal**: renombrar temporalmente el documento de Google
   (o revocar el acceso de la service account) y ejecutar con las sesiones válidas. Confirmar:
   `ERROR (Sheets): ...` en stderr con exit code `2`, y **un email** con asunto
   `Sincronización fallida: error escribiendo en Google Sheets — <YYYY-MM>` y la línea
   `ERROR (Sheets): <motivo>` en el cuerpo (US2). Restaurar el documento después.

4. **Configuración ausente — degradación silenciosa**: eliminar temporalmente `SMTP_PASSWORD` del
   `.env` (re-guardar el valor aparte) y forzar un fallo parcial. Confirmar: el exit code sigue
   siendo `3` (no `4`), en los logs aparece un `WARNING` de configuración de notificación ausente,
   y no se envía ningún email (FR-007). Restaurar la clave después.

5. **Fallo de entrega — exit 4**: configurar deliberadamente una contraseña SMTP incorrecta y
   forzar un fallo parcial. Confirmar: el resumen de la ejecución se imprime igualmente, en stderr
   aparece `ERROR (notificación): no se pudo enviar el email de aviso — ...`, y el exit code es `4`
   (FR-006). Restaurar la contraseña después.

6. **Fallo total**: no viable de forma realista sin revocar las cuatro sesiones; cubierto por el
   escenario mockeado en `test_notify.py`/`test_cli_sync.py` (FR-011b). Si se desea validar,
   revocar las cuatro sesiones y confirmar exit code `1` más un email con asunto
   `Sincronización fallida: los 4 bancos fallaron — <YYYY-MM>`.

## Presupuesto de rendimiento (SC-006)

La entrega del email debe completarse en menos de 60 segundos desde la detección del fallo (SLO de
la constitución). El timeout de conexión/lectura SMTP está fijado en 30s: un servidor caído
produce `FAILED` (exit 4) en como mucho ~30s, nunca un cuelgue indefinido. En la validación manual
(pasos 2/5), el email debe llegar al buzón en menos de un minuto tras imprimirse el resumen.
