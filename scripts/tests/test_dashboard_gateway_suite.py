"""dashboard-gateway's own unit tests run.

test_gateway_identity.py (the signature, issuer, expiry and azp checks of the token that names a
Superset user) needs PyJWT and cryptography, and test_superset_gateway_config.py (Superset's session
following the gateway's) Flask and Flask-Login, which the root suite does not install, and neither
verify.sh nor the root suite ran it, so the azp check was guarded only by a wiring test. This runs
it in its own uv environment, and verify.sh --modules runs it too. Both pin these packages to the versions
the dashboard image has, since PyJWT's behaviour differs between releases (a newer one refuses
an empty keys address that 2.8.0 accepts)."""
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

#: the versions in the aisc-results-dashboard image (pip show pyjwt cryptography flask flask-login werkzeug)
IMAGE_PINS = "--with pyjwt==2.8.0 --with cryptography==50.0.2 --with flask==2.3.3 --with flask-login==0.6.3 --with werkzeug==3.0.6"
TESTS = "test_gateway_identity test_superset_gateway_config"
COMMAND = f"uv run --no-project --quiet {IMAGE_PINS} python -m unittest -q {TESTS}"


def test_the_gateways_own_tests_pass():
    if not shutil.which("uv"):
        pytest.skip("uv is not installed")
    r = subprocess.run(COMMAND.split(), cwd=ROOT / "dashboard-gateway", capture_output=True, text=True,
                       timeout=600, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    ran = re.search(r"Ran (\d+) tests?", r.stderr)
    assert ran and int(ran.group(1)) >= 29, r.stderr[-1000:]


def test_verify_runs_them_with_the_modules():
    rows = (ROOT / "scripts/verify.sh").read_text().split("<<'MODULES'", 1)[1].split("\nMODULES", 1)[0]
    row = next((line for line in rows.splitlines() if line.startswith("dashboard gateway|")), "")
    assert row.startswith("dashboard gateway|dashboard-gateway||") and TESTS in row, row
    assert IMAGE_PINS in row, row
