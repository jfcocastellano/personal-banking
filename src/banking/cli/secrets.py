"""CLI handler for the ``banking secrets`` subcommand group."""

from __future__ import annotations

import argparse
import logging
import sys

from banking.config.secret_store import ConfigurationError, SecretStore

logger = logging.getLogger(__name__)


def add_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Register the ``secrets`` subcommand and its sub-subcommands.

    Args:
        subparsers: The subparsers action from the parent ArgumentParser.
    """
    secrets_parser = subparsers.add_parser(
        "secrets",
        help="Manage encrypted configuration secrets",
    )
    secrets_subparsers = secrets_parser.add_subparsers(
        dest="secrets_command",
        metavar="COMMAND",
    )

    set_parser = secrets_subparsers.add_parser(
        "set",
        help="Encrypt a value and store it in the SecretStore",
    )
    set_parser.add_argument("key", help="Secret name (e.g. MY_API_KEY)")
    set_parser.add_argument("value", help="Plaintext value to encrypt")
    set_parser.set_defaults(func=_handle_set)

    secrets_parser.set_defaults(func=_handle_secrets_root)


def _handle_secrets_root(args: argparse.Namespace) -> int:
    """Print usage when ``banking secrets`` is called without a sub-subcommand."""
    print("Usage: banking secrets set KEY VALUE")
    print()
    print("Encrypt VALUE and store it in the SecretStore under KEY.")
    return 1


def _handle_set(args: argparse.Namespace) -> int:
    """Encrypt args.value and write it to the SecretStore under args.key.

    Returns:
        Exit code: 0 on success, 1 on ConfigurationError, 2 on I/O error.
    """
    try:
        store = SecretStore()
    except ConfigurationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        store.set(args.key, args.value)
    except OSError as exc:
        print(f"ERROR: Could not write to SecretStore: {exc}", file=sys.stderr)
        return 2

    logger.info("Secret '%s' stored successfully.", args.key)
    return 0


def handle(args: argparse.Namespace) -> int:
    """Dispatch to the appropriate secrets sub-handler.

    Args:
        args: Parsed arguments with ``func`` set by argparse ``set_defaults``.

    Returns:
        Exit code.
    """
    if hasattr(args, "func") and args.func is not _handle_secrets_root:
        return int(args.func(args))
    return _handle_secrets_root(args)
