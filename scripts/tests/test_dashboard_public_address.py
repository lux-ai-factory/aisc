"""One name for the dashboard's public address: DASHBOARD_EXTERNAL_URL. The launcher (Caddy's
/origins.json) and the reports (report-renderer's REPORT_SUPERSET_PUBLIC_URL) read it; the platform, whose
plugin tiles link to the dashboard, read DASHBOARD_PUBLIC_URL, which nothing set, so an install on another
address got tile links to localhost:8188. Read-only: `docker compose config`."""
import json

import compose_cfg

ADDRESS = "https://dash.example.test"


def test_every_service_that_links_to_the_dashboard_gets_the_one_setting(tmp_path):
    r = compose_cfg.run(tmp_path, env={"DASHBOARD_EXTERNAL_URL": ADDRESS}, drop=("DASHBOARD_",))
    assert r.returncode == 0, r.stderr[-1000:]
    services = json.loads(r.stdout)["services"]
    assert services["platform"]["environment"]["DASHBOARD_EXTERNAL_URL"] == ADDRESS
    assert services["caddy"]["environment"]["DASHBOARD_EXTERNAL_URL"] == ADDRESS
    assert services["report-renderer"]["environment"]["REPORT_SUPERSET_PUBLIC_URL"] == ADDRESS
    assert not [s for s, svc in services.items() if "DASHBOARD_PUBLIC_URL" in (svc.get("environment") or {})]
