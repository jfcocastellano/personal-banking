"""Contract tests for `.github/workflows/sync.yml` (IT7 — scheduled sync).

Every assertion maps to an invariant of
``specs/007-scheduler-github-actions/contracts/sync-workflow.md`` § 6.

The tests only read and parse YAML: no network, no GitHub API access, no workflow
execution (constitution Principle III). The real end-to-end validation is a manual
`gh workflow run sync.yml` documented in ``quickstart.md`` § 3.

Growth history (Test-First, Principle II):

* T004 — file exists and is valid YAML.
* T005 — scheduled trigger is a single daily cron.
* T006 — job environment, time limit and dependency installation.
* T007 — configuration contract: 14 secrets, early validation, provisioning.
* T008 — execution and exit-code propagation.
* T012 — manual trigger and mutual exclusion (US2).
* T014 — published step summary (US3).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

SYNC_WORKFLOW = Path(".github/workflows/sync.yml")


def _load_workflow() -> dict[str, Any]:
    """Load the sync workflow, failing clearly when it does not exist yet."""
    assert SYNC_WORKFLOW.exists(), f"Sync workflow not found: {SYNC_WORKFLOW}"
    with SYNC_WORKFLOW.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict), f"{SYNC_WORKFLOW} is not a YAML mapping"
    # PyYAML resolves a bare `on:` key to the boolean True (YAML 1.1).
    if "on" not in data and True in data:
        data["on"] = data.pop(True)
    return data


def test_workflow_file_exists() -> None:
    """The scheduler must live in its own workflow file (FR-001)."""
    assert SYNC_WORKFLOW.is_file(), f"Missing: {SYNC_WORKFLOW}"


def test_workflow_is_valid_yaml_with_a_name() -> None:
    """The workflow must be valid YAML and carry a human-readable name (FR-006)."""
    workflow = _load_workflow()
    assert isinstance(workflow.get("name"), str) and workflow["name"].strip()
    assert "jobs" in workflow and workflow["jobs"], "The workflow declares no job"


# --------------------------------------------------------------------------
# Helpers shared by the story tests below
# --------------------------------------------------------------------------

REQUIRED_SECRETS = (
    "BANKING_MASTER_KEY",
    "ENABLE_BANKING_SESSION_ID_ING",
    "ENABLE_BANKING_SESSION_ID_REVOLUT",
    "ENABLE_BANKING_SESSION_ID_MYINVESTOR",
    "ENABLE_BANKING_SESSION_ID_SABADELL",
    "ENABLE_BANKING_APP_ID",
    "ENABLE_BANKING_PRIVATE_KEY",
    "GOOGLE_SHEETS_CREDENTIALS",
    "GOOGLE_SHEET_ID",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "NOTIFY_EMAIL_TO",
)

SECRET_EXPRESSION = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}")
DAILY_CRON = re.compile(r"^\d{1,2} \d{1,2} \* \* \*$")


def _job() -> dict[str, Any]:
    """Return the single job of the workflow."""
    jobs = _load_workflow().get("jobs", {})
    assert len(jobs) == 1, f"Expected exactly one job, found {sorted(jobs)}"
    (job,) = jobs.values()
    assert isinstance(job, dict)
    return job


def _steps() -> list[dict[str, Any]]:
    """Return every step of the job, in order."""
    steps = _job().get("steps", [])
    assert steps, "The job declares no steps"
    return steps


def _step_named(name: str) -> dict[str, Any]:
    """Return the step with the given name."""
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"No step named {name!r}; found {[s.get('name') for s in _steps()]}")


def _step_index(name: str) -> int:
    """Return the position of the named step within the job."""
    names = [step.get("name") for step in _steps()]
    assert name in names, f"No step named {name!r}; found {names}"
    return names.index(name)


def _run_text(name: str) -> str:
    """Return the `run` script of the named step."""
    script = _step_named(name).get("run")
    assert isinstance(script, str) and script.strip(), f"Step {name!r} has no run script"
    return script


def _all_run_text() -> str:
    """Concatenate every `run` script of the job."""
    return "\n".join(step["run"] for step in _steps() if isinstance(step.get("run"), str))


def _job_env() -> dict[str, Any]:
    """Return the job-level environment mapping."""
    env = _job().get("env", {})
    assert isinstance(env, dict), "The job declares no env mapping"
    return env


# --------------------------------------------------------------------------
# T005 — scheduled trigger (FR-001, FR-011)
# --------------------------------------------------------------------------


def test_schedule_trigger_is_a_single_daily_cron() -> None:
    """The workflow runs once a day at a fixed hour, with no other schedule."""
    schedule = _load_workflow()["on"].get("schedule")
    assert isinstance(schedule, list), "The workflow has no schedule trigger"
    assert len(schedule) == 1, f"Expected exactly one cron entry, found {schedule}"
    cron = schedule[0].get("cron")
    assert isinstance(cron, str) and DAILY_CRON.match(cron), f"Not a daily cron: {cron!r}"


def test_no_unexpected_triggers() -> None:
    """Only the daily schedule and the manual trigger are allowed (FR-011)."""
    triggers = set(_load_workflow()["on"])
    unexpected = triggers - {"schedule", "workflow_dispatch"}
    assert not unexpected, f"Unexpected triggers: {sorted(unexpected)}"


# --------------------------------------------------------------------------
# T006 — job environment, time limit and dependencies (FR-005, Decisión 11)
# --------------------------------------------------------------------------


def test_job_runs_on_ubuntu_with_a_ten_minute_timeout() -> None:
    """The job is bounded by the constitution's 10-minute hard kill."""
    job = _job()
    assert job.get("runs-on") == "ubuntu-latest"
    assert job.get("timeout-minutes") == 10


def test_python_runtime_and_actions_are_pinned() -> None:
    """Checkout and Python 3.12 come from the pinned major versions."""
    uses = [step.get("uses") for step in _steps()]
    assert "actions/checkout@v4" in uses, f"Missing checkout step: {uses}"
    setup = next((s for s in _steps() if s.get("uses") == "actions/setup-python@v5"), None)
    assert setup is not None, "Missing actions/setup-python@v5"
    assert setup.get("with", {}).get("python-version") == "3.12"


def test_runtime_dependencies_are_installed_and_audited() -> None:
    """Only runtime dependencies are installed, and they are audited."""
    commands = _all_run_text()
    assert "pip install -r requirements.txt" in commands
    assert "pip install -e ." in commands
    assert "pip-audit -r requirements.txt" in commands
    assert "requirements-dev.txt" not in commands, "The scheduler must not install dev tooling"


# --------------------------------------------------------------------------
# T007 — configuration contract (FR-004, FR-009, Decisión 3)
# --------------------------------------------------------------------------


def test_every_required_secret_is_declared_exactly_once() -> None:
    """All 14 secrets of the contract reach the job through `env:` (FR-004)."""
    env = _job_env()
    missing = [name for name in REQUIRED_SECRETS if name not in env]
    assert not missing, f"Secrets not declared in env: {missing}"
    for name in REQUIRED_SECRETS:
        match = SECRET_EXPRESSION.fullmatch(str(env[name]).strip())
        assert match is not None, f"{name} is not bound to a secret expression"
        assert match.group(1) == name, f"{name} is bound to secrets.{match.group(1)}"


def test_configuration_is_validated_before_any_external_call() -> None:
    """A missing secret aborts the run before any bank API call (FR-009)."""
    validation = _step_index("Validar configuración")
    assert validation < _step_index("Ejecutar sincronización")
    script = _run_text("Validar configuración")
    missing_names = [name for name in REQUIRED_SECRETS if name not in script]
    assert not missing_names, f"Validation does not check: {missing_names}"
    assert "exit 1" in script, "Validation must fail the job when a secret is missing"


def test_configuration_is_provisioned_into_the_existing_mechanisms() -> None:
    """Secrets land in the encrypted .env and in the Enable Banking config dir."""
    script = _run_text("Provisionar configuración")
    assert "python -m banking secrets set" in script
    assert "$RUNNER_TEMP" in script
    assert "BANKING_EB_CONFIG_DIR" in script
    assert "eb-config.json" in script
    assert "private_key_path" in script
    assert "app_id" in script
    assert "chmod 600" in script


# --------------------------------------------------------------------------
# T008 — execution and exit-code propagation (FR-003, FR-007, Decisión 5)
# --------------------------------------------------------------------------


def test_sync_step_runs_the_same_command_as_local() -> None:
    """The scheduler runs the very same CLI command as a local run (FR-003)."""
    assert "python -m banking sync" in _run_text("Ejecutar sincronización")


def test_sync_step_captures_output_and_exit_code() -> None:
    """The process output is teed to a log and its exit code preserved."""
    script = _run_text("Ejecutar sincronización")
    assert "tee" in script
    assert "PIPESTATUS[0]" in script
    assert "$GITHUB_OUTPUT" in script
    assert "exit_code=" in script
    assert _step_named("Ejecutar sincronización").get("id") == "sync"


def test_final_step_propagates_the_process_exit_code() -> None:
    """The job's final status equals the sync pipeline's exit code (FR-007)."""
    last = _steps()[-1]
    script = str(last.get("run", "")).strip()
    assert script.startswith("exit "), f"Last step is not the exit propagator: {last.get('name')!r}"
    assert "steps.sync.outputs.exit_code" in script, (
        f"Last step does not propagate the exit code: {last.get('name')!r}"
    )
