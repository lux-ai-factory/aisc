"""scripts/lib/probe-project.sh: the project verify-sso and verify-rbac act in. A project keeps its ledger
database for good, deleted or not, so the probe is made once, by its fixed name, and found again by every
later run instead of being made and deleted per run."""
from conftest import ROOT

LIB = ROOT / "scripts/lib/probe-project.sh"


def test_the_probe_has_a_fixed_name_and_is_never_deleted():
    text = LIB.read_text()
    assert 'PROBE_NAME="verify probe"' in text
    assert "DELETE" not in text and "probe_project_cleanup" not in text


def test_no_check_calls_the_retired_cleanup():
    for script in ("verify-sso.sh", "verify-rbac.sh"):
        assert "probe_project_cleanup" not in (ROOT / "scripts" / script).read_text(), script


def test_rbac_reuses_the_project_it_is_a_stranger_to():
    """verify-rbac also needs a project the account is not in: an admin's, found by name, made only once."""
    text = (ROOT / "scripts/verify-rbac.sh").read_text()
    assert "verify rbac scratch" in text
    assert not any("DELETE" in line and "/projects/" in line for line in text.splitlines())
