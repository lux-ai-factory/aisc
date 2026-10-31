"""python3 -m stackcheck <group> [--only NAME ...], from the scripts folder: see the package's docstring."""

from __future__ import annotations

import sys

from . import db_access, harness
from .stack import Stack

harness.GROUPS.setdefault("db-access", db_access.checks)


def main(argv: list[str]) -> int:
    try:
        args = harness.parse(argv)
    except SystemExit as stop:  # argparse has said why
        return int(stop.code or 0)
    checks = harness.GROUPS[args.group](Stack())
    names = [c.name for c in checks]
    unknown = [name for name in args.only if name not in names]
    if unknown:
        print(f"{args.group} has no check {', '.join(map(repr, unknown))}; it has:", *names, sep="\n  ",
              file=sys.stderr)
        return 2
    if args.only:
        checks = [c for c in checks if c.name in args.only]
    _, failed = harness.run_checks(checks)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
