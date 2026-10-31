"""The checks' common parts: what a check returns, the allow and deny rules, the run and its report."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Answer:
    """What a probe got: ok when the stack let it through; text is its output, or why it was refused."""
    ok: bool
    text: str = ""


@dataclass(frozen=True)
class Result:
    ok: bool
    detail: str = ""


PASS = Result(True)


@dataclass(frozen=True)
class Check:
    name: str
    run: Callable[[], Result]


#: a refusal for a privilege, as PostgreSQL words it; any other error proves nothing about the grants
PRIVILEGE_REFUSED = "permission denied"


def first_error(text: str) -> str:
    """The line that says what went wrong, or the whole text when none does."""
    return next((line.strip() for line in text.splitlines() if "ERROR" in line or "FATAL" in line), text.strip()
                ) or "no answer"


def allow(probe: Callable[[], Answer]) -> Result:
    got = probe()
    return PASS if got.ok else Result(False, f"was refused: {first_error(got.text)}")


def deny(probe: Callable[[], Answer], control: Callable[[], Answer],
         refused_for: Callable[[str], bool] = lambda text: PRIVILEGE_REFUSED in text) -> Result:
    """Passes when the control succeeds and the probe is then refused for the right reason (refused_for). A
    control that fails (no login, no such table) means the refusal could have any cause, so it proves nothing."""
    checked = control()
    if not checked.ok:
        return Result(False, f"the control failed, so a refusal would prove nothing: {first_error(checked.text)}")
    got = probe()
    if got.ok:
        return Result(False, "was ALLOWED")
    if not refused_for(got.text):
        return Result(False, f"not refused for a privilege: {first_error(got.text)}")
    return PASS


def run_checks(checks: list[Check], out=None) -> tuple[int, int]:
    """Runs each check on its own and prints PASS or FAIL with the whole detail; (passed, failed)."""
    out = out or sys.stdout
    green, red, plain = ("\033[32m", "\033[31m", "\033[0m") if out.isatty() else ("", "", "")
    passed = failed = 0
    for check in checks:
        try:
            result = check.run()
        except Exception as error:  # one check's error is its own failure, never the whole run's
            result = Result(False, f"{type(error).__name__}: {error}")
        if result.ok:
            passed += 1
            print(f"  {green}PASS{plain} {check.name}", file=out, flush=True)
        else:
            failed += 1
            print(f"  {red}FAIL{plain} {check.name}", file=out, flush=True)
            for line in result.detail.splitlines() or [""]:
                print(f"       {line}", file=out, flush=True)
    print(f"\npassed: {passed}  failed: {failed}", file=out, flush=True)
    return passed, failed


#: every group: its name and the function that lists its checks for a stack (filled in by __main__)
GROUPS: dict[str, Callable] = {}


def parse(argv: list[str]) -> argparse.Namespace:
    """Strict: an unknown group or option stops the run (argparse exits 2)."""
    parser = argparse.ArgumentParser(prog="python3 -m stackcheck", allow_abbrev=False,
                                     description="Checks against the running stack.")
    parser.add_argument("group", choices=sorted(GROUPS))
    parser.add_argument("--only", action="append", default=[], metavar="NAME",
                        help="run only this check (again for more); its name as the list prints it")
    return parser.parse_args(argv)
