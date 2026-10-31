"""A test bed's project database (`tpg_project_db`) is made by the platform's own provisioning, so it holds
what a provisioned one holds: every template file, tracked, and ledger.platform_action filled from the
registry (a hand-made copy left it empty, so ledger.emit refused nothing in the beds)."""
from __future__ import annotations

import subprocess
import sys

from conftest import ROOT

TPG = ROOT / "scripts/lib/throwaway-pg.sh"


def test_a_bed_project_database_is_the_one_provision_makes():
    sys.path.insert(0, str(ROOT / "platform"))
    from platform_service.ledger.registry import REGISTRY

    pid = "5e1f0c2a-7b3d-4c8e-9f10-2a3b4c5d6e7f"
    db = "project_" + pid.replace("-", "")
    script = f"""
set -e
. "{TPG}"
tpg_start bed-provision
tpg_init_platform "{ROOT}"
tpg_project_db {pid} >/dev/null
tpg_project_db {pid}
tpg_su {db} -tA -c "SELECT string_agg(name, ',' ORDER BY name) FROM provision.template_migration"
tpg_su {db} -tA -c "SELECT string_agg(name, ',' ORDER BY name) FROM ledger.platform_action"
"""
    done = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stderr[-1500:]
    name, templates, actions = done.stdout.strip().splitlines()[-3:]
    assert name == db
    assert templates == ",".join(sorted(p.name for p in (ROOT / "platform/project-template").glob("*.sql")))
    assert actions == ",".join(sorted(n for n, a in REGISTRY.items() if a.origin != "app"))
