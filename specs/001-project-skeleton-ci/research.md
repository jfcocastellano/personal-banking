# Research: Project Skeleton and CI Pipeline

**Phase 0 output for**: `specs/001-project-skeleton-ci/plan.md`
**Date**: 2026-07-05

---

## Decision 1: AES-256 encryption implementation

**Decision**: Use `cryptography.hazmat.primitives.ciphers.aead.AESGCM` with a
256-bit (32-byte) key.

**Rationale**: The Constitution explicitly requires AES-256. `cryptography.fernet.Fernet`
(the high-level API) uses AES-128-CBC — it does not satisfy this requirement.
`AESGCM` from the hazmat layer provides authenticated encryption (AES-256-GCM)
which combines encryption and integrity in a single operation, preventing
tampering with the ciphertext.

**Mechanics**:
- Key: 32 random bytes (256-bit), derived from the MasterKey environment variable
- Nonce: 12 random bytes (96-bit) generated per encryption operation; never reused
- Ciphertext includes a 16-byte authentication tag (GCM append behaviour)
- Storage format: `base64url(nonce + ciphertext_with_tag)` → compact, URL-safe

**Alternatives considered**:

| Option | Why rejected |
|--------|-------------|
| `Fernet` | AES-128-CBC, not AES-256; does not meet Constitution requirement |
| AES-256-CBC (manual) | No built-in authentication; requires separate HMAC; error-prone |
| PyNaCl / libsodium | Adds a second crypto dependency; `cryptography` already required |
| `secrets.token_bytes` + custom | Reinventing authenticated encryption; high bug risk |

---

## Decision 2: MasterKey format and derivation

**Decision**: The `BANKING_MASTER_KEY` environment variable holds a 64-character
lowercase hex string (32 raw bytes). No KDF (Key Derivation Function) is used.

**Rationale**: The MasterKey is generated once by the developer (`secrets.token_hex(32)`)
and stored as a system env var. It never changes and is not a human-memorised
password. A KDF (like PBKDF2 or Argon2) adds cost and a salt-storage problem
without benefit when the key is already a high-entropy random value. The application
validates the env var is exactly 64 hex characters at startup and fails immediately
with a clear error if absent or malformed.

**Key generation** (documented in quickstart.md):
```python
python -c "import secrets; print(secrets.token_hex(32))"
```

**Alternatives considered**:

| Option | Why rejected |
|--------|-------------|
| PBKDF2 / Argon2 from password | Adds salt storage; no benefit for random keys |
| 128-bit key (32 hex chars) | Does not satisfy AES-256 requirement |
| UUID v4 as key | Only 122 bits of entropy; non-standard for crypto keys |

---

## Decision 3: SecretStore file format

**Decision**: `.env` file in standard dotenv format. Encrypted values are stored
with the prefix `enc:` followed by a base64url-encoded blob. Plaintext values
(non-sensitive config) are stored without prefix.

**Format**:
```
# Non-sensitive config — stored plaintext
LOG_LEVEL=INFO

# Sensitive values — stored encrypted
ENABLE_BANKING_SESSION_ID=enc:dGVzdA==...
GOOGLE_SHEETS_CREDENTIALS=enc:dGVzdA==...
```

**Rationale**: `python-dotenv` loads the file transparently; the `banking`
application reads all values and decrypts `enc:` prefixed ones automatically.
The file is excluded from git via `.gitignore`. An `.env.example` committed to
the repo documents the expected keys with `enc:placeholder` values.

**Reading encrypted values**:
The `SecretStore` class loads the `.env` file, detects `enc:` prefixed values,
decrypts them with the MasterKey, and makes the plaintext available via a
`get(key)` method. The application never accesses `os.environ` for sensitive
values directly — it always goes through `SecretStore`.

**Alternatives considered**:

| Option | Why rejected |
|--------|-------------|
| Pure JSON SecretStore | Breaks dotenv convention; requires separate loader |
| Full encryption of entire file | Prevents viewing non-sensitive config; harder to diff |
| Per-file encryption (e.g., `age`) | External tool dependency; breaks `python-dotenv` integration |

---

## Decision 4: CLI entry point mechanism

**Decision**: `python -m banking` via `src/banking/__main__.py`. No
`console_scripts` in `pyproject.toml`.

**Rationale**: This is a local-run, non-distributed project. `console_scripts`
requires `pip install -e .` which adds an install step to the developer workflow.
`python -m banking` works directly after `pip install -r requirements.txt` with
the repo in `PYTHONPATH` (set by `src/` layout convention or `pip install -e .`
optionally). Simpler onboarding.

**CLI structure** (IT1 scope):
```
python -m banking                     → usage message, exit 0
python -m banking secrets set KEY V  → encrypt V, write to SecretStore
```

**Alternatives considered**:

| Option | Why rejected |
|--------|-------------|
| `console_scripts` / `entry_points` | Requires install step; unnecessary for non-distributed tool |
| `argparse` in top-level script | Not a package; harder to test and import |
| `typer` / `click` framework | Adds dependency; `argparse` stdlib is sufficient for IT1 |

---

## Decision 5: GitHub Actions CI pipeline

**Decision**: Single workflow file `.github/workflows/ci.yml` with one job,
steps executing in fixed sequence: `pip-audit → ruff check → ruff format --check
→ mypy → pytest`.

**Step ordering rationale**:
1. `pip-audit` first: security findings block all subsequent work immediately;
   cheap (no code analysis, just metadata lookup)
2. `ruff check` before `ruff format`: lint errors (import order, unused vars) are
   more likely on a dirty PR; catches errors before style gate
3. `ruff format --check`: style gate; fast
4. `mypy`: slower than ruff; runs after cheap gates pass
5. `pytest`: slowest; runs last, only when all quality gates pass

**Runner**: `ubuntu-latest` with `actions/setup-python@v5` pinned to Python 3.12.

**Trigger**: `push` to `main` branches + `pull_request` to `main`.

**Alternatives considered**:

| Option | Why rejected |
|--------|-------------|
| Matrix (multiple Python versions) | Single supported runtime per spec; unnecessary overhead |
| Separate jobs per gate | Slower; parallel jobs on free tier consume quota; serial fail-fast is sufficient |
| `pre-commit` instead of CI gates | Local hooks can be bypassed; CI gates are mandatory |

---

## Decision 6: `~/.config/banca-personal/` setup

**Decision**: Manual creation step in `quickstart.md`. IT1 does not create
or validate this directory. IT2 (Enable Banking connector) owns it.

**Rationale**: The directory holds an RSA private key (`private.pem`) which is
security-sensitive and developer-specific. Creating it programmatically (e.g.,
via `banking setup` command) would require key generation logic that belongs in IT2.
IT1's responsibility is only to document the directory structure so the developer
creates it manually before IT2 is implemented.

**`eb-config.json` placeholder** (documented in quickstart.md):
```json
{
  "app_id": "<your-enable-banking-app-id>",
  "private_key_path": "~/.config/banca-personal/private.pem"
}
```

This placeholder is not committed to git (it lives outside the repo in `~/.config/`).
