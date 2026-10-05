"""The witness names a dashboard request's project by its slug (witness._bridge). Every project dashboard
is a plugin's since 2026-10-04, aisc-<hex>-<plugin> (apps/results-dashboard charts.plugin_slug); the
pattern knew only aisc-<hex>, so those requests named no project (code review 2026-10-05)."""
from platform_service.ledger.witness import _bridge

PID = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
HEX = PID.replace("-", "")


def test_the_project_dashboard_slug():
    assert _bridge(f"/superset/dashboard/aisc-{HEX}/", "") == PID
    assert _bridge("/api/v1/aisc_comment/", f"dashboard=aisc-{HEX}") == PID


def test_a_plugin_dashboard_slug():
    slug = f"aisc-{HEX}-aisc-plugin-langbite-langbiteevaluationplugin"
    assert _bridge(f"/superset/dashboard/{slug}/", "") == PID
    assert _bridge("/api/v1/aisc_comment/", f"dashboard={slug}") == PID


def test_not_a_dashboard_slug():
    assert _bridge("/superset/dashboard/sales/", "") is None
    assert _bridge("/api/v1/aisc_comment/", f"dashboard=aisc-{HEX[:31]}") is None
