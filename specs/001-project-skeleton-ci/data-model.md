# Data Model: Project Skeleton and CI Pipeline

**Phase 1 output for**: `specs/001-project-skeleton-ci/plan.md`
**Date**: 2026-07-05

IT1 introduces two entities: **MasterKey** and **SecretStore**. No business
entities are introduced in this iteration.

---

## Entity 1: MasterKey

**Purpose**: The operator-held secret that encrypts and decrypts all sensitive
values in the SecretStore.

| Field | Type | Constraints |
|-------|------|-------------|
| `raw_bytes` | `bytes` | Exactly 32 bytes (256-bit AES key) |
| `env_var_name` | `str` | Always `BANKING_MASTER_KEY` |
| `hex_representation` | `str` | 64 lowercase hexadecimal characters |

**Source**: Loaded exclusively from the OS environment variable `BANKING_MASTER_KEY`.
Never from any file.

**Validation rules**:
- `BANKING_MASTER_KEY` must be present in the OS environment. If absent → immediate
  `ConfigurationError` with message: `"BANKING_MASTER_KEY environment variable is not set.
  Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""`.
- `BANKING_MASTER_KEY` must be exactly 64 hexadecimal characters. If malformed →
  `ConfigurationError` with message: `"BANKING_MASTER_KEY is invalid. Expected 64 hex
  characters (32 bytes), got N characters."`.
- These are the only two failure modes. They are distinct and produce distinct messages.

**State**: Stateless. Created at load time, used for encrypt/decrypt operations,
not stored anywhere.

---

## Entity 2: SecretEntry

**Purpose**: A single encrypted key-value pair stored in the SecretStore.

| Field | Type | Constraints |
|-------|------|-------------|
| `key` | `str` | Uppercase, alphanumeric + underscore; matches `[A-Z][A-Z0-9_]*` |
| `encrypted_blob` | `str` | `enc:` prefix followed by base64url-encoded bytes |
| `nonce` | `bytes` | Exactly 12 bytes (first 12 bytes of decoded blob) |
| `ciphertext_with_tag` | `bytes` | Remaining bytes (AES-256-GCM output, includes 16-byte tag) |

**Encryption invariant**: The same plaintext encrypted twice produces different
blobs (nonce is random per-call). Decryption is deterministic given the same
blob and key.

**Storage format** (in the `.env` file):
```
KEY_NAME=enc:<base64url_nonce_and_ciphertext>
```

Example (illustrative only — not a real key):
```
ENABLE_BANKING_SESSION_ID=enc:aGVsbG8gd29ybGQhISE=
```

---

## Entity 3: SecretStore

**Purpose**: The `.env` file on disk that holds all SecretEntry records plus
any non-sensitive plaintext configuration values.

| Field | Type | Constraints |
|-------|------|-------------|
| `file_path` | `Path` | Defaults to `.env` at repository root; configurable |
| `entries` | `dict[str, str]` | Raw key → raw value (encrypted or plaintext) |

**File format**: Standard dotenv (`KEY=VALUE`, one per line). Comments (`#`)
and blank lines are preserved on write.

**Invariants**:
- `.env` is permanently excluded from version control (`.gitignore`)
- `.env.example` is committed with placeholder values only (no `enc:` blobs)
- Encrypted values always carry the `enc:` prefix; plaintext values do not
- `SecretStore.get(key)` returns the plaintext: decrypts if `enc:` prefix,
  returns as-is otherwise
- `SecretStore.set(key, plaintext)` always writes encrypted form (`enc:` prefix)

**Absence handling**:
- If `.env` does not exist → `SecretStore` loads with empty entries (not an error;
  acceptable on fresh clone before any secrets are configured)
- If a specific key is absent → `SecretStore.get(key)` raises `KeyError` with
  the key name

---

## Entity 4: EnableBankingConfigDirectory (placeholder)

**Purpose**: Documents the directory structure required by IT2. IT1 only ensures
`quickstart.md` instructs the developer to create it manually.

| Field | Type | Notes |
|-------|------|-------|
| `base_path` | `Path` | `~/.config/banca-personal/` |
| `config_file` | `Path` | `~/.config/banca-personal/eb-config.json` |
| `private_key` | `Path` | `~/.config/banca-personal/private.pem` |

**`eb-config.json` structure** (placeholder only — validated in IT2):
```json
{
  "app_id": "<your-enable-banking-app-id>",
  "private_key_path": "~/.config/banca-personal/private.pem"
}
```

**IT1 responsibility**: Document this structure in `quickstart.md` and verify
(via acceptance scenario US1-5) that the developer creates the directory and
placeholder file while following setup.

**IT2 responsibility**: Validate this file, load the RSA key, and use both to
authenticate with Enable Banking.
