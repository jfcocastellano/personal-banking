<!--
SYNC IMPACT REPORT
==================
Version change: 1.0.0 → 1.0.1
Added sections: None
Modified principles:
  - V. Partial Resilience: connector list expanded (ING, Revolut, MyInvestor)
    → (ING, Revolut, MyInvestor, Sabadell) — scope clarification, no behavioral
    redefinition
Modified sections:
  - Performance & Observability: "Full sync duration (all 3 banks)" SLO →
    "all 4 banks", consistent with the Principle V connector list
Removed sections: None
Templates updated:
  - .specify/templates/plan-template.md: No bank-specific references ✅ (no change needed)
  - .specify/templates/tasks-template.md: No bank-specific references ✅ (no change needed)
  - .specify/templates/spec-template.md: No bank-specific references ✅ (no change needed)
Deferred TODOs: None
-->

# Banca Personal Constitution

## Core Principles

### I. Specification-First (NON-NEGOTIABLE)

Every feature MUST begin with an approved spec in `/specs/[###-feature-name]/spec.md`
before any code is written. The feature lifecycle is strictly ordered:
**spec → plan → tasks → implementation**. Skipping or reordering steps is prohibited.
`docs/context.md` is the project source of truth and supersedes all other documents.

**Rationale**: Prevents implementation drift and ensures all work is traceable
to documented requirements.

### II. Test-First (NON-NEGOTIABLE)

Tests MUST be written before implementation code. The Red-Green-Refactor cycle
is mandatory and non-negotiable:

1. Write the test → verify it **fails** (Red)
2. Write the minimum code to make it pass (Green)
3. Refactor without breaking tests

No implementation task may be marked complete unless a corresponding test
exists and was previously in a failing state. Tests are not optional.

**Rationale**: Ensures code does exactly what is specified, no more, no less.

### III. Mocks Over Real APIs in CI (NON-NEGOTIABLE)

All external services (Enable Banking, Google Sheets API, Gmail SMTP) MUST be
mocked in automated tests. No real network calls are permitted in CI.

- **Unit tests**: mock all external dependencies with `pytest-mock`
- **Integration tests**: use recorded fixtures or stub implementations, never live APIs
- Manual validation against real APIs is permitted locally and documented in quickstart

CI gate: any test that makes a real HTTP call or SMTP connection fails the pipeline.

**Rationale**: CI must be deterministic, fast, and free from external rate limits
or credential exposure.

### IV. Secret Safety (NON-NEGOTIABLE)

Zero plaintext secrets anywhere in the repository at any time:

- All credentials, tokens, and API keys stored encrypted (AES-256 via `cryptography`)
  when in `.env` files; as GitHub Secrets when running in CI
- `.env` MUST be listed in `.gitignore`; any `.env*` pattern is permanently excluded
- No hardcoded secrets, keys, or passwords in source code, test fixtures, or comments
- Master decryption key stored exclusively as an OS-level environment variable,
  never in any file tracked by git

CI gate: `git grep` pattern scan for credential shapes (Bearer tokens, private key
headers, password assignments) MUST pass on every PR.

**Rationale**: This project handles real banking credentials. A single leaked
secret is a critical security incident with no recovery path.

### V. Partial Resilience

A single bank connector failure MUST NOT abort the full synchronisation.
Required behavior:

- Each connector (ING, Revolut, MyInvestor, Sabadell) executes independently in sequence
- On connector failure: log the error, continue with remaining connectors,
  accumulate failures
- After all connectors complete: if any failed, send a single aggregated error email
- Google Sheets is updated with data from all connectors that succeeded

**Rationale**: Losing one bank's data for a day is acceptable;
losing all data because one API is unavailable is not.

### VI. Code Quality (CI-Enforced)

All code MUST pass every gate below before merge. Any violation fails CI:

| Tool | Rule | Enforcement |
|------|------|-------------|
| `ruff check` | Linting (E, W, F, I, C90 rule sets) | CI gate — zero warnings |
| `ruff format --check` | Formatting (replaces black + isort) | CI gate — zero diff |
| `mypy` | Strict type checking | CI gate — zero errors |
| `ruff` C901 | Max cyclomatic complexity: **10** per function | CI gate |

Naming conventions (enforced by `ruff` N-rules):
- Variables and functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- All public functions and methods MUST carry full type annotations

**Rationale**: Consistent style and static types reduce bugs in a codebase
with no database, no runtime schema enforcement, and a single maintainer.

### VII. Simplicity & Minimalism (YAGNI)

The project has no database, no ORM, and no persistence layer beyond Google Sheets.
This constraint MUST remain unless a spec explicitly justifies adding complexity
and documents why simpler alternatives were rejected.

- Add abstractions only when they eliminate real, present duplication (3+ occurrences)
- No speculative generalization or "future-proof" architecture
- Prefer Python stdlib over third-party libraries when capability is equivalent
- Maximum 3 layers of abstraction per vertical slice (connector → service → output)

**Rationale**: This is a single-user, single-purpose ETL process. Complexity
has a maintenance cost with no team to absorb it.

## Security Requirements

Beyond Principle IV, the following MUST be enforced:

**Dependency security**
- `pip-audit` MUST run in CI on every PR; critical or high severity vulnerabilities
  block merge
- All dependencies pinned to exact versions in `requirements.txt`;
  dev tools pinned in `requirements-dev.txt`
- `pip-audit` scan MUST also cover transitive dependencies

**Input validation**
- All data received from the Enable Banking API MUST be validated against the expected
  schema before writing to Google Sheets
- Unexpected fields MUST be ignored; missing required fields MUST trigger a warning
  log entry and skip the affected record — never crash the process
- Date fields MUST be parsed and validated as ISO 8601 before use

**No authentication layer**
- This process has no user-facing authentication (single-owner, GitHub Actions execution)
- GitHub Secrets and GitHub OIDC provide the only access control surface
- No auth middleware, session management, or token refresh logic is required

## Performance & Observability

**SLOs**

| Metric | Target |
|--------|--------|
| Full sync duration (all 4 banks) | < 2 minutes end-to-end |
| GitHub Actions job timeout | Configured at **10 minutes** (hard kill via `timeout-minutes`) |
| Error email delivery | < 60 seconds after failure detection |
| Google Sheets write per month tab | < 30 seconds |

**Mandatory observability**
- Structured logging using `logging` (stdlib). Format: `%(asctime)s %(levelname)s %(name)s: %(message)s`
- Log levels: `DEBUG` in local development, `INFO` in CI and production
- Every connector execution MUST emit: connector name, start timestamp, record count
  fetched, end timestamp, status (success | failure)
- No `print()` statements in any module except CLI entry points
- GitHub Actions step summary MUST include: banks synced, total records written,
  any partial failures, total duration

**No UX consistency requirements**
This project has no user interface. This section is intentionally N/A.

## Development Workflow

**Branch naming**
- Features: `###-short-description` (must match `/specs/###-feature-name/` folder)
- Bug fixes: `fix/short-description`
- CI / infra changes: `ci/short-description`
- Direct commits to `main` are prohibited

**Commit conventions** (Conventional Commits — mandatory)

```
<type>(<scope>): <imperative description>

Types : feat | fix | docs | chore | refactor | test | ci
Scopes: connector | sheets | email | config | ci | spec  (optional)

Examples:
  feat(connector): add ING bank connector via Enable Banking
  test(connector): add unit tests for Revolut partial-failure path
  fix(sheets): handle missing tab creation on new month
  ci: add pip-audit gate to PR workflow
  docs: update quickstart with local decryption key setup
```

Commits MUST NOT mix types (e.g., no single commit combining feat + refactor).

**Pull Requests**
- All CI gates MUST be green before merge (tests, ruff, mypy, pip-audit)
- PR description MUST reference at least one task ID from `tasks.md`
  (e.g., `Implements T042, T043`)
- Self-review is acceptable (single-owner project)
- Squash merge to `main` is the required merge strategy

**No formal release process**
`main` is always the deployable state. GitHub Actions runs the scheduled sync
directly from `main`.

## Anti-Patterns (Explicitly Prohibited)

The following are banned. Any occurrence MUST be resolved before merge:

1. **Plaintext secrets** — No API keys, passwords, or tokens in any file tracked by git,
   including test fixtures and CI config examples
2. **Real API calls in tests** — No live network requests (HTTP, SMTP, or other) in
   any file under `tests/`
3. **Bare exception suppression** — `except Exception: pass` or `except:` without
   re-raise or explicit error logging is forbidden
4. **Hardcoded configuration** — No hardcoded URLs, sheet names, bank identifiers,
   or schedule values; all configuration flows through environment variables
5. **Missing type annotations** — Public functions without return type and
   parameter type annotations on every argument
6. **`print()` in non-entry-point modules** — Use `logging`; `print()` is
   permitted only in `__main__` / CLI entry points
7. **Implementing before tests are red** — Writing implementation code before the
   corresponding test exists and has been verified to fail (violates Principle II)
8. **Local file or database persistence** — No SQLite, CSV, JSON, or any other
   intermediate storage; Google Sheets is the only output sink
9. **Aborting on single connector failure** — The sync process MUST NOT raise
   an uncaught exception that skips remaining connectors (violates Principle V)
10. **Unpinned dependencies** — No `>=`, `~=`, or open version ranges in
    `requirements.txt`; all packages MUST be pinned to exact versions

## Governance

This constitution supersedes all other practices, guidelines, and preferences
in this repository. In case of conflict, this document wins.

**Amendment procedure**
1. Open a PR modifying this file with a clear rationale for the change
2. Increment `CONSTITUTION_VERSION` per the version policy below
3. Update `LAST_AMENDED_DATE` to the amendment date (ISO 8601)
4. Update `docs/context.md` if the amendment reflects a change in project context
5. Propagate changes to affected templates (`plan-template.md`, `tasks-template.md`)
6. All CI gates MUST pass after the amendment PR

**Version policy** (Semantic Versioning)
- **MAJOR**: Removal or redefinition of a Core Principle
- **MINOR**: New principle or section added; materially expanded guidance
- **PATCH**: Clarification, wording fix, or non-semantic refinement

**Compliance review**
- The Constitution Check section in `plan-template.md` gates every feature plan
- CI enforces code quality, security, and test gates on every PR
- `docs/context.md` MUST stay in sync with any architectural decision that changes
  the project context

**Version**: 1.0.1 | **Ratified**: 2026-06-16 | **Last Amended**: 2026-08-10
