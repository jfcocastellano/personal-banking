"""Tests for the GitHub Actions CI workflow configuration."""

from pathlib import Path

import yaml

CI_WORKFLOW = Path(".github/workflows/ci.yml")


def _load_workflow() -> dict:  # type: ignore[type-arg]
    assert CI_WORKFLOW.exists(), f"CI workflow file not found: {CI_WORKFLOW}"
    with CI_WORKFLOW.open(encoding="utf-8") as f:
        return yaml.safe_load(f)  # type: ignore[no-any-return]


def test_ci_workflow_file_exists() -> None:
    """The CI workflow YAML file must exist."""
    assert CI_WORKFLOW.exists(), f"Missing: {CI_WORKFLOW}"


def test_ci_triggers_on_push_to_main() -> None:
    """The workflow must trigger on push to main."""
    workflow = _load_workflow()
    push_branches = workflow.get("on", {}).get("push", {}).get("branches", [])
    assert "main" in push_branches


def test_ci_triggers_on_pull_request_to_main() -> None:
    """The workflow must trigger on pull_request to main."""
    workflow = _load_workflow()
    pr_branches = workflow.get("on", {}).get("pull_request", {}).get("branches", [])
    assert "main" in pr_branches


def test_ci_steps_contain_required_tools_in_order() -> None:
    """The CI job must include pip-audit, ruff check, ruff format, mypy, pytest in order."""
    workflow = _load_workflow()
    jobs = workflow.get("jobs", {})
    assert jobs, "No jobs defined in CI workflow"

    # Flatten all step run commands
    all_steps: list[dict] = []  # type: ignore[type-arg]
    for job in jobs.values():
        all_steps.extend(job.get("steps", []))

    run_commands = [s.get("run", "") for s in all_steps if "run" in s]
    combined = "\n".join(run_commands)

    required_tools = ["pip-audit", "ruff check", "ruff format", "mypy", "pytest"]
    for tool in required_tools:
        assert tool in combined, f"CI step for '{tool}' not found in workflow"

    # Verify order: each tool must appear after the previous one
    positions = [combined.index(tool) for tool in required_tools]
    assert positions == sorted(positions), (
        f"CI tools are not in the required order: {required_tools}"
    )
