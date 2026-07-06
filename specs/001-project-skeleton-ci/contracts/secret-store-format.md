# Contract: SecretStore File Format

**Feature**: Project Skeleton and CI Pipeline (IT1)
**Type**: File format specification
**Date**: 2026-07-05

---

## File location

Default: `.env` at the repository root.

This file is **always excluded from version control** via `.gitignore`. It must
never appear in any committed changeset.

---

## File format

Standard [dotenv](https://www.dotenv.org/docs/security/env) format:
one `KEY=VALUE` pair per line, UTF-8 encoding, Unix line endings (`\n`).

```
# Comments are preserved
KEY_NAME=value
ANOTHER_KEY=enc:<base64url_blob>
```

**Rules**:
- Lines starting with `#` are comments; preserved on read and write
- Blank lines are preserved
- Keys are case-sensitive; by convention `UPPER_SNAKE_CASE`
- Values may not contain unquoted newlines

---

## Encrypted value format

Encrypted values have the prefix `enc:` followed immediately by a base64url-encoded
binary blob (no padding required, URL-safe alphabet):

```
KEY=enc:<base64url(nonce || ciphertext_with_tag)>
```

**Binary layout of the decoded blob**:

```
[ nonce: 12 bytes ][ ciphertext + GCM tag: variable ]
```

| Component | Size | Description |
|-----------|------|-------------|
| `nonce` | 12 bytes | Random 96-bit nonce, unique per encryption call |
| `ciphertext` | variable | AES-256-GCM encrypted plaintext |
| `tag` | 16 bytes (appended by GCM) | Authentication tag (integrity check) |

**Algorithm**: AES-256-GCM (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`)

**Key**: 32 bytes (256-bit), loaded from `BANKING_MASTER_KEY` environment variable
(64 hex characters decoded to bytes).

**Associated data**: `None` (no AAD used)

---

## Plaintext value format

Values without the `enc:` prefix are stored and returned as-is. These are
non-sensitive configuration values (e.g., `LOG_LEVEL=INFO`).

**Note**: The `secrets set` command always writes encrypted values. Plaintext
values are only introduced by manually editing `.env` (documented in quickstart.md
as allowed for non-sensitive config).

---

## `.env.example`

The committed `.env.example` file documents expected keys with placeholder values:

```
# Enable Banking
ENABLE_BANKING_SESSION_ID=enc:placeholder
ENABLE_BANKING_APP_ID=enc:placeholder

# Google Sheets
GOOGLE_SHEETS_CREDENTIALS=enc:placeholder
GOOGLE_SHEET_ID=enc:placeholder

# Gmail SMTP
GMAIL_SMTP_PASSWORD=enc:placeholder
GMAIL_FROM=enc:placeholder
GMAIL_TO=enc:placeholder

# Non-sensitive
LOG_LEVEL=INFO
```

**Rules for `.env.example`**:
- No real keys or real encrypted blobs — only the literal string `enc:placeholder`
- All keys that the application reads must appear here
- New keys added in future iterations are added here before the spec is closed

---

## Decryption failure modes

| Failure | Cause | Error message |
|---------|-------|---------------|
| Missing MasterKey | `BANKING_MASTER_KEY` not set | `"BANKING_MASTER_KEY environment variable is not set."` |
| Malformed MasterKey | Not 64 hex chars | `"BANKING_MASTER_KEY is invalid. Expected 64 hex characters (32 bytes)."` |
| Authentication failure | Wrong key, tampered blob | `"Decryption failed for key '<KEY>'. The MasterKey may be incorrect or the stored value is corrupted."` |
| Malformed blob | Invalid base64 or truncated nonce | `"Stored value for key '<KEY>' is malformed and cannot be decoded."` |
