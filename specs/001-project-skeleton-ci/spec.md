# Feature Specification: Project Skeleton and CI Pipeline

**Feature Branch**: `001-project-skeleton-ci`

**Created**: 2026-06-16

**Status**: Implemented

**Input**: Project skeleton with CI pipeline, encrypted local secrets, reproducible developer setup, and pre-configured Enable Banking directory structure documented in quickstart

**Updated**: 2026-07-05 — Added FR-012 (Enable Banking config directory in quickstart) and SC-006

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reproducible Local Development Setup (Priority: P1)

A developer clones the repository and needs to go from zero to a running
local environment — including the ability to configure sensitive credentials
securely — by following a single sequential guide. No prior knowledge of
the project is assumed.

**Why this priority**: Without a reproducible local setup, no further
development is possible. Every subsequent iteration depends on this
foundation being correct and documented.

**Independent Test**: The developer can clone the repo on a machine with
Python already installed, follow quickstart.md step by step, configure
the master key, and execute the process entry point without errors.

**Acceptance Scenarios**:

1. **Given** a fresh clone with no prior configuration, **When** the
   developer follows quickstart.md from start to finish, **Then** the
   local environment is ready and the main process entry point runs
   without errors in under 5 minutes.

2. **Given** the master decryption key is not configured in the
   operating system, **When** the process attempts to read any encrypted
   secret from the configuration file, **Then** it fails immediately with
   a clear, human-readable error message identifying the missing key —
   not a cryptic decryption failure.

3. **Given** a configuration file with encrypted sensitive values and
   the master key correctly configured in the OS environment, **When**
   the process starts, **Then** the secrets are decrypted transparently
   and available to the application without any manual intervention.

4. **Given** the master key is configured, **When** the developer uses
   the built-in secrets management subcommand with a key name and a
   plaintext value, **Then** the value is encrypted and written to the
   SecretStore without the plaintext appearing in any file or shell
   history output.

5. **Given** a fresh clone with no prior configuration, **When** the
   developer follows quickstart.md from start to finish, **Then** the
   directory `~/.config/banca-personal/` exists on the machine and
   contains a placeholder `eb-config.json` that documents the required
   fields (`app_id`, `private_key_path`), making the developer ready to
   configure the Enable Banking connector without additional research.

---

### User Story 2 - Automated Quality Enforcement on Every Code Change (Priority: P2)

Every time code is pushed to the repository or a pull request is opened,
an automated pipeline verifies that the change meets the project's
quality standards. The developer can rely on this to catch regressions
before they reach the main branch.

**Why this priority**: Consistent code quality is a prerequisite for all
subsequent features. Without automated enforcement, standards degrade
over time.

**Independent Test**: A code change that violates any quality rule fails
the pipeline before it can be merged. A clean change passes all gates
automatically.

**Acceptance Scenarios**:

1. **Given** a push to `main` or a pull request, **When** the pipeline
   runs, **Then** it verifies dependency security, code style, type
   correctness, and tests in a fixed sequence, stopping at the first
   failure and reporting it clearly.

2. **Given** a dependency with a known critical or high severity
   security vulnerability is introduced, **When** the pipeline runs,
   **Then** it fails at the security verification step and the change
   cannot be merged until the vulnerability is resolved.

3. **Given** all quality checks pass and the test suite is green,
   **When** the pipeline completes, **Then** the result is marked
   successful and the change is eligible for merge.

---

### Edge Cases

- What happens when the `.env` file is absent on a fresh clone?
  → The process starts without errors; no secrets are available yet,
  which is acceptable for an empty process with no business logic.
- What happens if the MasterKey is not set in the OS environment?
  → The process fails immediately with a clear human-readable error
  identifying the missing key — not a cryptic decryption failure.
- What happens if the MasterKey is set but is incorrect for a stored value?
  → The process fails immediately with a distinct, descriptive error
  indicating that decryption failed — differentiating it from the
  missing-key case so the developer can diagnose the root cause.
- What happens if a quality gate times out in CI?
  → The job is marked as failed via GitHub's standard timeout mechanism;
  no special handling required at this stage.
- What happens if `~/.config/banca-personal/` is absent when a developer
  tries to configure the Enable Banking connector in a later iteration?
  → Because quickstart.md explicitly includes its creation as a required
  step, the absence means setup was incomplete; the error is the
  connector's to raise (out of scope for IT1).

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST contain a main package with an
  invocable entry point that, when called without arguments, displays a
  usage message listing the available subcommands and exits with code 0.
- **FR-002**: All production and development dependencies MUST be
  declared in separate manifests with every version pinned to an exact
  release (no ranges, no approximate pins).
- **FR-003**: Every code change MUST be automatically validated against
  the project's defined style and formatting rules before it can be
  merged; any violation MUST cause the pipeline to fail.
- **FR-004**: Every code change MUST pass static type analysis with zero
  errors before it can be merged.
- **FR-005**: Every code change MUST pass an automated security scan
  covering all direct and transitive dependencies; findings at critical
  or high severity MUST block the merge.
- **FR-006**: Every code change MUST pass the full automated test suite
  before it can be merged.
- **FR-007**: The CI pipeline MUST execute its validation steps in a
  fixed, defined sequence so that failures surface at the earliest
  possible step and do not waste pipeline time on later steps.
- **FR-008**: Sensitive configuration values MUST be stored in an
  encrypted form in any local configuration file; decryption MUST
  require a key that exists only in the operator's OS environment and
  never in any file tracked by version control.
- **FR-011**: The main package's CLI MUST provide a secrets management
  subcommand that accepts a key name and a plaintext value, encrypts
  the value using the MasterKey, and writes the result to the
  SecretStore — allowing the developer to populate secrets without
  writing plaintext to any file manually.
- **FR-009**: The local configuration file containing encrypted secrets
  MUST be permanently excluded from version control.
- **FR-010**: The project MUST include a setup guide that allows any
  developer to reproduce the complete local environment from a fresh
  clone by following a single, linear document with no ambiguous steps.
- **FR-012**: The setup guide MUST include an explicit, sequential step
  that instructs the developer to create `~/.config/banca-personal/`
  and documents its expected contents: a placeholder `eb-config.json`
  file showing the required fields (`app_id`, `private_key_path`) and
  the location for the RSA private key (`private.pem`). This step is a
  prerequisite for configuring the Enable Banking connector in a later
  iteration; its absence MUST be detectable before attempting connector
  setup.

### Key Entities

- **SecretStore**: The local configuration file containing encrypted
  sensitive values. Excluded from version control. Unreadable without
  the master key. Managed via the built-in secrets management CLI
  subcommand; never edited manually. A committed example file with
  placeholder key names (no real values) documents its structure.
- **MasterKey**: The operator-held secret required to decrypt the
  SecretStore. Exists exclusively as an operating system environment
  variable on the developer's machine. Never stored in any file,
  committed or otherwise.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer with no prior knowledge of the project can
  complete local setup and run the process entry point by following
  quickstart.md, in under 5 minutes on a machine with Python 3.12
  already installed.
- **SC-002**: The CI pipeline completes a full quality verification
  cycle in under 3 minutes for the initial codebase.
- **SC-003**: Zero quality violations are present in the initial
  committed codebase — all pipeline gates pass green from the very
  first commit.
- **SC-004**: Zero dependency security findings at high or critical
  severity are present in the initial set of pinned dependencies.
- **SC-005**: A value written to the SecretStore is successfully
  decrypted and readable by the running process in a local environment
  where the MasterKey is set; and produces a clear error if the
  MasterKey is absent.
- **SC-006**: After completing quickstart.md, the directory
  `~/.config/banca-personal/` exists on the developer's machine and
  contains a placeholder `eb-config.json` that documents the required
  fields. A developer following only quickstart.md is fully prepared
  to configure the Enable Banking connector in the next iteration
  without any additional research.

---

## Assumptions

- Python 3.12 is the sole supported runtime. No multi-version matrix
  is needed in CI.
- The CI pipeline runs on standard GitHub-hosted Linux runners.
- The main package is named `banking`, reflecting the repository domain.
  It will be populated with business logic in future iterations.
- The quickstart assumes the developer already has Python 3.12 installed.
  Installation of Python itself is out of scope.
- The initial automated test suite may be empty or contain a single
  smoke test; the pipeline MUST pass regardless.
- A committed `.env.example` file with placeholder (non-sensitive) values
  documents the expected structure of the SecretStore without exposing
  real credentials.
- The CI pipeline does not require real credentials or network access;
  it runs entirely with the committed codebase and pinned dependencies.
- The Enable Banking connector (IT2) will require a dedicated configuration
  directory at `~/.config/banca-personal/` containing the RSA private key
  (`private.pem`) and a configuration file (`eb-config.json` with `app_id`
  and the path to the key). This directory is independent of the SecretStore
  (AES-256) and must be documented in `quickstart.md`.

---

## Clarifications

### Session 2026-06-16

- Q: How does a developer write a new secret into the SecretStore? → A: Via a built-in CLI subcommand (`secrets set <KEY> <VALUE>`) that encrypts the value with the MasterKey and writes it to the SecretStore. No manual file editing required.
- Q: What does the entry point do when run without arguments in this iteration? → A: Displays a usage message listing available subcommands (e.g., `sync`, `secrets`) and exits with code 0.
- Q: What should happen when the MasterKey is present but wrong (decryption fails)? → A: Fail immediately with a distinct, descriptive error message that differentiates this case from a missing MasterKey.
