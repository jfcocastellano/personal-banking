# Quickstart: Personal Banking Automation

This guide takes you from a fresh clone to a fully working local environment.
Follow all steps in order. All commands assume a terminal at the repository root.

**Prerequisites**: Python 3.12+ installed. Git available. No prior configuration needed.

---

## Step 1 — Clone and install dependencies

```bash
git clone <repo-url>
cd proyecto-banca-personal

pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install -e .
```

**Expected**: No errors. All packages install at their pinned versions.

---

## Step 2 — Verify the entry point

```bash
python -m banking
```

**Expected output**:
```
Usage: banking <command>

Commands:
  secrets   Manage encrypted configuration secrets

Run 'banking <command> --help' for more information.
```

**Expected exit code**: 0

---

## Step 3 — Verify that a missing MasterKey produces a clear error

```bash
# On Linux/macOS:
unset BANKING_MASTER_KEY
# On Windows PowerShell:
Remove-Item Env:BANKING_MASTER_KEY -ErrorAction SilentlyContinue

python -m banking secrets set TEST_KEY some_value
```

**Expected stderr**:
```
ERROR: BANKING_MASTER_KEY environment variable is not set.
Generate one with: python -c "import secrets; print(secrets.token_hex(32))"
```

**Expected exit code**: 1

---

## Step 4 — Generate and configure the MasterKey

```bash
# Generate a key (outputs 64 hex characters):
python -c "import secrets; print(secrets.token_hex(32))"

# On Linux/macOS — add to your shell profile (.bashrc, .zshrc, etc.):
export BANKING_MASTER_KEY=<paste-your-key-here>

# On Windows PowerShell — set as a permanent user environment variable:
[System.Environment]::SetEnvironmentVariable("BANKING_MASTER_KEY", "<paste-your-key-here>", "User")
```

> ⚠️ **Never write the MasterKey to any file inside the repository.**
> It must exist only in your OS environment.

Confirm it is set:
```bash
# Linux/macOS:
echo $BANKING_MASTER_KEY   # should print 64 hex characters

# Windows PowerShell:
$Env:BANKING_MASTER_KEY    # should print 64 hex characters
```

---

## Step 5 — Write an encrypted secret

```bash
python -m banking secrets set ENABLE_BANKING_SESSION_ID test_placeholder_value
```

**Expected**: No output to stdout. Exit code 0. A `.env` file is created containing:
```
ENABLE_BANKING_SESSION_ID=enc:<base64url blob>
```

Verify:
```bash
# Linux/macOS:
grep ENABLE_BANKING_SESSION_ID .env

# Windows PowerShell:
Select-String -Path .env -Pattern "ENABLE_BANKING_SESSION_ID"
```

The line must start with `enc:` — the plaintext `test_placeholder_value` must not appear.

---

## Step 6 — Verify the SecretStore decrypts correctly

```python
python - << 'EOF'
from banking.config.secret_store import SecretStore
store = SecretStore()
value = store.get("ENABLE_BANKING_SESSION_ID")
assert value == "test_placeholder_value", f"Got: {value!r}"
print("OK — SecretStore round-trip verified")
EOF
```

**Expected output**: `OK — SecretStore round-trip verified`

On Windows, run the equivalent in a Python script or interactive session.

---

## Step 7 — Verify that a wrong MasterKey produces a distinct error

```python
python - << 'EOF'
import secrets, os
os.environ["BANKING_MASTER_KEY"] = secrets.token_hex(32)  # different key
from banking.config.secret_store import SecretStore, DecryptionError
store = SecretStore()
try:
    store.get("ENABLE_BANKING_SESSION_ID")
    print("FAIL — should have raised an error")
except DecryptionError as e:
    print(f"OK — got expected error: {e}")
EOF
```

**Expected**: prints a line containing `MasterKey may be incorrect`.
This is a *different* error from the missing-key error in Step 3.

---

## Step 8 — Run the full CI pipeline locally

```bash
pip-audit -r requirements.txt -r requirements-dev.txt
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest tests/ -v
```

**Expected**: All five commands exit with code 0.

---

## Step 9 — Create the Enable Banking configuration directory

This step prepares your machine for the Enable Banking connector (implemented in IT2).

```bash
# Linux/macOS:
mkdir -p ~/.config/banca-personal
cat > ~/.config/banca-personal/eb-config.json << 'EOF'
{
  "app_id": "<your-enable-banking-app-id>",
  "private_key_path": "~/.config/banca-personal/private.pem"
}
EOF

# Windows PowerShell:
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.config\banca-personal"
@'
{
  "app_id": "<your-enable-banking-app-id>",
  "private_key_path": "~/.config/banca-personal/private.pem"
}
'@ | Set-Content "$env:USERPROFILE\.config\banca-personal\eb-config.json"
```

Verify:
```bash
# Linux/macOS:
cat ~/.config/banca-personal/eb-config.json

# Windows PowerShell:
Get-Content "$env:USERPROFILE\.config\banca-personal\eb-config.json"
```

**Expected**: The JSON above with placeholder fields.

> The `private.pem` RSA key is **not** required in IT1. It will be generated and placed
> here during IT2 (Enable Banking connector) setup. The `app_id` placeholder will be
> replaced with your real Enable Banking application ID at that time.

---

## Validation checklist

| Step | Description | Passes when |
|------|-------------|-------------|
| 1 | Dependencies install | `pip install` exits 0 |
| 2 | Entry point | `python -m banking` prints usage, exits 0 |
| 3 | Missing MasterKey | Exit 1, "not set" message on stderr |
| 4 | MasterKey configured | `echo $BANKING_MASTER_KEY` shows 64 hex chars |
| 5 | Encrypted write | `.env` contains `enc:` prefix, not plaintext |
| 6 | Round-trip decryption | `store.get()` returns original plaintext |
| 7 | Wrong MasterKey | Distinct "MasterKey may be incorrect" error |
| 8 | CI pipeline green | All 5 tools exit 0 |
| 9 | EB config directory | Directory exists with placeholder `eb-config.json` |

---

## Notes

- `.env` is git-ignored — never commit it
- `BANKING_MASTER_KEY` must never appear in any file — only in your OS environment
- The `eb-config.json` placeholder will be replaced with real credentials during IT2
