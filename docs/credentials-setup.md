# Alta y renovación de credenciales

> Runbook de reconstrucción de las 14 credenciales que necesita el sistema.
> Última actualización: 2026-10-18

Este documento existe porque las credenciales **no viven en el repositorio**
(por diseño: `.env` y `*.pem` están en `.gitignore`), así que no hay forma de
recuperarlas desde el código. Aquí está de dónde sale cada una, cómo se
reconstruye desde cero y cómo se suben a GitHub Secrets.

Es el procedimiento de "camino B": reconstruir desde los proveedores cuando no
queda nada utilizable en la máquina anterior. El procedimiento rutinario de una
sola vez está en [`quickstart.md`](../quickstart.md) § IT7.

---

## 0. Las 14 credenciales, de un vistazo

| # | Secreto | Qué es | Dónde se obtiene | Caduca |
|---|---|---|---|---|
| 1 | `BANKING_MASTER_KEY` | Clave AES-256 (64 hex) del `SecretStore` | La generas tú | No (si la pierdes, el `.env` es ilegible) |
| 2-5 | `ENABLE_BANKING_SESSION_ID_{ING,REVOLUT,MYINVESTOR,SABADELL}` | Consentimiento PSD2 por banco | Flujo `/auth` + `/sessions` de Enable Banking (§ 3) | Sí, hasta el `maximum_consent_validity` del ASPSP (90-180 días) |
| 6 | `ENABLE_BANKING_APP_ID` | Identificador de tu aplicación en Enable Banking | Panel de Enable Banking | No |
| 7 | `ENABLE_BANKING_PRIVATE_KEY` | Clave RSA (PEM) con la que se firma el JWT | Panel de Enable Banking (o generada por ti) | No |
| 8 | `GOOGLE_SHEETS_CREDENTIALS` | JSON de la cuenta de servicio de Google Cloud | Google Cloud Console (§ 4) | No |
| 9 | `GOOGLE_SHEET_ID` | ID del documento de Sheets | URL de la hoja (§ 4) | No |
| 10-13 | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Envío del email de fallo por Gmail | Cuenta de Gmail + app password (§ 5) | La app password, sí |
| 14 | `NOTIFY_EMAIL_TO` | Destinatario del email | Tu decisión | No |

Los 1-13 viven en el `.env` cifrado (`SecretStore`); los 6-7 viven además en
`~/.config/banca-personal/` porque el conector de Enable Banking firma con un
fichero, no con el `SecretStore` (ver `src/banking/connectors/enable_banking.py`).

> ⚠️ La línea `ENABLE_BANKING_APP_ID` de `.env.example` es heredada y **no se
> usa**: el `app_id` se lee de `eb-config.json`.

---

## 1. Clave maestra y `.env`

```bash
# Genera la clave (solo la primera vez; guárdala en tu gestor de contraseñas)
python -c "import secrets; print(secrets.token_hex(32))"

# Linux/macOS: expórtala en el perfil de tu shell (.bashrc/.zshrc)
export BANKING_MASTER_KEY=<los-64-hex>

# Comprueba que está disponible en la sesión actual
test -n "$BANKING_MASTER_KEY" && echo "clave presente"
```

Si **recuperas la clave maestra** de la máquina antigua, el `.env` antiguo sigue
siendo válido y no hace falta volver a introducir nada. Si creas una nueva, todos
los valores `enc:...` anteriores quedan ilegibles: hay que repetir los pasos 2-5.

---

## 2. Application de Enable Banking (`app_id` + PEM)

1. Entra en el panel de Enable Banking con tu cuenta (la que ya tiene ING dado de
   alta) y abre tu *application*.
2. Copia el **Application ID** → será `ENABLE_BANKING_APP_ID`.
3. Descarga la **clave privada RSA** de la aplicación, o genera un par nuevo y
   sube la parte pública al panel. El fichero descargado es `ENABLE_BANKING_PRIVATE_KEY`.
4. Déjala en el directorio que lee el conector, con permisos restringidos:

```bash
mkdir -p ~/.config/banca-personal
chmod 700 ~/.config/banca-personal
mv ~/Descargas/private_key.pem ~/.config/banca-personal/private_key.pem
chmod 600 ~/.config/banca-personal/private_key.pem

cat > ~/.config/banca-personal/eb-config.json <<JSON
{
  "app_id": "<application-id>",
  "private_key_path": "$HOME/.config/banca-personal/private_key.pem"
}
JSON
chmod 600 ~/.config/banca-personal/eb-config.json
```

Comprobación (no imprime la clave, solo verifica que carga):

```bash
python -c "
from banking.connectors.enable_banking import _load_signing_credential, _build_jwt
c = _load_signing_credential(None)
print('app_id OK, JWT de', len(_build_jwt(c)), 'caracteres')
"
```

---

## 3. Sesión PSD2 de ING (`ENABLE_BANKING_SESSION_ID_ING`)

El código **no** crea sesiones: consume una ya autorizada. La creación es un
flujo de consentimiento en el navegador, en tres llamadas a la API. Usa los
mismos helpers que el conector, así la firma es idéntica a la de producción.

**3.1 — Pedir la URL de consentimiento**

```bash
python - <<'PY'
import datetime as dt
import httpx
from banking.connectors.enable_banking import _build_jwt, _load_signing_credential

cred = _load_signing_credential(None)
headers = {"Authorization": f"Bearer {_build_jwt(cred)}"}
valid_until = (dt.datetime.now(dt.UTC) + dt.timedelta(days=170)).isoformat()

response = httpx.post(
    "https://api.enablebanking.com/auth",
    headers=headers,
    json={
        "access": {"valid_until": valid_until},
        "aspsp": {"name": "ING", "country": "ES"},
        "state": "banca-personal",
        "redirect_url": "https://nasts251cloud.myqnapcloud.com:5051/callback",
        "psu_type": "personal",
        "language": "es",
    },
    timeout=30,
)
response.raise_for_status()
print(response.json()["url"])
PY
```

Tres detalles de este bloque, que son los que fallan cuando algo no cierra:

- **`redirect_url` debe coincidir exactamente** con el registrado en tu
  aplicación. Consultalo con `GET /application`; en este proyecto es
  `https://nasts251cloud.myqnapcloud.com:5051/callback`. Cualquier otra cosa
  (por ejemplo `https://localhost:8080/callback`) devuelve
  `REDIRECT_URI_NOT_ALLOWED` y quema el `authorization_id`.
- **`valid_until` va por debajo del máximo del ASPSP**, que se publica en
  `GET /aspsps` como `maximum_consent_validity`. Banco Sabadell permite 180 días,
  así que se piden 170: rozar el límite hace que el banco rechace el
  consentimiento por desfase de reloj.
- **`psu_type` y `language` son obligatorios en la práctica**: sin ellos algunos
  ASPSPs devuelven el consentimiento en otro idioma o rechazan el `psu_type`
  implícito.

**3.2 — Autorizar en el navegador**

Abre la URL que imprime, **en un navegador real y con cookies** (la capa de
consentimiento de Enable Banking, `tilisy.enablebanking.com`, mantiene la sesión
en una cookie `sessionid`; sin ella responde `400 {"detail":"Missing session id"}`,
así que no sirve seguirla con `curl` ni pegarle saltos a mano). Tras
autenticarte y dar el consentimiento, el banco redirige al `redirect_url`
registrado con `?code=...&state=...`. Si el callback no está levantado, el
navegador muestra un error de conexión: da igual, **copia el valor de `code`** de
la barra de direcciones (caduca en minutos) y no vuelvas a abrir esa URL — cada
`authorization_id` es de un solo uso.

**3.3 — Canjear el `code` por el `session_id`**

```bash
python - <<'PY'
import httpx
from banking.connectors.enable_banking import _build_jwt, _load_signing_credential

code = input("Pega el code de la URL: ").strip()
headers = {"Authorization": f"Bearer {_build_jwt(_load_signing_credential(None))}"}
response = httpx.post(
    "https://api.enablebanking.com/sessions",
    headers=headers,
    json={"code": code},
    timeout=30,
)
response.raise_for_status()
data = response.json()
print("SESSION_ID:", data["session_id"])
print("CUENTAS:", data.get("accounts"))
PY
```

**3.4 — Guardarla**

```bash
python -m banking secrets set ENABLE_BANKING_SESSION_ID_ING <session_id>
```

> Si el banco devuelve alguna variante de nombre de ASPSP, ajústala en
> `aspsp.name` / `country` (por ejemplo `"ING"` + `"ES"` es lo habitual para ING
> España). El conector solo necesita que `GET /sessions/{id}` devuelva la cuenta.

**3.5 — Particularidades: Banco Sabadell (y clientes de ActivoBank)**

ASPSP a usar: `{"name": "Banco de Sabadell", "country": "ES"}` (BIC
`BSABESBBXXX`, `maximum_consent_validity` 180 días). No existe un ASPSP
"ActivoBank" español en Enable Banking.

El login PSD2 de Sabadell se sirve por **marca**, y la marca la fija el host, no
la pestaña de la pantalla:

| Host del login | Marca | `SERVICE_PROCEDENCE` | Pestañas |
|---|---|---|---|
| `openapi.bancsabadell.com` | bancsabadell | `CA01` | Particular (`CA01`), Empresa (`CA02`) |
| `openapi.activobank.com` | activobank | `CA03` | ninguna (canal fijo) |

Ese valor viaja como **header** (`HEADER.SERVICE_PROCEDENCE`), no por URL, y
Enable Banking solo rutea al host de Sabadell. Un cliente de ActivoBank no puede
ser atendido por ese canal.

**Estado: bloqueado (escalado a Enable Banking el 2026-10-21).** Síntoma exacto,
después de que el banco **acepte** el login:

```
[{"i18nCode":"unsupported_response_type",
  "description":"Client does not support this response type."}]
```

Cómo leerlo, para no perder tiempo la próxima vez:

- La SPA de Sabadell muestra **el mismo modal genérico** ("¡Vaya! Los datos
  introducidos no son correctos.") tanto si fallan las credenciales como si falla
  el paso `authorize` posterior. Ese cartel **no prueba** que la contraseña esté
  mal.
- `authorize` corre solo después de un login `200` con `access_token`, así que
  `unsupported_response_type` implica credenciales correctas y rechazo del cliente
  TPP (`PSDFI-FINFSA-2988499-7`, second client `PSDES-RDS-4000`) en el hub.
- No hay nada que ajustar del lado del usuario: no cambia con la pestaña, con el
  navegador ni con reintentos. Reintentar solo quema `authorization_id`.
- Akamai responde `403 Access Denied` a cualquier sondeo server-side del endpoint
  de login: la verificación requiere un navegador real.

**Respuesta del proveedor (2026-10-21) y por qué el desvío no es accionable.**
Enable Banking contestó que no tiene documentación específica de Sabadell
("Sabadell-specific open-banking details are not yet available", es decir, el
conector está armado sobre la plantilla genérica de Redsys) y derivó el caso al
helpdesk de TPPs de Redsys sin responder ninguna de las dos preguntas:

| Pregunta abierta | Estado |
|---|---|
| ¿Qué `response_type` soporta el cliente `PSDFI-FINFSA-2988499-7` / second client `PSDES-RDS-4000` en este ASPSP? | sin respuesta |
| ¿Cómo autoriza un cliente ActivoBank ES a través del conector de Sabadell? | sin respuesta |

La derivación no se puede ejecutar desde acá: el helpdesk de Redsys es para
**TPPs registrados**, y el TPP ante Redsys es Enable Banking, no el titular de la
cuenta. `hubpsd2.redsys.es` responde `403` a cualquier acceso que no sea de un
TPP registrado, y no existe portal público de soporte. Cualquier ticket abierto
por un particular rebota.

Estado de la escalada: se reclamó a Enable Banking que abra el ticket de Redsys
por su cuenta, o que confirme por escrito que su conector de Sabadell hoy no
puede soportar este ASPSP. En paralelo, un reclamo del titular a Banco Sabadell
es válido y está fundado —el acceso de terceros es una obligación PSD2 del banco,
y el rechazo ocurre en su `authorize`—, aunque su efecto esperable es lento.

Qué destrabaría esto, en orden de probabilidad:

1. Que Enable Banking corrija el registro del cliente o el `response_type` que
   pide su conector (§ 3.1). Es su bug y no requiere cambios acá.
2. Que agreguen un ASPSP ActivoBank ES que rutee al host con `CA03`.
3. Que se use otro agregador con conector propio de Sabadell; implicaría escribir
   otro conector, porque todo el proyecto está apoyado en Enable Banking.

Mientras siga así, `ENABLE_BANKING_SESSION_ID_SABADELL` se queda en
`unconfigured` (§ 6) y las ejecuciones terminan en fallo parcial, que es el
comportamiento correcto.

---

## 4. Google Sheets

1. Google Cloud Console → proyecto → *APIs* → habilita **Google Sheets API** y
   **Google Drive API**.
2. *Credenciales* → *Crear credenciales* → **Cuenta de servicio** → créala.
3. En la cuenta de servicio, pestaña *Claves* → *Añadir clave* → **JSON**.
   Descarga el fichero: ese contenido completo es `GOOGLE_SHEETS_CREDENTIALS`.
4. Crea (o reutiliza) la hoja de cálculo y **compártela como editora** con el
   `client_email` que aparece dentro del JSON (`...@....iam.gserviceaccount.com`).
   Sin este paso, `gspread` autentica pero falla al abrir el documento.
5. El `GOOGLE_SHEET_ID` es la parte entre `/d/` y `/edit` de la URL:
   `https://docs.google.com/spreadsheets/d/<GOOGLE_SHEET_ID>/edit`.

```bash
python -m banking secrets set GOOGLE_SHEETS_CREDENTIALS "$(cat service-account.json)"
python -m banking secrets set GOOGLE_SHEET_ID <id-de-la-hoja>
```

---

## 5. Gmail SMTP

`SMTP_PASSWORD` **no** es la contraseña de la cuenta: es una *app password* de 16
caracteres, que exige tener la verificación en dos pasos activada.

1. Cuenta de Google → *Seguridad* → *Verificación en dos pasos* (actívala si no lo está).
2. *Contraseñas de aplicaciones* → crea una para "Correo" → copia los 16 caracteres.

```bash
python -m banking secrets set SMTP_HOST smtp.gmail.com
python -m banking secrets set SMTP_PORT 465
python -m banking secrets set SMTP_USER <tu-correo@gmail.com>
python -m banking secrets set SMTP_PASSWORD <app-password-sin-espacios>
python -m banking secrets set NOTIFY_EMAIL_TO <destinatario@dominio>
```

---

## 6. Los bancos sin sesión todavía

El código instancia siempre los cuatro conectores y el workflow exige que los 14
secretos existan, así que hasta que autorices cada banco hay que darle un valor
inerte para que el arranque no se bloquee. Sabadell también va acá por ahora:
existe en Enable Banking, pero su consentimiento está bloqueado del lado del
proveedor (§ 3.5).

```bash
for bank in REVOLUT MYINVESTOR SABADELL; do
  python -m banking secrets set "ENABLE_BANKING_SESSION_ID_$bank" unconfigured
done
```

Consecuencia esperada: cada ejecución termina en **fallo parcial** (exit `3`),
el resumen muestra `ING: N movimientos` y tres líneas `FALLÓ — ...`, y llega un
email agregado. Es el comportamiento correcto, no un error de configuración.

Cuando autorices un banco más, repite el § 3 cambiando `aspsp` y la clave
(`ENABLE_BANKING_SESSION_ID_REVOLUT`, etc.). Al completar los cuatro, las
ejecuciones pasan a `success` y dejan de enviar email.

---

## 7. Comprobación local antes de tocar GitHub

Una sola ejecución real (consume cuota PSD2 de la cuenta de ING; el límite es de
4 peticiones/cuenta/día):

```bash
python -m banking sync; echo "exit=$?"
```

Esperado con solo ING: exit `3`, resumen `Sincronización parcial: 1/4 bancos`,
movimientos escritos en la pestaña del mes y email recibido.

---

## 8. Subir los 14 a GitHub Secrets

Los valores viajan por stdin: nunca aparecen en `argv`, ni en el historial del
shell, ni en los logs. Ejecútalo en la máquina donde están las credenciales.

```bash
cd /ruta/a/personal-banking        # donde está el .env con los valores cifrados
REPO=jfcocastellano/personal-banking

test -n "$BANKING_MASTER_KEY" || { echo "Falta BANKING_MASTER_KEY"; return 1; }
printf '%s' "$BANKING_MASTER_KEY" | gh secret set BANKING_MASTER_KEY --repo "$REPO"

for key in \
  ENABLE_BANKING_SESSION_ID_ING ENABLE_BANKING_SESSION_ID_REVOLUT \
  ENABLE_BANKING_SESSION_ID_MYINVESTOR ENABLE_BANKING_SESSION_ID_SABADELL \
  GOOGLE_SHEETS_CREDENTIALS GOOGLE_SHEET_ID \
  SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD NOTIFY_EMAIL_TO; do
  .venv/bin/python -c "
import sys
from banking.config.secret_store import SecretStore
sys.stdout.write(SecretStore().get('$key'))
" | gh secret set "$key" --repo "$REPO" && echo "ok $key"
done

# Enable Banking: app_id + PEM desde el directorio de configuración
EB_DIR="${BANKING_EB_CONFIG_DIR:-$HOME/.config/banca-personal}"
read -r APP_ID PEM < <(.venv/bin/python -c "
import json, sys
c = json.load(open(sys.argv[1]))
print(c['app_id'], c['private_key_path'])
" "$EB_DIR/eb-config.json")
case "$PEM" in /*) ;; *) PEM="$EB_DIR/$PEM" ;; esac
printf '%s' "$APP_ID" | gh secret set ENABLE_BANKING_APP_ID --repo "$REPO"
gh secret set ENABLE_BANKING_PRIVATE_KEY --repo "$REPO" < "$PEM"

gh secret list --repo "$REPO"    # deben aparecer 14 nombres, ningún valor
```

---

## 9. Primera ejecución real

```bash
gh workflow run sync.yml --repo jfcocastellano/personal-banking
gh run watch --repo jfcocastellano/personal-banking
```

Esperado (con solo ING): `failure`, porque el exit code es `3` (fallo parcial);
resumen con una línea por banco, tres `FALLÓ`, la duración y el enlace a los
logs. Ver la ejecución desde la pestaña *Actions* y comprobar la hoja.

Si el paso **Validar configuración** falla, el mensaje `##[error]Faltan secretos
de GitHub: ...` nombra exactamente los que faltan y no se ha llamado a ninguna
API.

---

## 10. Caducidad y renovación

| Qué | Cada cuánto | Cómo se renueva |
|---|---|---|
| Sesiones PSD2 (`ENABLE_BANKING_SESSION_ID_*`) | ~90 días (lo fija el banco en el consentimiento) | Repetir § 3 para ese banco, `gh secret set` de la clave y `gh workflow run sync.yml` |
| App password de Gmail | Cuando se revoca o caduca | Repetir § 5 (solo `SMTP_PASSWORD`) |
| Clave RSA de Enable Banking | No caduca; se rota por seguridad | Generar par nuevo, subir la pública al panel, `gh secret set ENABLE_BANKING_PRIVATE_KEY` |
| Clave maestra | No caduca | Cambiarla obliga a re-cifrar todos los valores (`secrets set` de los 13) |

**Cómo se detecta una sesión caducada**: el conector lanza
`ReauthorizationRequiredError` (HTTP 403 o `status: "expired"`), ese banco cuenta
como fallido, el resumen lo dice con su motivo y el email de IT6 llega en la
misma ejecución. No hay que leer logs para enterarse.
