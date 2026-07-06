# Contract: CLI Interface

**Feature**: Project Skeleton and CI Pipeline (IT1)
**Type**: CLI command schema
**Date**: 2026-07-05

---

## Entry Point

```
python -m banking [COMMAND] [SUBCOMMAND] [ARGS...]
```

Invoked with no arguments → prints usage and exits with code **0**.

---

## Commands

### `banking` (no arguments)

```
Usage: banking <command>

Commands:
  secrets   Manage encrypted configuration secrets

Run 'banking <command> --help' for more information.
```

**Exit code**: 0

---

### `banking secrets set KEY VALUE`

Encrypts `VALUE` with the MasterKey and writes the result to the SecretStore
under `KEY`.

**Arguments**:

| Argument | Type | Constraints |
|----------|------|-------------|
| `KEY` | string | Required. Pattern: `[A-Z][A-Z0-9_]*` (uppercase env var name) |
| `VALUE` | string | Required. The plaintext value to encrypt. Whitespace allowed. |

**Preconditions**:
- `BANKING_MASTER_KEY` must be set in the OS environment (64 hex chars)

**Postconditions**:
- `.env` file contains `KEY=enc:<blob>` (created if absent, updated if present)
- Plaintext `VALUE` does not appear in any file or in standard output

**stdout on success**: (empty — no confirmation output to avoid leaking values
into shell history or terminal logs)

**Exit codes**:

| Code | Condition |
|------|-----------|
| 0 | Success |
| 1 | `BANKING_MASTER_KEY` is absent or malformed |
| 2 | `.env` file cannot be read or written (permissions, disk full, etc.) |

**Error output format** (stderr):
```
ERROR: <human-readable message>
```

---

### `banking secrets set` (missing arguments)

**stdout**:
```
Usage: banking secrets set KEY VALUE

Encrypt VALUE and store it in the SecretStore under KEY.
```

**Exit code**: 1

---

## Invariants

1. `banking` never reads sensitive values from `argv` beyond what the user
   explicitly provides via `secrets set`. No auto-discovery of env vars.
2. Exit code 0 always means the operation completed successfully and the
   system is in a consistent state.
3. All error messages are written to **stderr**, never stdout.
4. The command does not print the plaintext or encrypted value to stdout
   under any normal execution path.
