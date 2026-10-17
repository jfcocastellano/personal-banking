"""Security guards for the GitHub Actions workflow definitions (IT7).

These tests only read and parse the YAML text of every workflow file: no network
call, no GitHub API access (constitution Principle III).

Guard semantics: the assertions that inspect `${{ secrets.* }}` usage are
vacuously true while no workflow declares secrets. `.github/workflows/sync.yml`
starts declaring them in T010 of ``specs/007-scheduler-github-actions/tasks.md``;
from that moment on they are effective, and they stay green afterwards.

Contract: ``specs/007-scheduler-github-actions/contracts/sync-workflow.md`` § 4.1
(secret exposure) and § 6 invariants 8, 12 and 14.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

import yaml

WORKFLOW_DIR = Path(".github/workflows")
GITIGNORE = Path(".gitignore")
CI_WORKFLOW = WORKFLOW_DIR / "ci.yml"

SECRET_EXPRESSION = re.compile(r"\$\{\{\s*secrets\.[A-Za-z0-9_]+\s*\}\}")

# Shapes that must never appear in a workflow file (Principle IV).
CREDENTIAL_SHAPES = (
    "-----BEGIN",
    "Bearer ",
    "password=",
    "enc:",
)

# Files that must never be committable, expressed as gitignore patterns.
CREDENTIAL_FILES = (".env", ".env.local", "private_key.pem")

CI_REQUIRED_TOOLS = ("pip-audit", "ruff check", "ruff format", "mypy", "pytest")


def _workflow_files() -> list[Path]:
    """Return every workflow definition, failing if there is none."""
    files = sorted(WORKFLOW_DIR.glob("*.yml"))
    assert files, f"No workflow definitions found in {WORKFLOW_DIR}"
    return files


def _load(path: Path) -> dict[str, Any]:
    """Load a workflow file as a mapping, normalising the `on` key."""
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict), f"{path} is not a YAML mapping"
    # PyYAML resolves a bare `on:` key to the boolean True (YAML 1.1).
    if "on" not in data and True in data:
        data["on"] = data.pop(True)
    return data


def _all_steps(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten every step of every job in the workflow."""
    steps: list[dict[str, Any]] = []
    for job in workflow.get("jobs", {}).values():
        steps.extend(job.get("steps", []))
    return steps


def _gitignore_patterns() -> list[str]:
    """Return the meaningful patterns declared in .gitignore."""
    lines = GITIGNORE.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.startswith("#")]


def test_no_secret_expression_is_interpolated_into_a_run_block() -> None:
    """Secrets must reach scripts through `env:`, never through `run:`.

    A `${{ secrets.* }}` expression inside `run:` is expanded before the
    platform masks the log, so a stray `echo` would leak the value (FR-010).
    """
    offenders: list[str] = []
    for path in _workflow_files():
        for index, step in enumerate(_all_steps(_load(path))):
            run_block = step.get("run")
            if isinstance(run_block, str) and SECRET_EXPRESSION.search(run_block):
                offenders.append(f"{path}: step {index} ({step.get('name', '?')})")
    assert not offenders, f"Secret expression interpolated into run: {offenders}"


def test_workflows_contain_no_literal_credentials() -> None:
    """No workflow file may contain a credential shape (Principle IV)."""
    offenders: list[str] = []
    for path in _workflow_files():
        text = path.read_text(encoding="utf-8")
        for shape in CREDENTIAL_SHAPES:
            if shape in text:
                offenders.append(f"{path}: {shape!r}")
    assert not offenders, f"Credential-like literal found in workflows: {offenders}"


def test_gitignore_excludes_every_credential_file() -> None:
    """`.env`, its variants and private keys must never be committable (FR-004)."""
    patterns = _gitignore_patterns()
    unignored = [
        name
        for name in CREDENTIAL_FILES
        if not any(fnmatch(name, pattern) for pattern in patterns if not pattern.startswith("!"))
    ]
    assert not unignored, f"Credential files not ignored by .gitignore: {unignored}"


def test_ci_workflow_still_gates_every_commit() -> None:
    """`ci.yml` keeps its triggers and its five gates (FR-011)."""
    workflow = _load(CI_WORKFLOW)
    triggers = workflow.get("on", {})
    assert "main" in triggers.get("push", {}).get("branches", []), "CI lost its push trigger"
    assert "main" in triggers.get("pull_request", {}).get("branches", []), (
        "CI lost its pull_request trigger"
    )
    commands = "\n".join(
        step["run"] for step in _all_steps(workflow) if isinstance(step.get("run"), str)
    )
    positions = [commands.index(tool) for tool in CI_REQUIRED_TOOLS if tool in commands]
    assert len(positions) == len(CI_REQUIRED_TOOLS), "CI lost one of its quality gates"
    assert positions == sorted(positions), "CI gates are no longer in the required order"


def test_sync_workflow_is_a_separate_file_from_ci() -> None:
    """The scheduler lives in its own workflow, not inside the CI pipeline (FR-011)."""
    assert (WORKFLOW_DIR / "sync.yml") in _workflow_files()
    ci_triggers = set(_load(CI_WORKFLOW).get("on", {}))
    assert "schedule" not in ci_triggers, "The scheduled sync must not live in ci.yml"
    assert "workflow_dispatch" not in ci_triggers, "The manual sync must not live in ci.yml"
