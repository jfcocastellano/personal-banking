# Implementation Plan: Project Skeleton and CI Pipeline

**Branch**: `001-project-skeleton-ci` | **Date**: 2026-07-05 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-project-skeleton-ci/spec.md`

---

## Summary

Establish the Python 3.12 project structure, encrypted local secrets mechanism
(AES-256-GCM via `cryptography`), a minimal CLI entry point, and a GitHub Actions
CI pipeline that enforces code quality on every push. The iteration delivers no
business logic — it sets the foundation that all subsequent iterations build on,
including the `~/.config/banca-personal/` directory documented in `quickstart.md`
as a prerequisite for the Enable Banking connector (IT2).

See `research.md` for all key design decisions (encryption scheme, SecretStore
format, MasterKey derivation, CI pipeline ordering).

---

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**:
- `cryptography` — AES-256-GCM encryption for SecretStore (production)
- `python-dotenv` — load `.env` file (production)
- `pytest` + `pytest-mock` — testing (dev)
- `ruff` — linting and formatting (dev)
- `mypy` — strict static type checking (dev)
- `pip-audit` — dependency security scanning (dev)

**Storage**: `.env` file (SecretStore — configuration, not business data;
explicitly allowed by Constitution §IV). No database, no business data persistence.

**Testing**: `pytest` with `pytest-mock`. No real API calls anywhere in tests.

**Target Platform**: Linux (GitHub Actions `ubuntu-latest`). Local dev on any OS
that supports Python 3.12.

**Project Type**: CLI / batch process skeleton

**Performance Goals**:
- Full CI pipeline: < 3 minutes (SC-002)
- Developer setup from fresh clone: < 5 minutes (SC-001)

**Constraints**:
- MasterKey exclusively as OS env var; never in any file
- `.env` permanently excluded from version control
- All dependencies pinned to exact versions

**Scale/Scope**: Single developer, single-owner system. No concurrency requirements
in this iteration.

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] Spec exists and is approved in `specs/001-project-skeleton-ci/spec.md` (Principle I)
- [x] No real API calls planned in any test file — IT1 has no external APIs (Principle III)
- [x] No database or local file persistence introduced — SecretStore is configuration,
  not business data; explicitly allowed by Constitution §IV (Principle VII)
- [x] All secrets flow via GitHub Secrets or encrypted `.env` — this iteration
  establishes that pattern (Principle IV)
- [x] Connector failures handled independently — N/A, no connectors in IT1 (Principle V)
- [x] All public functions will carry full type annotations — enforced by `mypy` in CI
  (Principle VI)
- [x] No function with cyclomatic complexity > 10 — CLI + encryption helpers are
  simple, well within limit (Principle VI)
- [x] No new third-party dependency without exact pin — enforced by the pinning
  mechanism being established in this very iteration (Anti-pattern #10)

**Post-design re-check**: All gates pass. SecretStore write path introduces one
file I/O operation (`open().write()`), which is configuration management, not
business persistence. No violations.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-project-skeleton-ci/
├── plan.md              ← this file
├── research.md          ← Phase 0 decisions
├── data-model.md        ← Phase 1 entities
├── quickstart.md        ← Phase 1 validation guide
├── contracts/
│   ├── cli-interface.md     ← CLI command schema
│   └── secret-store-format.md ← .env file format
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/
└── banking/
    ├── __init__.py
    ├── __main__.py              # `python -m banking` entry point
    ├── cli/
    │   ├── __init__.py
    │   └── secrets.py           # `banking secrets set KEY VALUE`
    └── config/
        ├── __init__.py
        └── secret_store.py      # AES-256-GCM read/write + MasterKey loading

tests/
└── unit/
    ├── conftest.py
    ├── test_main.py             # Entry point: usage message, exit code 0
    └── config/
        ├── __init__.py
        └── test_secret_store.py # Encrypt, decrypt, missing key, wrong key

.github/
└── workflows/
    └── ci.yml                   # pip-audit → ruff → mypy → pytest

pyproject.toml                   # ruff + mypy configuration
requirements.txt                 # cryptography, python-dotenv (pinned)
requirements-dev.txt             # pytest, pytest-mock, ruff, mypy, pip-audit (pinned)
.env.example                     # placeholder key names (no real values)
.gitignore                       # includes .env, .env.*
quickstart.md                    # (repo root) developer setup guide
docs/
├── context.md
└── roadmap.md
```

**Structure Decision**: Single Python package `src/banking/`. Two sub-packages:
`cli/` for user-facing commands, `config/` for the SecretStore mechanism. Tests
mirror the source tree under `tests/unit/`. No integration or contract tests in IT1
(no external interfaces yet).

---

## Complexity Tracking

No violations. All functions are simple (SecretStore encrypt/decrypt, CLI argument
parsing) and well within the cyclomatic complexity limit of 10.

---

## Design Decisions (Phase 0 summary)

Full rationale and alternatives in `research.md`.

| Decision | Choice | Key reason |
|----------|--------|------------|
| Encryption scheme | AES-256-GCM via `cryptography` hazmat layer | True AES-256 as required by Constitution §IV |
| SecretStore file | `.env` with `enc:<base64>` prefix for encrypted values | dotenv-compatible; python-dotenv loads it transparently |
| MasterKey format | 32-byte raw key, base64-encoded, stored as OS env var | No KDF overhead; deterministic; standard for AES-256 |
| MasterKey env var name | `BANKING_MASTER_KEY` | Clear, project-scoped, unambiguous |
| Package entry point | `python -m banking` via `__main__.py` | No install required; simpler than console_scripts for this use |
| CI runner | `ubuntu-latest` + Python 3.12 | Matches GitHub Actions free tier and target platform |
| CI step order | pip-audit → ruff check → ruff format → mypy → pytest | Security first, style gates cheap-fail before slow type check |
| `~/.config/banca-personal/` | Manual creation step in `quickstart.md` | IT1 does not own this directory; IT2 connector owns it |
