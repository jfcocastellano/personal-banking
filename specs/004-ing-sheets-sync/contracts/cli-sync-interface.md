# Contrato: Interfaz de Línea de Comandos `banking sync`

**Funcionalidad**: Pipeline de Sincronización ING → Google Sheets (IT4)
**Tipo**: Interfaz CLI (punto de entrada del sistema)
**Fecha**: 2026-08-09

---

## Comando

```
python -m banking sync
```

Sin argumentos ni flags (FR-001; Suposición del spec: sin modo `--dry-run`
en esta iteración).

---

## Salida en éxito (stdout, código de salida `0`)

Una sola línea con, como mínimo: nombre del banco, número de movimientos
escritos, nombre de la pestaña destino, duración total (FR-006). Ejemplo
de referencia (formato exacto no normativo, contenido sí):

```
Sincronización completada: ING España — 12 movimientos escritos en la pestaña 2026-08 (3.42s)
```

## Salida en fallo por ING (stderr, código de salida `1`)

```
ERROR (ING): <motivo, tal como lo reporta la excepción original de IngConnector>
```

## Salida en fallo por Google Sheets (stderr, código de salida `2`)

```
ERROR (Sheets): <motivo, tal como lo reporta la excepción original de SheetsWriter o del SecretStore>
```

---

## Códigos de salida

| Código | Condición |
|--------|-----------|
| `0` | Sincronización completada (incluye el caso de 0 movimientos, FR-009) |
| `1` | Fallo al obtener movimientos de ING (`IngSyncError`) |
| `2` | Fallo al escribir en Google Sheets, incluida la lectura de `GOOGLE_SHEET_ID` (`SheetsSyncError`) |

Decidido en `/speckit-clarify` (FR-007/FR-008) — permite a un futuro
scheduler (IT7) o notificador por email (IT6) reaccionar por código sin
parsear el mensaje.

---

## Precondiciones de configuración (leídas internamente, no son argumentos)

- `BANKING_MASTER_KEY` (variable de entorno, IT1)
- `SecretStore.get("ENABLE_BANKING_SESSION_ID")` (IT2)
- `~/.config/banca-personal/eb-config.json` + clave privada RSA (IT2)
- `SecretStore.get("GOOGLE_SHEETS_CREDENTIALS")` (IT3)
- `SecretStore.get("GOOGLE_SHEET_ID")` (IT1, consumido de verdad por primera vez en esta funcionalidad)

Si cualquiera de estas falta o es inválida, el comando falla con el código
de salida correspondiente (`1` si el problema es de ING, `2` si es de
Sheets — la lectura de `GOOGLE_SHEET_ID` cuenta como `2`).
