# Tasks: Project Skeleton and CI Pipeline

**Input**: Design documents from `specs/001-project-skeleton-ci/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅

**Tests**: Tests are **MANDATORY** per Principle II (Test-First). Tests MUST be
written before implementation code and MUST be verified to fail (Red) before any
implementation begins. Red → Green → Refactor is non-negotiable.

**Organization**: US1 (P1) → US2 (P2). US2 depends on US1 having established
a working package structure (a CI pipeline needs code to lint and test).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Parallelizable — different files, no blocking dependency
- **[Story]**: User story label (US1, US2)
- All paths are relative to repository root

---

## Phase 1: Setup (Project Initialization)

**Purpose**: Create the physical file structure and configuration manifests. No
Python logic yet. All tasks marked [P] are independent and can run simultaneously.

- [X] T001 Create all required directories: `src/banking/`, `src/banking/cli/`, `src/banking/config/`, `tests/unit/`, `tests/unit/config/`, `docs/`, `.github/workflows/`
- [X] T002 [P] Create `requirements.txt` with exact-pinned production dependencies: `cryptography` and `python-dotenv` (run `pip install cryptography python-dotenv`, then `pip freeze` to capture exact versions)
- [X] T003 [P] Create `requirements-dev.txt` with exact-pinned dev dependencies: `pytest`, `pytest-mock`, `ruff`, `mypy`, `pip-audit` (same pin methodology)
- [X] T004 [P] Create `pyproject.toml` with ruff config (select E, W, F, I, C90, N; max-line-length 100; target Python 3.12), mypy config (strict = true; python_version = "3.12"), and `[build-system]` + `[project]` sections for `pip install -e .` support (package name `banking`, root `src/`)
- [X] T005 [P] Create `.gitignore` with Python standard entries plus explicit exclusions: `.env`, `.env.*`, `__pycache__/`, `*.pyc`, `.mypy_cache/`, `.ruff_cache/`, `dist/`, `*.egg-info/`
- [X] T006 [P] Create `.env.example` with all required placeholder keys per `specs/001-project-skeleton-ci/contracts/secret-store-format.md` (keys for Enable Banking, Google Sheets, Gmail SMTP; all values = `enc:placeholder`)

**Checkpoint**: All configuration files exist. No Python code yet.

---

## Phase 2: Foundational (Package Skeleton)

**Purpose**: Minimal Python package scaffolding that must exist before any test
can be written or run. Blocks all user story work.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T007 Create all `__init__.py` marker files: `src/banking/__init__.py` (with `__version__ = "0.1.0"`), `src/banking/cli/__init__.py`, `src/banking/config/__init__.py`, `tests/__init__.py`, `tests/unit/__init__.py`, `tests/unit/config/__init__.py`
- [X] T008 [P] Create `src/banking/py.typed` (empty PEP 561 marker; required for mypy strict type checking of downstream consumers)
- [X] T009 Create `tests/unit/conftest.py` with shared pytest fixtures: `mock_master_key` (exports a valid 64-char hex string as `BANKING_MASTER_KEY` env var via `monkeypatch`), `tmp_env_file` (creates a temporary `.env` file path in `tmp_path`)

**Checkpoint**: `python -m pytest --collect-only` runs without import errors. `mypy src/` produces no errors on empty packages.

---

## Phase 3: User Story 1 — Reproducible Local Development Setup (Priority: P1) 🎯 MVP

**Goal**: A developer can clone the repo, follow `quickstart.md`, configure the
MasterKey, use `banking secrets set` to store encrypted values, and verify the
SecretStore decrypts correctly. The directory `~/.config/banca-personal/` is
created with a documented placeholder structure ready for IT2.

**Independent Test**: Run `quickstart.md` steps 1–9 on a clean machine. All
steps exit 0. `SecretStore` round-trip test passes. `python -m banking` prints
usage and exits 0.

### Tests for User Story 1 ⚠️ MANDATORY — write first, verify RED before T014

> **NOTE: Write ALL tests in this section first. Run `pytest` and confirm EVERY
> test FAILS with ImportError or AttributeError before writing any implementation
> (Principle II — Red-Green-Refactor is non-negotiable).**

- [X] T010 [P] [US1] Write failing tests for `python -m banking` entry point in `tests/unit/test_main.py`: (1) running as module prints usage text to stdout and exits 0; (2) unrecognised subcommand exits non-zero
- [X] T011 [US1] Write failing tests for MasterKey validation in `tests/unit/config/test_secret_store.py`: (1) `BANKING_MASTER_KEY` absent → `ConfigurationError` with "not set" in message; (2) `BANKING_MASTER_KEY` is 32 chars (wrong length) → `ConfigurationError` with "64 hex characters" in message
- [X] T012 [US1] Write failing tests for SecretStore operations in `tests/unit/config/test_secret_store.py`: (3) encrypt then decrypt returns original plaintext (round-trip); (4) decrypting with a different valid MasterKey → `DecryptionError` with "MasterKey may be incorrect" in message; (5) decrypting a malformed blob (corrupted base64) → `DecryptionError` with "malformed" in message; (6) `get()` on absent key → `KeyError`
- [X] T013 [P] [US1] Write failing tests for `banking secrets set KEY VALUE` CLI in `tests/unit/test_cli_secrets.py`: (1) calling with valid args writes `enc:` prefixed value to `.env` file; (2) plaintext does not appear anywhere in `.env` after set; (3) missing `BANKING_MASTER_KEY` → exits with code 1; (4) missing args → exits with code 1

### Implementation for User Story 1

- [X] T014 [US1] Implement `SecretStore` class in `src/banking/config/secret_store.py`: `load_master_key()` (validates env var, raises `ConfigurationError`); `encrypt(plaintext: str) -> str` (AES-256-GCM, returns `enc:<base64url>`); `decrypt(blob: str) -> str` (raises `DecryptionError` on tag failure or malformed input); `set(key: str, value: str)` (reads `.env`, updates/inserts encrypted entry, writes back); `get(key: str) -> str` (reads `.env`, decrypts if `enc:` prefix) — all public methods fully type-annotated; custom exceptions `ConfigurationError` and `DecryptionError` in same module
- [X] T015 [US1] Implement `secrets set` subcommand handler in `src/banking/cli/secrets.py`: `add_parser(subparsers)` registers `secrets set KEY VALUE`; `handle(args)` calls `SecretStore().set(args.key, args.value)`, exits 0 on success, exits 1 on `ConfigurationError` with stderr message, exits 2 on file I/O error — fully type-annotated
- [X] T016 [US1] Implement `src/banking/__main__.py` entry point: create `argparse.ArgumentParser`, register `secrets` subparser via `banking.cli.secrets.add_parser()`, print usage and exit 0 when called with no arguments, dispatch to appropriate handler otherwise — fully type-annotated
- [X] T017 [P] [US1] Create `quickstart.md` at repository root following the 9-step validation guide in `specs/001-project-skeleton-ci/quickstart.md` (step 9 must include creating `~/.config/banca-personal/` and writing the placeholder `eb-config.json`)

**Checkpoint**: All Phase 3 tests pass. `python -m banking` prints usage. `banking secrets set` encrypts correctly. SecretStore round-trip verified. `~/.config/banca-personal/` documented in quickstart.

---

## Phase 4: User Story 2 — Automated Quality Enforcement on Every Code Change (Priority: P2)

**Goal**: Every push to `main` and every PR triggers a pipeline that runs
pip-audit → ruff check → ruff format --check → mypy → pytest in sequence.
The first failure stops the pipeline immediately.

**Independent Test**: Push a PR with a deliberate ruff violation; confirm the
pipeline fails at the ruff step with a clear message. Push a clean commit;
confirm all steps pass green.

### Tests for User Story 2 ⚠️ MANDATORY — write first, verify RED before T019

> **NOTE: The test verifies structural properties of the CI config file. It fails
> because the file does not exist yet. Create it only after verifying this test
> is RED.**

- [X] T018 [P] [US2] Write failing test for CI workflow in `tests/unit/test_ci_config.py`: parse `.github/workflows/ci.yml` as YAML; assert file exists; assert `on.push.branches` includes `main`; assert `on.pull_request.branches` includes `main`; assert job steps include shell commands containing `pip-audit`, `ruff check`, `ruff format`, `mypy`, `pytest` in that order

### Implementation for User Story 2

- [X] T019 [US2] Create `.github/workflows/ci.yml`: trigger on `push` and `pull_request` to `main`; single job `ci` on `ubuntu-latest`; steps: (1) `actions/checkout@v4`, (2) `actions/setup-python@v5` with `python-version: "3.12"`, (3) `pip install -r requirements.txt -r requirements-dev.txt`, (4) `pip-audit -r requirements.txt -r requirements-dev.txt`, (5) `ruff check src/ tests/`, (6) `ruff format --check src/ tests/`, (7) `mypy src/`, (8) `pytest tests/`; each step named clearly; no credentials in YAML

**Checkpoint**: All Phase 4 tests pass. `ci.yml` is valid YAML and contains all required steps. Running steps 4–8 locally all exit 0.

---

## Phase 5: Polish & Validation

**Purpose**: Final cross-cutting verification. Confirms the full feature satisfies
all acceptance criteria and success criteria from spec.md.

- [X] T020 Run full local CI simulation (quickstart.md step 8): `pip-audit -r requirements.txt -r requirements-dev.txt && ruff check src/ tests/ && ruff format --check src/ tests/ && mypy src/ && pytest tests/ -v` — all must exit 0
- [X] T021 [P] Verify `.env.example` is committed, `.env` is absent from git tracking, and `git grep` finds no credential-shaped strings (`BANKING_MASTER_KEY=`, `enc:`, `Bearer `) in any committed file

**Checkpoint**: All 21 tasks complete. All acceptance scenarios from spec.md pass. Feature is ready to merge.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 completion — blocks US1 and US2
- **Phase 3 (US1)**: Depends on Phase 2; tests (T010–T013) must fail before implementation (T014–T017)
- **Phase 4 (US2)**: Depends on Phase 3 — CI pipeline needs code to lint and test
- **Phase 5 (Polish)**: Depends on Phases 3 and 4

### User Story Dependencies

- **US1 (P1)**: Depends on Phase 2 (Foundational) only. No other user story dependencies.
- **US2 (P2)**: Depends on US1 — the CI pipeline runs against the code created in US1. Cannot be green before US1 is complete.

### Within US1

```
T010 (test_main.py)       →  T016 (__main__.py)
T011 (test_secret_store)  →  T012 (test_secret_store)  →  T014 (SecretStore)  →  T015 (cli/secrets.py)  →  T016
T013 (test_cli_secrets)   →  T015 (cli/secrets.py)
T017 (quickstart.md)      — independent, can run in parallel with T014–T016
```

### Within US2

```
T018 (test_ci_config.py)  →  T019 (ci.yml)
```

---

## Parallel Opportunities

### Phase 1 (all parallelizable after T001)

```
After T001 (directories created):
  T002 (requirements.txt)
  T003 (requirements-dev.txt)
  T004 (pyproject.toml)
  T005 (.gitignore)
  T006 (.env.example)
  — all can run simultaneously
```

### Phase 3 Tests (before implementation)

```
T010 (test_main.py)    ─┐
T011 (test_secret_store)─┤ Write tests simultaneously (different files or independent sections)
T013 (test_cli_secrets) ─┘
T012 continues T011 in the same file
```

### Phase 3 Implementation

```
T014 (SecretStore)  ─→  T015 (cli/secrets.py)  ─→  T016 (__main__.py)
T017 (quickstart.md) — independent, write in parallel with T014
```

---

## Implementation Strategy

### MVP (User Story 1 only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Write failing tests for US1 (T010–T013) — verify all RED
4. Implement US1 (T014–T017) — verify all GREEN
5. **STOP AND VALIDATE**: Run quickstart.md steps 1–9 manually

### Full Delivery

1. MVP above ✅
2. Write failing test for US2 (T018) — verify RED
3. Implement US2 (T019) — verify GREEN
4. Phase 5 Polish (T020–T021)

---

## Notes

- [P] tasks = different files, safe to parallelize
- Test tasks are always [P] if they target different files
- `SecretStore` exceptions (`ConfigurationError`, `DecryptionError`) are defined
  in `src/banking/config/secret_store.py` — not in a separate module (YAGNI)
- All public functions and methods MUST carry full type annotations (mypy strict)
- No `print()` in `secret_store.py` or `cli/secrets.py` — use `logging`; `print()`
  only in `__main__.py` for usage message output
- Commit after each logical group (e.g., after Phase 1 complete, after US1 tests
  written, after US1 implementation complete, after US2 complete)
- `BANKING_MASTER_KEY` must never appear in any committed file — verified in T021
