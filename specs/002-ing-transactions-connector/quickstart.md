# Guía de Validación: Conector de Movimientos ING España (Enable Banking)

Esta guía valida que el conector funciona de extremo a extremo usando
respuestas mockeadas (por defecto, y suficiente para CI) y, opcionalmente,
una sesión PSD2 real ya autorizada (manual, solo local — Principio III).

**Prerrequisitos**: Entorno de IT1 ya configurado (ver `quickstart.md` en la
raíz del repositorio: `BANKING_MASTER_KEY` exportado, dependencias
instaladas). `~/.config/banca-personal/eb-config.json` existente con
`app_id` y `private_key_path` reales, y `private.pem` en esa ruta.

---

## Parte A — Validación con mocks (siempre disponible, sin credenciales reales)

### Paso 1 — Instalar las nuevas dependencias

```bash
pip install -r requirements.txt -r requirements-dev.txt
```

**Esperado**: `httpx` y `PyJWT` instalados en las versiones pineadas.

### Paso 2 — Ejecutar los tests del conector

```bash
pytest tests/unit/connectors/test_ing.py -v
```

**Esperado**: Todos los tests pasan. Ninguno realiza una llamada de red real
(verificable: los tests no requieren conectividad — pueden correr con la red
desconectada).

### Paso 3 — Verificar el escenario de éxito con página única (referencia)

```python
from datetime import date
import httpx
from banking.connectors.ing import IngConnector

def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "transactions": [
            {
                "status": "BOOK",
                "booking_date": "2026-08-15",
                "transaction_amount": {"amount": "42.50", "currency": "EUR"},
                "credit_debit_indicator": "CRDT",
                "remittance_information": "Nómina",
            },
            {
                "status": "PDNG",
                "booking_date": "2026-08-16",
                "transaction_amount": {"amount": "10.00", "currency": "EUR"},
                "credit_debit_indicator": "DBIT",
                "remittance_information": "Pendiente, debe ignorarse",
            },
        ],
        "continuation_key": None,
    })

client = httpx.Client(transport=httpx.MockTransport(handler))
connector = IngConnector(http_client=client)
result = connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))

assert len(result) == 1  # la PDNG se descarta
assert result[0].amount > 0  # CRDT → positivo
print("OK — filtrado y normalización correctos")
```

**Esperado**: `OK — filtrado y normalización correctos`.

### Paso 4 — Verificar la detección de sesión inutilizable (referencia)

```python
import httpx
from banking.connectors.ing import IngConnector, ReauthorizationRequiredError

def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(403, json={"error": "forbidden"})

client = httpx.Client(transport=httpx.MockTransport(handler))
connector = IngConnector(http_client=client)
try:
    connector.fetch_transactions(date(2026, 8, 1), date(2026, 8, 31))
    print("FAIL — debería haber lanzado ReauthorizationRequiredError")
except ReauthorizationRequiredError as e:
    print(f"OK — {e}")
```

**Esperado**: Un mensaje que menciona explícitamente la necesidad de
re-autorización manual por navegador. El mensaje no debe contener la clave
privada, el JWT ni el `session_id`.

### Paso 5 — Verificar la detección del límite de peticiones (referencia)

Igual que el Paso 4, pero con `httpx.Response(429, ...)` y capturando
`RateLimitExceededError`.

**Esperado**: Mensaje que menciona explícitamente el límite diario de 4
peticiones/cuenta.

---

## Parte B — Validación manual con sesión PSD2 real (opcional, solo local)

> Esta parte requiere una sesión PSD2 ya autorizada para una cuenta ING
> España real (flujo de consentimiento por navegador ya completado
> previamente, fuera del alcance de este conector). **No se ejecuta en CI.**

### Paso 6 — Configurar el `session_id` real

```bash
python -m banking secrets set ENABLE_BANKING_SESSION_ID <tu-session-id-real>
```

### Paso 7 — Ejecutar una recuperación real de un rango pequeño

```python
from datetime import date, timedelta
from banking.connectors.ing import IngConnector

connector = IngConnector()  # sin http_client → cliente real
today = date.today()
result = connector.fetch_transactions(today - timedelta(days=7), today)
print(f"Recuperadas {len(result)} transacciones BOOK")
```

**Esperado**: La invocación completa sin error, o lanza
`ReauthorizationRequiredError`/`RateLimitExceededError` con un mensaje claro
si la sesión ha expirado o se agotó la cuota diaria (recordar el límite de 4
peticiones/cuenta/día — no repetir esta prueba más de una vez al día).

> Este paso valida el objetivo original de la funcionalidad: confirmar que
> Enable Banking soporta ING España en la práctica.

---

## Checklist de validación

| Paso | Descripción | Pasa cuando |
|------|-------------|-------------|
| 1 | Instalación de dependencias nuevas | `pip install` sale con código 0 |
| 2 | Suite de tests del conector | Todos los tests pasan, sin red real |
| 3 | Filtrado y normalización | Solo `BOOK` presente, signo correcto |
| 4 | Sesión inutilizable | `ReauthorizationRequiredError` con mensaje claro, sin secretos |
| 5 | Límite de peticiones | `RateLimitExceededError` con mensaje claro |
| 6-7 | Validación manual (opcional) | Recuperación real exitosa o error claro y esperado |

---

## Notas

- La Parte A es la que se ejecuta en CI (`ci.yml`, IT1) como parte de
  `pytest tests/`.
- La Parte B es manual, local, y consume cuota real de la API — no
  automatizar ni incluir en CI (Principio III).
