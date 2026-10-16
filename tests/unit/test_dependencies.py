"""Runtime dependency declarations must match what ``src/`` actually imports.

Constitution Principle VII (Simplicity & Minimalism) requires every declaration
to earn its place: a package listed in ``pyproject.toml`` but never imported is
dead weight, and a package imported but not listed makes ``pip install .``
produce an unimportable package for anyone who does not install
``requirements.txt`` first.
"""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
_PYPROJECT = _ROOT / "pyproject.toml"
_OWN_PACKAGE = "banking"


def _normalise(distribution: str) -> str:
    """PEP 503 name normalisation, so ``PyJWT`` and ``pyjwt`` compare equal."""
    return re.sub(r"[-_.]+", "-", distribution).lower()


def _declared_distributions() -> set[str]:
    """Distribution names declared in ``[project].dependencies``."""
    with _PYPROJECT.open("rb") as handle:
        manifest = tomllib.load(handle)
    return {
        _normalise(re.split(r"[<>=!~ ]", requirement, maxsplit=1)[0])
        for requirement in manifest["project"]["dependencies"]
    }


def _imported_modules() -> set[str]:
    """Top-level modules imported by ``src/``, excluding the stdlib and itself."""
    modules: set[str] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return {
        module
        for module in modules
        if module not in sys.stdlib_module_names and module != _OWN_PACKAGE
    }


def _imported_distributions() -> set[str]:
    """Distribution names that provide the third-party modules ``src/`` imports."""
    providers = packages_distributions()
    distributions: set[str] = set()
    for module in _imported_modules():
        distributions.update(providers.get(module, []))
    return {_normalise(distribution) for distribution in distributions}


def test_the_scan_finds_modules_and_declarations() -> None:
    """Guards the checks below against silently scanning nothing."""
    assert _imported_distributions(), "no third-party imports were found under src/"
    assert _declared_distributions(), "no dependencies were found in pyproject.toml"


def test_every_imported_third_party_module_is_declared() -> None:
    """Otherwise ``pip install .`` yields a package that cannot be imported."""
    undeclared = _imported_distributions() - _declared_distributions()
    assert not undeclared, (
        f"src/ imports {sorted(undeclared)}, which pyproject.toml does not declare"
    )


def test_every_declared_dependency_is_imported() -> None:
    """Constitution Principle VII: no speculative or unused dependencies."""
    unused = _declared_distributions() - _imported_distributions()
    assert not unused, f"pyproject.toml declares {sorted(unused)}, which src/ never imports"
