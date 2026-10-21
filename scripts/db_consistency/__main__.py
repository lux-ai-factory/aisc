"""Run the checks and print them the way the verify-*.sh scripts do.

    python -m db_consistency [--dsn CONNINFO] [--only C1,C3]

The connection comes from --dsn, else DB_CONSISTENCY_DSN, else libpq's PG* environment. It
must be a superuser (listing databases, reading every schema). Exit status 1 on any FAIL.
"""

from __future__ import annotations

import argparse
import os
import sys

from .checks import ALL_CHECKS
from .cluster import Cluster
from .findings import FAIL, WARN

COLOR = {"PASS": "32", FAIL: "31", WARN: "33"}


def line(level: str, text: str) -> str:
    if os.environ.get("NO_COLOR"):
        return f"  {level} {text}"
    return f"  \033[{COLOR[level]}m{level}\033[0m {text}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="db_consistency", description=__doc__.splitlines()[0])
    ap.add_argument("--dsn", default=os.environ.get("DB_CONSISTENCY_DSN", ""))
    ap.add_argument("--only", default="", help="comma-separated check ids, e.g. C1,C3")
    args = ap.parse_args(argv)
    cl = Cluster(args.dsn)
    wanted = {c.strip().upper() for c in args.only.split(",") if c.strip()}

    passed = warned = failed = 0
    for check in ALL_CHECKS:
        if wanted and check.id not in wanted:
            continue
        print(f"{check.id} {check.name}")
        try:
            found = check.run(cl)
        except Exception as exc:  # a check that cannot run is a failure, not a pass
            first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
            print(line(FAIL, f"{check.id} could not run: {first}"))
            failed += 1
            continue
        if not found:
            print(line("PASS", check.title))
            passed += 1
        for f in found:
            print(line(f.level, f"{f.check} {f.message}"))
            failed += f.level == FAIL
            warned += f.level == WARN
        sys.stdout.flush()

    print(f"\npassed: {passed}  warned: {warned}  failed: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
