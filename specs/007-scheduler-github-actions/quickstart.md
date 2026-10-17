# Quickstart — Scheduler en GitHub Actions (IT7)

**Funcionalidad**: `007-scheduler-github-actions` | **Fecha**: 2026-10-17

Guía de puesta en marcha y operación. Todo lo que sigue lo ejecuta el propietario una sola vez
(despliegue) o cuando rote una credencial; el día a día ya no requiere ninguna acción.

---

## 0. Requisitos previos

- IT5 e IT6 desplegados en `main` (`python -m banking sync` con exit codes `0`-`4` y notificación por
  email funcionando).
- `gh` autenticado con permiso de administración del repositorio (para crear secretos).
- Los 14 valores a mano: clave maestra, 4 `session_id`, `app_id` + PEM RSA, JSON de cuenta de
  servicio, ID de hoja, y las 5 claves SMTP del email.

---

## 1. Alta de los 14 secretos

```bash
REPO=jfcocastellano/personal-banking

# Familia A — clave maestra (64 hex) y 11 valores del SecretStore
gh secret set BANKING_MASTER_KEY --repo "$REPO"
gh secret set ENABLE_BANKING_SESSION_ID_ING --repo "$REPO"
gh secret set ENABLE_BANKING_SESSION_ID_REVOLUT --repo "$REPO"
gh secret set ENABLE_BANKING_SESSION_ID_MYINVESTOR --repo "$REPO"
gh secret set ENABLE_BANKING_SESSION_ID_SABADELL --repo "$REPO"
gh secret set GOOGLE_SHEETS_CREDENTIALS --repo "$REPO" < service-account.json
gh secret set GOOGLE_SHEET_ID --repo "$REPO"
gh secret set SMTP_HOST --repo "$REPO"
gh secret set SMTP_PORT --repo "$REPO"
gh secret set SMTP_USER --repo "$REPO"
gh secret set SMTP_PASSWORD --repo "$REPO"
gh secret set NOTIFY_EMAIL_TO --repo "$REPO"

# Familia B — credencial de firma Enable Banking
gh secret set ENABLE_BANKING_APP_ID --repo "$REPO"
gh secret set ENABLE_BANKING_PRIVATE_KEY --repo "$REPO" < private_key.pem
```

`gh secret set` sin `--body` pide el valor por entrada estándar oculta; con `< fichero` admite PEM y
JSON multilínea. Comprobación:

```bash
gh secret list --repo "$REPO"   # deben aparecer los 14 nombres, sin valores
```

**Nunca** subas estos valores al repositorio: `.env` y `*.pem` están fuera del control de versiones
(Principio IV).

---

## 2. Verificación del workflow antes de mergear

En la rama de la funcionalidad:

```bash
python -m pytest tests/unit/test_sync_workflow.py -v   # contrato del workflow, sin red
python -m pytest tests/ -q                             # suite completa (no debe empeorar)
```

Los tests comprueban: disparadores (cron diario + manual, sin `push`/`pull_request`),
`timeout-minutes: 10`, `concurrency` sin cancelación, permisos de lectura, ejecución de
`python -m banking sync`, secretos sólo en `env:` y el paso de resumen.

---

## 3. Primera ejecución real (criterio de cierre de IT7)

```bash
gh workflow run sync.yml --repo "$REPO"          # disparo manual (workflow_dispatch)
sleep 5 && gh run list --workflow=sync.yml --repo "$REPO" --limit 3
gh run watch --repo "$REPO"                      # seguimiento en vivo
```

Qué comprobar en la ejecución:

1. Estado `success` y exit code `0` en el resumen.
2. Resumen con los cuatro datos: `Sincronización completada: 4/4 bancos`, movimientos escritos y
   pestaña, una línea por banco y duración.
3. La pestaña del mes en curso en Google Sheets contiene los movimientos del día.
4. Ningún email recibido (éxito completo, IT6).
5. Duración total por debajo de 10 minutos.

Deja constancia (log o captura) de esa primera ejecución exitosa en la PR o en `docs/context.md`,
como exige el roadmap.

---

## 4. Cambiar la hora diaria

La hora vive en una única línea de `.github/workflows/sync.yml`:

```yaml
on:
  schedule:
    - cron: "0 6 * * *"   # 06:00 UTC = 08:00 Madrid (verano) / 07:00 (invierno)
```

Edita el cron (siempre en UTC), abre PR y mergea. Los workflows programados sólo se ejecutan desde la
rama por defecto, así que el cambio no surte efecto hasta el merge. La sincronización no depende de la
hora: siempre cubre el mes en curso desde el día 1.

---

## 5. Runbook — sesión PSD2 caducada (`403` / `status: "expired"`)

Síntoma esperado: la ejecución falla con exit code `3` (fallo parcial) o `1` (total), el resumen
muestra `<banco>: FALLÓ — ... sesión expirada ...` y llega un email de IT6 con ese banco y motivo.

1. Re-autorizar en el flujo de navegador de Enable Banking para ese banco y obtener el nuevo
   `session_id` (formato `uuid:hash`).
2. Actualizar el secreto:

   ```bash
   gh secret set ENABLE_BANKING_SESSION_ID_<BANCO> --repo "$REPO"
   ```

3. Recuperar el día sin esperar al cron:

   ```bash
   gh workflow run sync.yml --repo "$REPO"
   ```

4. Confirmar ejecución `success` y ausencia de email.

Las sesiones caducan cada 90-180 días (riesgo documentado en `docs/roadmap.md`): es un procedimiento
manual esperado, no un fallo del sistema.

---

## 6. Runbook — rotación de credenciales

| Credencial | Cuándo | Acción |
|---|---|---|
| `ENABLE_BANKING_SESSION_ID_*` | Caducidad PSD2 (90-180 días) | § 5 |
| `ENABLE_BANKING_PRIVATE_KEY` / `ENABLE_BANKING_APP_ID` | Regeneración de la aplicación en Enable Banking | `gh secret set` de ambos y ejecución manual de comprobación |
| `GOOGLE_SHEETS_CREDENTIALS` | Rotación de la clave de la cuenta de servicio | `gh secret set GOOGLE_SHEETS_CREDENTIALS < nuevo.json` |
| `SMTP_PASSWORD` | Cambio de la contraseña de aplicación de Gmail | `gh secret set SMTP_PASSWORD` |
| `BANKING_MASTER_KEY` | Sospecha de compromiso | Rotar exige re-cifrar el `.env`: regenerar los secretos de la familia A con la nueva clave y actualizar `BANKING_MASTER_KEY` |

Tras cualquier rotación: `gh workflow run sync.yml` y verificar `success`.

---

## 7. Validación local sin tocar GitHub

Con el `.env` cifrado y `eb-config.json` ya configurados en la máquina (ver `quickstart.md` raíz):

```bash
python -m banking sync; echo "exit=$?"
```

Es exactamente el comando que ejecuta el workflow (FR-003), así que reproduce cualquier fallo de
sincronización. Ojo con la cuota PSD2 (4 peticiones por cuenta y día): no lo repitas en bucle el mismo
día. El scheduler **no** se puede probar en local: su validación son los tests de § 2 y una ejecución
manual en GitHub (§ 3).

---

## 8. Riesgos operativos conocidos

- **Retraso del cron**: hasta ~15 minutos en horas de alta carga; aceptado y sin impacto en los datos.
- **Desactivación por inactividad**: GitHub desactiva los workflows programados tras periodos largos
  sin actividad en el repositorio. Comprobación periódica: `gh run list --workflow=sync.yml --limit 5`;
  reactivar con un push o desde la UI de Actions.
- **Timeout de 10 minutos**: si se alcanza, no hay email (el proceso muere antes de IT6); el estado
  fallido de la ejecución y el resumen degradado son la señal.
- **Cuota PSD2**: 4 peticiones por cuenta y día. La ejecución diaria consume 1; las ejecuciones
  manuales de recuperación también cuentan — no encadenar más de 3 recuperaciones en el mismo día.
- **Ejecuciones solapadas**: la segunda espera a la primera (`concurrency`); nunca escriben a la vez.
