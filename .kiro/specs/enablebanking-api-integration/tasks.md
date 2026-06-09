# Implementation Plan: Enable Banking API Integration

## Overview

Pipeline Python desatendida que conecta con ING, Sabadell, Revolut y MyInvestor via Enable Banking API, normaliza movimientos del día anterior y los persiste en archivos Excel mensuales. Se implementa en seis fases incrementales: infraestructura base → componentes de soporte → fetcher → normalizer → excel writer → orquestador y CI.

## Tasks

- [x] 1. Configurar estructura del proyecto e infraestructura base
  - Crear la estructura de directorios: `src/`, `tests/unit/`, `tests/property/`, `logs/`
  - Crear `requirements.txt` con dependencias pinadas: `requests`, `tenacity`, `openpyxl`
  - Crear `requirements-dev.txt` con dependencias pinadas: `pytest`, `hypothesis`, `responses`
  - Crear `src/__init__.py` y `tests/__init__.py` vacíos
  - Crear `.env.example` documentando las variables de entorno requeridas (sin valores reales): `ENABLEBANKING_CLIENT_ID`, `ENABLEBANKING_CLIENT_SECRET`, `{BANK}_ACCESS_TOKEN`, `{BANK}_REFRESH_TOKEN` para cada banco
  - Añadir `logs/` y `*.xlsx` al `.gitignore`
  - _Requirements: 6.5, 7.1_

- [x] 2. Implementar excepciones personalizadas y modelos de datos
  - [x] 2.1 Crear `src/exceptions.py` con `BankAuthError`, `BankAPIError`, `MissingSecretError` y `ExcelWriteError`
    - Cada excepción hereda de `Exception` y acepta un mensaje descriptivo
    - _Requirements: 1.5, 2.4, 7.3_
  - [x] 2.2 Crear `src/normalizer.py` con el dataclass `NormalizedTransaction`
    - `frozen=True`, campos: `fecha: date`, `importe: Decimal`, `concepto: str`, `banco: str`
    - Importar desde `decimal`, `datetime`
    - _Requirements: 3.1, 3.2_
  - [ ]* 2.3 Escribir tests unitarios para `NormalizedTransaction`
    - Verificar inmutabilidad (frozen), tipos de campo y valor por defecto de `concepto`
    - _Requirements: 3.1, 3.4_

- [x] 3. Implementar `SecretStore`
  - [x] 3.1 Crear `src/secret_store.py` con la clase `SecretStore`
    - Método `get(key)`: lee variable de entorno; lanza `MissingSecretError` si ausente o vacía
    - Método `set(key, value)`: actualiza `os.environ` y escribe a `$GITHUB_ENV` si la variable está definida
    - Ningún valor de credencial debe aparecer en mensajes de excepción
    - _Requirements: 1.3, 6.5, 7.1, 7.3_
  - [ ]* 3.2 Escribir tests unitarios para `SecretStore`
    - `get` con variable presente → devuelve valor
    - `get` con variable ausente → lanza `MissingSecretError`
    - `get` con variable vacía → lanza `MissingSecretError`
    - `set` actualiza `os.environ` correctamente
    - Verificar que el mensaje de `MissingSecretError` no contiene el valor esperado
    - _Requirements: 7.1, 7.3_

- [x] 4. Implementar `ProcessLogger`
  - [x] 4.1 Crear `src/logger.py` con la clase `ProcessLogger`
    - Constructor recibe `log_dir: Path`; determina el nombre del fichero como `execution_{YYYY_MM_DD}.log` según la fecha de ejecución
    - Abre el fichero en modo append (`"a"`); crea el directorio si no existe
    - Métodos `info()`, `warning()`, `error()` con firma `(component: str, bank: str | None, message: str) -> None`
    - Formato de línea: `{ISO8601_TIMESTAMP} [{LEVEL}]    {COMPONENT} [{BANK}|global] {MESSAGE}`
    - Fallback a `stderr` si la escritura al fichero falla; continúa silenciosamente si `stderr` también falla
    - Nunca incluir valores de credenciales/tokens en ninguna entrada de log
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.7_
  - [ ]* 4.2 Escribir test de propiedad para `ProcessLogger` — Property 14
    - **Property 14: Las entradas de log contienen todos los campos requeridos en todos los niveles**
    - **Validates: Requirements 8.2, 8.3, 8.4**
  - [ ]* 4.3 Escribir test de propiedad para `ProcessLogger` — Property 15
    - **Property 15: El fichero de log se abre en modo append y preserva entradas previas**
    - **Validates: Requirements 8.1**
  - [ ]* 4.4 Escribir test de propiedad para `ProcessLogger` — Property 13
    - **Property 13: Ningún secreto ni credencial aparece en texto plano en los logs**
    - **Validates: Requirements 7.3, 7.4, 8.4**
  - [ ]* 4.5 Escribir tests unitarios para `ProcessLogger`
    - Formato correcto de línea para cada nivel (`INFO`, `WARNING`, `ERROR`)
    - Fallback a `stderr` cuando la escritura al fichero falla
    - Log con credencial pasada como mensaje → credencial no aparece en texto plano
    - _Requirements: 8.2, 8.3, 8.4, 8.7_

- [ ] 5. Checkpoint — Verificar infraestructura base
  - Asegurarse de que todos los tests pasan hasta este punto. Consultar al usuario si surgen dudas.

- [x] 6. Implementar `DataNormalizer`
  - [x] 6.1 Implementar el método `normalize()` en `src/normalizer.py`
    - Mapear `booking_date` (fallback a `value_date`) → `fecha: date`
    - Mapear `transaction_amount.amount` → `importe: Decimal` (preservar signo)
    - Mapear `remittance_information` → `concepto: str` (cadena vacía si ausente)
    - Usar el parámetro `bank` → `banco: str`
    - Excluir movimientos con `fecha`, `importe` o `banco` ausentes/nulos; registrar `WARNING` via `ProcessLogger`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_
  - [ ]* 6.2 Escribir test de propiedad para `DataNormalizer` — Property 4
    - **Property 4: Mapeo completo de campos normalizados**
    - **Validates: Requirements 3.1, 3.4, 3.5**
  - [ ]* 6.3 Escribir test de propiedad para `DataNormalizer` — Property 5
    - **Property 5: Round-trip de precisión decimal sin pérdida**
    - **Validates: Requirements 3.2**
  - [ ]* 6.4 Escribir test de propiedad para `DataNormalizer` — Property 6
    - **Property 6: Movimientos con campos obligatorios ausentes son excluidos**
    - **Validates: Requirements 3.3**
  - [ ]* 6.5 Escribir tests unitarios para `DataNormalizer`
    - `concepto` ausente → campo vacío (sin error)
    - `fecha` ausente → movimiento excluido, log WARNING
    - `importe` negativo → signo preservado
    - Lista vacía de transacciones → lista vacía devuelta
    - Múltiples movimientos con campos mixtos → solo los válidos en el resultado
    - _Requirements: 3.1, 3.3, 3.4, 3.5_

- [x] 7. Implementar `TransactionFetcher`
  - [x] 7.1 Crear `src/fetcher.py` con la clase `TransactionFetcher`
    - Constructor: `__init__(self, bank: str, secret_store: SecretStore)`
    - Leer `{BANK}_ACCESS_TOKEN` y `{BANK}_REFRESH_TOKEN` desde `SecretStore`
    - Implementar `fetch_transactions(date_from: date, date_to: date) -> list[dict]`
    - Llamar al endpoint de transacciones de la Enable Banking API con `date_from` y `date_to`
    - Todas las URLs deben comenzar con `https://`; nunca usar `http://`
    - _Requirements: 1.1, 2.1, 2.2, 7.1, 7.2_
  - [x] 7.2 Implementar lógica de renovación automática de Access Token
    - Detectar respuesta 401 del endpoint de transacciones
    - Usar `{BANK}_REFRESH_TOKEN` para obtener nuevo Access Token via POST al endpoint OAuth
    - Almacenar el nuevo Access Token en `SecretStore`
    - Reintentar la llamada original con el nuevo token
    - Si el Refresh Token es inválido/expirado → lanzar `BankAuthError`
    - _Requirements: 1.4, 1.5_
  - [x] 7.3 Implementar lógica de reintento con exponential backoff usando `tenacity`
    - Aplicar `@retry` en errores de red y respuestas HTTP 5xx / 429
    - Configuración: máximo 5 intentos, backoff inicial 1 s, factor 2, jitter aleatorio
    - Errores 4xx de autenticación (401, 403) → no reintentar; elevar como `BankAuthError`
    - Al agotar reintentos → lanzar `BankAPIError`
    - _Requirements: 1.6, 2.4_
  - [x] 7.4 Implementar cálculo de fecha del día anterior en `src/fetcher.py` o utilidad en `src/utils.py`
    - Función `get_yesterday(today: date) -> date` que devuelve `today - timedelta(days=1)`
    - _Requirements: 2.1_
  - [ ]* 7.5 Escribir test de propiedad para `TransactionFetcher` — Property 1
    - **Property 1: Renovación automática de Access Token expirado**
    - **Validates: Requirements 1.4**
  - [ ]* 7.6 Escribir test de propiedad para `TransactionFetcher` — Property 3
    - **Property 3: Cálculo correcto de la fecha del día anterior**
    - **Validates: Requirements 2.1**
  - [ ]* 7.7 Escribir test de propiedad para `TransactionFetcher` — Property 12
    - **Property 12: Todas las llamadas a la API usan conexiones HTTPS**
    - **Validates: Requirements 7.2**
  - [ ]* 7.8 Escribir tests unitarios para `TransactionFetcher`
    - Token expirado → refresh automático (mock de API con `responses`)
    - Refresh token inválido → `BankAuthError`
    - API devuelve 500 → reintento con backoff y finalmente `BankAPIError`
    - API devuelve 429 → reintento con backoff
    - API devuelve 0 transacciones → lista vacía + log WARNING
    - Verificar que ningún token aparece en texto plano en los logs
    - _Requirements: 1.4, 1.5, 1.6, 2.4, 2.6, 7.2, 7.4_

- [ ] 8. Checkpoint — Verificar componentes individuales
  - Asegurarse de que todos los tests pasan hasta este punto. Consultar al usuario si surgen dudas.

- [x] 9. Implementar `ExcelWriter`
  - [x] 9.1 Crear `src/excel_writer.py` con la clase `ExcelWriter`
    - Constructor: `__init__(self, output_dir: Path)`
    - Implementar `write(transactions: list[NormalizedTransaction], enable_summary: bool = False) -> None`
    - Determinar el fichero `movimientos_{YYYY_MM}.xlsx` a partir de `fecha` de cada movimiento
    - Si el fichero no existe, crearlo con hoja `Movimientos` y cabeceras: `Fecha`, `Importe`, `Concepto`, `Banco`, `Estado`
    - _Requirements: 4.1, 4.2_
  - [x] 9.2 Implementar lógica de deduplicación y marcado de estado
    - Al abrir el workbook existente, construir un `set` de tuplas `(fecha, importe, concepto, banco)` a partir de las filas existentes
    - Para cada movimiento nuevo: `Estado = DUPLICATE` si la clave ya existe; `Estado = NORMAL` si es nueva
    - Conservar todas las filas existentes (nunca eliminar ni sobrescribir)
    - _Requirements: 4.3, 4.4_
  - [x] 9.3 Implementar guardado seguro del workbook
    - Guardar y cerrar el fichero solo si toda la escritura completó sin errores
    - Si la escritura fue interrumpida → no guardar; lanzar `ExcelWriteError`
    - _Requirements: 4.5_
  - [x] 9.4 Implementar hoja `Resumen` opcional
    - Si `enable_summary=True`: crear o reemplazar la hoja `Resumen` con cabeceras `Banco`, `Total Ingresos`, `Total Gastos`
    - Calcular totales acumulados de todos los movimientos del mes (previos + nuevos) usando `Decimal`
    - Ingresos: suma de `importe > 0`; Gastos: suma de `importe < 0`; aritmética `Decimal` exacta
    - _Requirements: 5.1, 5.2, 5.3_
  - [ ]* 9.5 Escribir test de propiedad para `ExcelWriter` — Property 7
    - **Property 7: Inserción en el archivo mensual correcto y creación de cabeceras**
    - **Validates: Requirements 4.1, 4.2**
  - [ ]* 9.6 Escribir test de propiedad para `ExcelWriter` — Property 8
    - **Property 8: La escritura en modo append preserva todas las filas existentes**
    - **Validates: Requirements 4.4**
  - [ ]* 9.7 Escribir test de propiedad para `ExcelWriter` — Property 9
    - **Property 9: Detección y marcado consistente de duplicados**
    - **Validates: Requirements 4.3**
  - [ ]* 9.8 Escribir test de propiedad para `ExcelWriter` — Property 10
    - **Property 10: Hoja Resumen refleja todos los movimientos acumulados del mes**
    - **Validates: Requirements 5.1, 5.2, 5.3**
  - [ ]* 9.9 Escribir tests unitarios para `ExcelWriter`
    - Crear Excel nuevo → cabeceras correctas presentes
    - Añadir movimientos a Excel existente → filas previas inalteradas
    - Movimiento duplicado → `Estado = DUPLICATE`; movimiento nuevo → `Estado = NORMAL`
    - Escritura interrumpida (excepción simulada) → fichero no guardado
    - `enable_summary=True` → hoja `Resumen` creada con totales correctos en `Decimal`
    - Movimientos de meses distintos → insertados en ficheros `.xlsx` distintos
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 5.1, 5.2, 5.3_

- [x] 10. Implementar `main.py` — Orquestador
  - [ ] 10.1 Crear `main.py` en la raíz del proyecto
    - Instanciar `ProcessLogger`, `SecretStore`, `DataNormalizer`, `ExcelWriter`
    - Definir `BANKS = ["ING", "Sabadell", "Revolut", "MyInvestor"]`
    - Calcular `yesterday = get_yesterday(date.today())`
    - Iterar sobre cada banco: instanciar `TransactionFetcher`, llamar `fetch_transactions`, `normalize`, `write`
    - Capturar excepciones por banco (`BankAuthError`, `BankAPIError`, `MissingSecretError`, `ExcelWriteError`, `Exception`): registrar `ERROR`, marcar `failed = True`, continuar con el siguiente banco
    - Registrar resultado final (`success` / `failure`) en el log
    - Devolver código de salida `0` si todos los bancos procesados sin error, `1` si alguno falló
    - _Requirements: 2.3, 2.5, 6.1, 6.2, 6.3, 6.4_
  - [ ]* 10.2 Escribir test de propiedad para el orquestador — Property 2
    - **Property 2: Aislamiento de fallos por entidad bancaria**
    - **Validates: Requirements 1.5, 2.4**
  - [ ]* 10.3 Escribir test de propiedad para el orquestador — Property 11
    - **Property 11: El código de salida refleja el resultado global del flujo**
    - **Validates: Requirements 2.5, 6.3**
  - [ ]* 10.4 Escribir tests unitarios para `main.py`
    - Todos los bancos exitosos → código de salida `0`
    - Un banco con `BankAuthError` → código de salida `1`, otros bancos procesados
    - Un banco con `BankAPIError` → código de salida `1`, otros bancos procesados
    - Log contiene entrada de resultado final `success` / `failure`
    - _Requirements: 2.4, 2.5, 6.3, 6.4_

- [x] 11. Configurar GitHub Actions
  - [x] 11.1 Crear `.github/workflows/daily_fetch.yml`
    - Trigger: `schedule` cron `'5 0 * * *'` (00:05 UTC)
    - Job único con pasos secuenciales: checkout → setup Python 3.12 → install dependencies → run `main.py`
    - Leer todas las credenciales exclusivamente desde GitHub Actions Secrets (variables de entorno)
    - Marcar el job como `failure` si `main.py` devuelve código de salida distinto de 0
    - Publicar el fichero de log diario como artefacto con retención de 90 días (incluso si está vacío o ausente)
    - Publicar los ficheros `.xlsx` generados como artefactos
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 8.6_
  - [x] 11.2 Crear `.github/workflows/tests.yml`
    - Trigger: `push` y `pull_request`
    - Job: checkout → setup Python 3.12 → `pip install -r requirements-dev.txt` → `pytest tests/ -v`
    - _Requirements: 6.2_

- [ ] 12. Checkpoint final — Verificar integración completa
  - Asegurarse de que todos los tests pasan y el flujo completo funciona end-to-end con mocks. Consultar al usuario si surgen dudas.

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad
- Los tests de propiedad usan `hypothesis` con `@settings(max_examples=100)`
- Los tests unitarios mockean la Enable Banking API con `unittest.mock.patch` y la librería `responses`; no se realizan llamadas reales a la API
- Todos los importes monetarios usan `decimal.Decimal`; nunca `float`
- Ningún secreto, token ni credencial debe aparecer en código versionado, logs ni mensajes de excepción

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1", "2.2"] },
    { "id": 1, "tasks": ["2.3", "3.1", "4.1"] },
    { "id": 2, "tasks": ["3.2", "4.2", "4.3", "4.4", "4.5"] },
    { "id": 3, "tasks": ["6.1", "7.1", "7.4"] },
    { "id": 4, "tasks": ["6.2", "6.3", "6.4", "6.5", "7.2", "7.3"] },
    { "id": 5, "tasks": ["7.5", "7.6", "7.7", "7.8", "9.1"] },
    { "id": 6, "tasks": ["9.2", "9.3", "9.4"] },
    { "id": 7, "tasks": ["9.5", "9.6", "9.7", "9.8", "9.9", "10.1"] },
    { "id": 8, "tasks": ["10.2", "10.3", "10.4", "11.1", "11.2"] }
  ]
}
```
