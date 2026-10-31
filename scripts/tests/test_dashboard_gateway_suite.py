"""dashboard-gateway's own unit tests run.

test_gateway_identity.py (the signature, issuer, expiry and azp checks of the token that names a
Superset user) needs PyJWT and cryptography, and test_superset_gateway_config.py (Superset's session
following the gateway's) Flask and Flask-Login, which the root suite does not install, and neither
verify.sh nor the root suite ran it, so the azp check was guarded only by a wiring test. This runs
it in its own uv environment, with the command of its row in scripts/suites.py, which verify.sh --modules
runs too. The row pins these packages to the versions the dashboard image has, since PyJWT's behaviour
differs between releases (a newer one refuses an empty keys address that 2.8.0 accepts)."""
import re
import shutil
import subprocess
import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import suites  # noqa: E402

ROW = next(s for s in suites.SUITES if s.name == "dashboard gateway")


def test_the_gateways_own_tests_pass():
    if not shutil.which("uv"):
        pytest.skip("uv is not installed")
    r = subprocess.run(["bash", "-c", ROW.command], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    ran = re.search(r"Ran (\d+) tests?", r.stderr)
    assert ran and int(ran.group(1)) >= 29, r.stderr[-1000:]


def test_the_row_pins_the_dashboard_images_versions():
    assert ROW.dir == "dashboard-gateway"
    assert "test_gateway_identity test_superset_gateway_config" in ROW.command
    for pin in ("pyjwt==2.8.0", "cryptography==50.0.2", "flask==2.3.3", "flask-login==0.6.3", "werkzeug==3.0.6"):
        assert f"--with {pin}" in ROW.command, pin
