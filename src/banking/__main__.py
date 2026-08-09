"""Entry point for ``python -m banking``."""

import argparse
import sys

from banking.cli import secrets as secrets_cmd
from banking.cli import sync as sync_cmd


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="banking",
        description="Personal finance automation — synchronise bank transactions to Google Sheets.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    secrets_cmd.add_parser(subparsers)
    sync_cmd.add_parser(subparsers)
    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand handler."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        print("Usage: banking <command>")
        print()
        print("Commands:")
        print("  secrets   Manage encrypted configuration secrets")
        print("  sync      Fetch this month's ING movements and write them to Google Sheets")
        print()
        print("Run 'banking <command> --help' for more information.")
        sys.exit(0)

    if args.command == "secrets":
        exit_code = secrets_cmd.handle(args)
        sys.exit(exit_code)

    if args.command == "sync":
        exit_code = sync_cmd.handle(args)
        sys.exit(exit_code)

    parser.print_usage(sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
