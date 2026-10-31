"""Every throwaway Postgres the tests start runs the stack's own Postgres image, so a test passes on the server the
stack runs, and a dump of a test database compares with a dump of the live one. The image is read from the
stack's compose file; each bed names it as a literal (or takes it from scripts/pipeline_chain/throwaway.py), and a
bed that names another version fails here. Read-only: nothing is started.
"""

from __future__ import annotations

import re

import pytest
import yaml

from conftest import ROOT

#: the beds that name the image themselves; a submodule not checked out is skipped
NAMING = (
    "scripts/lib/throwaway-pg.sh",
    "scripts/pipeline_chain/throwaway.py",
    "scripts/lib/report_bed.py",
    "scripts/check-superset-upgrade.sh",
    "apps/qualification/test/db/throwaway-db.sh",
    "apps/results-dashboard/tests/test_project_datasets_db.py",
    "apps/report-generator/tests/conftest.py",
    "apps/report-composer/tests/conftest.py",
)
#: the beds built on scripts/pipeline_chain/throwaway.py, which take its image
BUILT_ON_THROWAWAY = ("scripts/tests/isolation_bed.py", "scripts/lib/report_bed.py")


def stack_image() -> str:
    services = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]
    return services["postgres"]["image"]


@pytest.mark.parametrize("bed", NAMING)
def test_the_bed_uses_the_stacks_postgres_image(bed):
    path = ROOT / bed
    if not path.is_file():
        pytest.skip(f"{bed} is not checked out")
    named = set(re.findall(r"\bpostgres:[0-9][\w.-]*", path.read_text()))
    assert named, f"{bed} names no postgres image: if it now takes it from elsewhere, check it here"
    assert named == {stack_image()}, f"{bed}: {sorted(named)}, the stack runs {stack_image()}"


@pytest.mark.parametrize("bed", BUILT_ON_THROWAWAY)
def test_the_bed_takes_the_image_of_the_python_throwaway(bed):
    assert re.search(r"^from throwaway import .*\bThrowaway\b", (ROOT / bed).read_text(), re.M), bed
