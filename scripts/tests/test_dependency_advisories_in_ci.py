"""CI fails on a known advisory in any lock of the checkout, submodules included, and dependabot watches every root
lock and the submodule pointers. The audit script lists every lock and requirements file it checks (development
requirement files left out) and honours an accepted advisory only until its date.

Read-only: the workflow and dependabot files as text; the audit script is asked only for its list and for the
check of the accepted file, which reach no network.
"""

import yaml

from conftest import ROOT, run

CI = ROOT / ".github/workflows/ci.yml"
AUDIT = ROOT / "scripts/audit-dependencies.sh"


def test_ci_fails_on_a_known_advisory():
    jobs = yaml.safe_load(CI.read_text())["jobs"]
    assert "advisories" in jobs, "CI has no job that checks the locks against published advisories"
    steps = jobs["advisories"]["steps"]
    assert any("scripts/audit-dependencies.sh" in (s.get("run") or "") for s in steps)
    assert any((s.get("with") or {}).get("submodules") == "recursive" for s in steps)


def test_dependabot_watches_every_root_lock():
    cfg = ROOT / ".github/dependabot.yml"
    assert cfg.is_file(), "no dependabot configuration in the root repository"
    watched = {(u["package-ecosystem"], u["directory"]) for u in yaml.safe_load(cfg.read_text())["updates"]}
    assert {("uv", "/platform"), ("uv", "/shared/identity"), ("uv", "/apps/report-composer"),
            ("gitsubmodule", "/"), ("github-actions", "/")} - watched == set()


def test_the_audit_lists_every_lock_and_leaves_out_development_files():
    assert AUDIT.is_file(), "no scripts/audit-dependencies.sh"
    r = run(["bash", str(AUDIT), "--list"])
    assert r.returncode == 0, r.stderr[-1500:]
    listed = set(r.stdout.split())
    assert {"platform/uv.lock", "apps/webapp/package-lock.json",
            "apps/qualification/services/prefill/requirements.txt"} - listed == set()
    assert not any(p.endswith("requirements-dev.txt") for p in listed)


def test_an_expired_acceptance_is_named_and_fails(tmp_path):
    assert AUDIT.is_file(), "no scripts/audit-dependencies.sh"
    accepted = tmp_path / "accepted.txt"
    accepted.write_text("GHSA-xxxx-xxxx-xxxx somepackage a reason until=2000-01-01\n")
    r = run(["bash", str(AUDIT), "--accepted", str(accepted), "--check-accepted"])
    assert r.returncode == 1 and "GHSA-xxxx-xxxx-xxxx" in r.stdout and "expired" in r.stdout
