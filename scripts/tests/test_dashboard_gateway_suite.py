"""dashboard-gateway's own unit tests run.

test_gateway_identity.py (the signature, issuer, expiry and azp checks of the token that names a
Superset user) needs PyJWT and cryptography, which the root suite does not install, and neither
verify.sh nor the root suite ran it, so the azp check was guarded only by a wiring test. This runs
it in its own uv environment, and verify.sh --modules runs it too."""
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

COMMAND = "uv run --no-project --quiet --with pyjwt --with cryptography python -m unittest -q test_gateway_identity"


def test_the_gateways_own_tests_pass():
    if not shutil.which("uv"):
        pytest.skip("uv is not installed")
    r = subprocess.run(COMMAND.split(), cwd=ROOT / "dashboard-gateway", capture_output=True, text=True,
                       timeout=600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    ran = re.search(r"Ran (\d+) tests?", r.stderr)
    assert ran and int(ran.group(1)) >= 11, r.stderr[-1000:]


def test_verify_runs_them_with_the_modules():
    rows = (ROOT / "scripts/verify.sh").read_text().split("<<'MODULES'", 1)[1].split("\nMODULES", 1)[0]
    row = next((line for line in rows.splitlines() if line.startswith("dashboard gateway|")), "")
    assert row.startswith("dashboard gateway|dashboard-gateway||") and "test_gateway_identity" in row, row
