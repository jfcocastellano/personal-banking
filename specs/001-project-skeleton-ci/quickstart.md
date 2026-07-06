# Quickstart Validation Guide: Project Skeleton and CI Pipeline

**Purpose**: Prove that IT1 is complete — the project structure is sound, the CI
pipeline passes, the SecretStore mechanism works, and the developer is fully
prepared for IT2.

**Prerequisites**: Python 3.12 installed. Git available. No prior configuration
assumed.

---

## Step 1 — Clone and install dependencies

```bash
git clone <repo-url>
cd proyecto-banca-personal

pip install -r requirements.txt
pip install -r requirements-dev.txt
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
unset BANKING_MASTER_KEY    # ensure the key is absent
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
export BANKING_MASTER_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
echo $BANKING_MASTER_KEY    # confirm it's set (64 hex chars)
```

Add this export to your shell profile (`.bashrc`, `.zshrc`, etc.) so it persists
across sessions. Do **not** write it to any file inside the repository.

---

## Step 5 — Write an encrypted secret

```bash
python -m banking secrets set ENABLE_BANKING_SESSION_ID test_placeholder_value
```

**Expected**: No output to stdout. Exit code 0. The file `.env` now contains:
```
ENABLE_BANKING_SESSION_ID=enc:<base64url blob>
```

Verify:
```bash
grep ENABLE_BANKING_SESSION_ID .env
# Should show: ENABLE_BANKING_SESSION_ID=enc:...
# "test_placeholder_value" must NOT appear anywhere in the line
```

---

## Step 6 — Verify the SecretStore decrypts correctly

```python
python - << 'EOF'
from banking.config.secret_store import SecretStore
store = SecretStore()
value = store.get("ENABLE_BANKING_SESSION_ID")
assert value == "test_placeholder_value", f"Got: {value}"
print("OK — SecretStore round-trip verified")
EOF
```

**Expected output**: `OK — SecretStore round-trip verified`

---

## Step 7 — Verify that a wrong MasterKey produces a distinct error

```bash
BANKING_MASTER_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") python - << 'EOF'
from banking.config.secret_store import SecretStore
store = SecretStore()
try:
    store.get("ENABLE_BANKING_SESSION_ID")
    print("FAIL — should have raised an error")
except Exception as e:
    print(f"OK — got expected error: {e}")
EOF
```

**Expected**: prints `OK — got expected error: Decryption failed for key 'ENABLE_BANKING_SESSION_ID'...`
(distinct message from Step 3)

---

## Step 8 — Run the full CI pipeline locally

```bash
pip-audit -r requirements.txt -r requirements-dev.txt
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest tests/
```

**Expected**: All commands exit with code 0. `pytest` output shows at minimum
one test passing (smoke test).

---

## Step 9 — Create the Enable Banking configuration directory

This step prepares the environment for IT2 (Enable Banking connector). IT1 only
requires the directory to exist with a documented placeholder structure.

```bash
mkdir -p ~/.config/banca-personal

cat > ~/.config/banca-personal/eb-config.json << 'EOF'
{
  "app_id": "<your-enable-banking-app-id>",
  "private_key_path": "~/.config/banca-personal/private.pem"
}
EOF
```

**Verify**:
```bash
ls ~/.config/banca-personal/
# eb-config.json

cat ~/.config/banca-personal/eb-config.json
# should show the JSON above
```

**Expected**: directory exists, `eb-config.json` present with placeholder fields.
The `private.pem` RSA key is NOT yet required in IT1 — it will be generated
and placed here during IT2 setup.

---

## Validation checklist

| Scenario | Steps | Passes when |
|----------|-------|-------------|
| Fresh clone runs entry point | 1-2 | Exit 0, usage message printed |
| Missing MasterKey gives clear error | 3 | Exit 1, specific error on stderr |
| SecretStore round-trip works | 4-6 | Decrypted value matches original |
| Wrong MasterKey gives distinct error | 7 | Distinct error, not a crash |
| Full CI pipeline green | 8 | All tools exit 0 |
| EB config directory ready for IT2 | 9 | Directory + placeholder JSON exist |

---

## Notes

- `.env` is git-ignored; never commit it
- `BANKING_MASTER_KEY` must never appear in any file — only in your shell environment
- The `eb-config.json` placeholder will be replaced with real Enable Banking
  credentials during IT2 setup
