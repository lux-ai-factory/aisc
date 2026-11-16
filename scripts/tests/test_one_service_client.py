"""Internal service calls go through one client, aisc_service_client: a timeout always, no redirects, one set of
errors. The callers below import it and no HTTP library of their own. Calls to addresses a person configured stay
on the guarded transport and are not listed here.

Read-only: the source files as text.
"""

import re

from conftest import ROOT

MOVED = [
    "platform/platform_service/evidence.py", "platform/platform_service/engine_components.py",
    "platform/platform_service/publisher.py", "platform/platform_service/reports.py",
    "platform/platform_service/dashboard_bridge.py", "platform/platform_service/targets.py",
    "apps/eval/aisc_eval/service/api_client.py", "apps/eval/aisc_eval/service/helpers.py",
    "apps/eval/aisc_eval/service/run_pass.py",
    "apps/report-composer/report_composer/anchor.py", "apps/report-composer/report_composer/renderer_client.py",
    "apps/report-composer/report_composer/declared_charts.py",
    "apps/control-objectives/src/aisc_control_objectives/upstream.py",
]
OWN_HTTP = re.compile(r"^\s*(import requests|import urllib\.request|import httpx|from urllib import request|"
                      r"from httpx import|from requests import)", re.M)


def test_the_one_client_exists():
    assert (ROOT / "shared/identity/aisc_service_client/__init__.py").is_file(), "no aisc_service_client module"


def test_the_internal_callers_use_the_one_client():
    own = [f for f in MOVED if "aisc_service_client" not in (ROOT / f).read_text()
           or OWN_HTTP.search((ROOT / f).read_text())]
    assert own == [], "these call other services in their own way"
