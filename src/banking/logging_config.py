"""Process-wide logging configuration (constitution: Mandatory observability).

Library modules only create loggers; this module is what actually gives them a
handler. It is called once by the CLI entry point, so importing ``banking`` never
reconfigures the host application's logging.
"""

import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
"""Record format mandated by the project constitution."""

_LEVEL_ENV_VAR = "LOG_LEVEL"
_DEFAULT_LEVEL_NAME = "INFO"


def resolve_level(level: str | None = None) -> int:
    """Resolve a log level name to its numeric logging value.

    The lookup is case-insensitive and never raises: an unrecognised name falls
    back to ``INFO`` so a typo in ``LOG_LEVEL`` cannot abort a sync run.

    Args:
        level: Explicit level name. When ``None``, the ``LOG_LEVEL`` environment
            variable is used.

    Returns:
        The matching numeric level, or ``logging.INFO`` when the name is missing
        or unknown.
    """
    name = (level or os.environ.get(_LEVEL_ENV_VAR) or _DEFAULT_LEVEL_NAME).strip().upper()
    return logging.getLevelNamesMapping().get(name, logging.INFO)


def configure_logging(level: str | None = None) -> None:
    """Install a formatted stderr handler on the root logger.

    Without this call the root logger owns no handler, so every ``logger.info``
    record is discarded and WARNING/ERROR records reach stderr through the bare
    ``lastResort`` handler with no timestamp, level or logger name.

    Args:
        level: Explicit level name, overriding ``LOG_LEVEL``. Defaults to
            ``INFO`` (constitution: ``DEBUG`` in local development, ``INFO`` in
            CI and production).
    """
    logging.basicConfig(format=LOG_FORMAT, level=resolve_level(level))
