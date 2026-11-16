"""Does any lock of the checkout hold a version inside a published advisory of high or critical severity?

scripts/audit-dependencies.sh runs this; see its header for the options. The files it checks are the ones git
tracks, in this repository and its submodules:

  uv.lock               `uv export --frozen` of its project, the dev group included, local packages left out (each
                        has its own lock)
  requirements*.txt     resolved with `uv pip compile` for Python 3.12, with the overrides.txt beside it when there
                        is one (the image installs it so); requirements-dev*.txt files are test-only and left out
  package-lock.json     `npm audit --omit=dev`: what the built app ships, not its build and test tools

Python advisories come from pip-audit; their severity is the one GitHub's review gives the advisory, read from
OSV (api.osv.dev), and one without a reviewed severity counts as high. npm audit gives its own severity.

An advisory can be accepted for a time in scripts/audit-accepted.txt, one per line:

  <advisory id> <package> <reason, any words> until=YYYY-MM-DD

It is skipped (by its id or any alias) until that day has passed; from then on the audit fails and names it.
Below high, findings are listed and do not fail. Exit status: 0 clean, 1 a finding or an expired or malformed
acceptance, 2 a check that could not run.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ACCEPTED = ROOT / "scripts/audit-accepted.txt"
PIP_AUDIT = "pip-audit==2.10.1"
FAILING = {"HIGH", "CRITICAL"}
OSV = "https://api.osv.dev/v1/vulns/"


@dataclass(frozen=True)
class Acceptance:
    advisory: str
    package: str
    until: dt.date


@dataclass(frozen=True)
class Finding:
    lock: str
    package: str
    version: str
    advisory: str
    severity: str
    fixed_in: str

    def line(self) -> str:
        fix = f"fixed in {self.fixed_in}" if self.fixed_in else "no fixed version"
        return f"{self.lock}  {self.package} {self.version}  {self.advisory}  {self.severity}  {fix}"


def tracked_locks() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--recurse-submodules"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    locks = []
    for path in out.splitlines():
        name = path.rsplit("/", 1)[-1]
        if name in ("uv.lock", "package-lock.json") or (
                re.fullmatch(r"requirements[^/]*\.txt", name) and not name.startswith("requirements-dev")):
            if (ROOT / path).is_file():
                locks.append(path)
    return sorted(locks)


def read_accepted(path: Path) -> tuple[list[Acceptance], list[str]]:
    """The acceptances, and one problem line per malformed line."""
    accepted, problems = [], []
    if not path.is_file():
        return accepted, problems
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.fullmatch(r"(\S+)\s+(\S+)\s+(.+?)\s+until=(\d{4}-\d{2}-\d{2})", line)
        if not m:
            problems.append(f"malformed: line {n} of {path.name}: {line}")
            continue
        try:
            until = dt.date.fromisoformat(m.group(4))
        except ValueError:
            problems.append(f"malformed: line {n} of {path.name}: {line}")
            continue
        accepted.append(Acceptance(m.group(1), m.group(2).lower(), until))
    return accepted, problems


def expired(accepted: list[Acceptance], today: dt.date) -> list[str]:
    return [f"expired: {a.advisory} {a.package} was accepted until {a.until}" for a in accepted if a.until < today]


def _severity(advisory: str, cache: dict[str, str]) -> str:
    if advisory in cache:
        return cache[advisory]
    severity = "UNKNOWN"
    try:
        record = json.load(urllib.request.urlopen(OSV + advisory, timeout=30))
        severity = str((record.get("database_specific") or {}).get("severity") or "").upper() or "UNKNOWN"
        for alias in record.get("aliases") or []:
            if severity == "UNKNOWN" and alias.startswith("GHSA-"):
                ghsa = json.load(urllib.request.urlopen(OSV + alias, timeout=30))
                severity = str((ghsa.get("database_specific") or {}).get("severity") or "").upper() or "UNKNOWN"
    except OSError:
        pass
    cache[advisory] = "MEDIUM" if severity == "MODERATE" else severity
    return cache[advisory]


def _pinned_requirements(lock: str, work: Path) -> Path:
    """The lock or requirements file as one pinned requirements file pip-audit reads without installing."""
    path = ROOT / lock
    out = work / (lock.replace("/", "_") + ".txt")
    if path.name == "uv.lock":
        text = subprocess.run(["uv", "export", "--frozen", "--no-hashes", "--no-emit-project", "--no-header",
                               "--project", str(path.parent)], capture_output=True, text=True, check=True).stdout
        # local packages (the project's own, vendored wheels, path dependencies) have their own locks
        kept = [line for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith(("#", "-e ", "./", "../", "/"))]
        out.write_text("\n".join(kept) + "\n")
    else:
        cmd = ["uv", "pip", "compile", "--quiet", "--no-header", "--python-version", "3.12", str(path), "-o", str(out)]
        overrides = path.parent / "overrides.txt"
        if overrides.is_file():
            cmd += ["--override", str(overrides)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out


def audit_python(lock: str, work: Path, cache: dict[str, str]) -> list[Finding]:
    pinned = _pinned_requirements(lock, work)
    r = subprocess.run(["uvx", PIP_AUDIT, "--no-deps", "--disable-pip", "--progress-spinner", "off", "-f", "json",
                        "-r", str(pinned)], capture_output=True, text=True)
    if r.returncode not in (0, 1) or not r.stdout.strip():
        raise RuntimeError(f"pip-audit could not check {lock}: {r.stderr.strip()[-500:]}")
    findings = []
    for dep in json.loads(r.stdout)["dependencies"]:
        for vuln in dep.get("vulns") or []:
            ids = [vuln["id"], *sorted(vuln.get("aliases") or [])]
            findings.append(Finding(lock, dep["name"].lower(), dep["version"], " ".join(ids),
                                    _severity(vuln["id"], cache), ", ".join(vuln.get("fix_versions") or [])))
    return findings


def audit_node(lock: str) -> list[Finding]:
    folder = (ROOT / lock).parent
    r = subprocess.run(["npm", "audit", "--omit=dev", "--json"], cwd=folder, capture_output=True, text=True)
    try:
        report = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"npm audit could not check {lock}: {r.stderr.strip()[-500:]}") from None
    if "error" in report:
        raise RuntimeError(f"npm audit could not check {lock}: {report['error']}")
    lock_json = json.loads((ROOT / lock).read_text()).get("packages", {})
    findings = []
    for name, vuln in (report.get("vulnerabilities") or {}).items():
        for via in vuln.get("via") or []:
            if not isinstance(via, dict):   # a package vulnerable only through another one: that one is listed
                continue
            advisory = via.get("url", "").rsplit("/", 1)[-1] or str(via.get("source"))
            versions = sorted({p.get("version", "?") for path, p in lock_json.items()
                               if path.rsplit("node_modules/", 1)[-1] == name})
            fixed = vuln.get("fixAvailable")
            fixed_in = f"{fixed['name']} {fixed['version']}" if isinstance(fixed, dict) else (
                "a version in range" if fixed else "")
            findings.append(Finding(lock, name, ",".join(versions), advisory,
                                    "MEDIUM" if via.get("severity") == "moderate" else via.get("severity", "").upper(),
                                    fixed_in))
    return findings


def is_accepted(f: Finding, accepted: list[Acceptance]) -> bool:
    ids = set(f.advisory.split())
    return any(a.advisory in ids and a.package == f.package for a in accepted)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="audit-dependencies.sh")
    ap.add_argument("--list", action="store_true", help="print the files checked and stop")
    ap.add_argument("--only", choices=("python", "node"))
    ap.add_argument("--accepted", type=Path, default=ACCEPTED)
    ap.add_argument("--check-accepted", action="store_true", help="check only the acceptances (no network)")
    args = ap.parse_args(argv)

    locks = [lock for lock in tracked_locks()
             if args.only is None or (lock.endswith("package-lock.json")) == (args.only == "node")]
    if args.list:
        print("\n".join(locks))
        return 0

    accepted, problems = read_accepted(args.accepted)
    problems += expired(accepted, dt.date.today())
    for p in problems:
        print(p)
    if args.check_accepted:
        return 1 if problems else 0

    failing, below = [], []
    cache: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)

        def check(lock: str) -> list[Finding]:
            return audit_node(lock) if lock.endswith("package-lock.json") else audit_python(lock, work, cache)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(check, locks))
        except (RuntimeError, subprocess.CalledProcessError) as e:
            print(f"could not run: {getattr(e, 'stderr', None) or e}")
            return 2
    for f in sorted({f for findings in results for f in findings}, key=Finding.line):
        if not is_accepted(f, accepted):
            (failing if f.severity in FAILING or f.severity == "UNKNOWN" else below).append(f)
    if below:
        print(f"below high, not failing ({len(below)}):")
        for f in below:
            print("  " + f.line())
    if failing:
        print(f"high or critical ({len(failing)}):")
        for f in failing:
            print("  " + f.line())
    print(f"{len(locks)} files checked; {len(failing)} high or critical; {len(problems)} acceptance problems")
    return 1 if failing or problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
