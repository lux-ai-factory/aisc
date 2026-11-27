"""The platform's connection rules live in one domain module (platform_service/connections.py), and the
routes are split by job: connections, targets, run passes and allowed hosts each have a router. The split
changes no route: every (method, path) served before is served after, and nothing new appears. Read-only."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import platform_service

#: every (method, path) the platform's routers served before the split
ROUTES = {
    ('DELETE', '/internal/run-passes'),
    ('DELETE', '/projects/{slug}'),
    ('DELETE', '/projects/{slug}/agents/{system}'),
    ('DELETE', '/projects/{slug}/allowed-hosts/{entry}'),
    ('DELETE', '/projects/{slug}/connections/{name}'),
    ('DELETE', '/projects/{slug}/connections/{name}/tool'),
    ('DELETE', '/projects/{slug}/helpers/{name}'),
    ('DELETE', '/projects/{slug}/llm/providers/{provider}'),
    ('DELETE', '/projects/{slug}/llm/systems/{system}'),
    ('DELETE', '/projects/{slug}/members/{subject}'),
    ('DELETE', '/projects/{slug}/runs/{evaluation_pid}'),
    ('GET', '/authz/admin'),
    ('GET', '/authz/projects/{ref}'),
    ('GET', '/authz/schema'),
    ('GET', '/authz/witness'),
    ('GET', '/internal/facade/{pid}/{name}/a2a/.well-known/agent-card.json'),
    ('GET', '/internal/facade/{pid}/{name}/oip/v2'),
    ('GET', '/internal/facade/{pid}/{name}/oip/v2/health/{which}'),
    ('GET', '/internal/facade/{pid}/{name}/oip/v2/models/{model}'),
    ('GET', '/internal/facade/{pid}/{name}/oip/v2/models/{model}/ready'),
    ('GET', '/internal/facade/{pid}/{name}/openai/v1/models'),
    ('GET', '/internal/projects/{pid}/connections/{name}'),
    ('GET', '/internal/projects/{pid}/helpers'),
    ('GET', '/internal/projects/{pid}/helpers/{name}/models'),
    ('GET', '/internal/projects/{pid}/helpers/{name}/resolve'),
    ('GET', '/internal/projects/{pid}/llm/{system}'),
    ('GET', '/internal/projects/{pid}/network-rule'),
    ('GET', '/internal/projects/{pid}/proof-files/{file_id}'),
    ('GET', '/internal/projects/{pid}/targets/{key}/connection'),
    ('GET', '/internal/projects/{pid}/targets/{key}/reachable'),
    ('GET', '/internal/run-passes/trace'),
    ('GET', '/ledger/projects'),
    ('GET', '/projects'),
    ('GET', '/projects/{project}/system-versions'),
    ('GET', '/projects/{project}/system-versions/latest'),
    ('GET', '/projects/{slug}'),
    ('GET', '/projects/{slug}/allowed-hosts'),
    ('GET', '/projects/{slug}/catalogue'),
    ('GET', '/projects/{slug}/catalogue/api/metric/'),
    ('GET', '/projects/{slug}/catalogue/api/project-dimensions'),
    ('GET', '/projects/{slug}/catalogue/api/tags/'),
    ('GET', '/projects/{slug}/catalogue/api/tool/'),
    ('GET', '/projects/{slug}/catalogue/api/tool/{entry}/install-info'),
    ('GET', '/projects/{slug}/catalogue/control/{control}/export'),
    ('GET', '/projects/{slug}/connections'),
    ('GET', '/projects/{slug}/connections/protocols'),
    ('GET', '/projects/{slug}/connections/{name}/models'),
    ('GET', '/projects/{slug}/connectivity'),
    ('GET', '/projects/{slug}/dashboards/open'),
    ('GET', '/projects/{slug}/declared-charts'),
    ('GET', '/projects/{slug}/evidence'),
    ('GET', '/projects/{slug}/helpers'),
    ('GET', '/projects/{slug}/ledger/events'),
    ('GET', '/projects/{slug}/ledger/export'),
    ('GET', '/projects/{slug}/ledger/head'),
    ('GET', '/projects/{slug}/llm'),
    ('GET', '/projects/{slug}/llm/providers/{provider}/models'),
    ('GET', '/projects/{slug}/members'),
    ('GET', '/projects/{slug}/reports'),
    ('GET', '/projects/{slug}/runs/{evaluation_plugin}/trace-ref/{sha256}'),
    ('GET', '/projects/{slug}/targets'),
    ('GET', '/projects/{slug}/targets/assessable-by'),
    ('PATCH', '/projects/{project}/system-versions/{pid}'),
    ('POST', '/internal/facade/{pid}/{name}/a2a'),
    ('POST', '/internal/facade/{pid}/{name}/aisc/ask'),
    ('POST', '/internal/facade/{pid}/{name}/oip/v2/models/{model}/infer'),
    ('POST', '/internal/facade/{pid}/{name}/openai/v1/chat/completions'),
    ('POST', '/internal/projects/{pid}/connections/fingerprints'),
    ('POST', '/internal/projects/{pid}/connections/{name}/run-keys'),
    ('POST', '/internal/projects/{pid}/ledger/events'),
    ('POST', '/internal/projects/{pid}/proof-files'),
    ('POST', '/internal/projects/{pid}/targets/{key}/run-keys'),
    ('POST', '/internal/run-passes'),
    ('POST', '/ledger/beacon'),
    ('POST', '/ledger/corrections'),
    ('POST', '/ledger/reanchor'),
    ('POST', '/projects'),
    ('POST', '/projects/{project}/system-versions'),
    ('POST', '/projects/{project}/system-versions/abandon'),
    ('POST', '/projects/{slug}/catalogue'),
    ('POST', '/projects/{slug}/catalogue/api/tool/{entry}/install'),
    ('POST', '/projects/{slug}/catalogue/update'),
    ('POST', '/projects/{slug}/connections/{name}/target'),
    ('POST', '/projects/{slug}/connections/{name}/test'),
    ('POST', '/projects/{slug}/dashboards/again'),
    ('POST', '/projects/{slug}/evidence/review'),
    ('POST', '/projects/{slug}/helpers/{name}/test'),
    ('POST', '/projects/{slug}/members'),
    ('POST', '/projects/{slug}/targets/sync'),
    ('PUT', '/projects/{slug}/agents/{system}'),
    ('PUT', '/projects/{slug}/allowed-hosts/{entry}'),
    ('PUT', '/projects/{slug}/catalogue/local/{package}/dimensions'),
    ('PUT', '/projects/{slug}/connections/{name}'),
    ('PUT', '/projects/{slug}/connections/{name}/tool'),
    ('PUT', '/projects/{slug}/evidence/links'),
    ('PUT', '/projects/{slug}/helpers/{name}'),
    ('PUT', '/projects/{slug}/llm/providers/{provider}'),
    ('PUT', '/projects/{slug}/llm/systems/{system}'),
    ('PUT', '/projects/{slug}/members/{subject}'),
    ('PUT', '/projects/{slug}/retention'),
    ('PUT', '/projects/{slug}/targets/{key}/file'),
    # who holds a part of a task (added after the split; the inventory lists every route the platform serves)
    ('GET', '/projects/{project}/work/{kind}/{subject}'),
    ('PUT', '/projects/{project}/work/holds'),
    ('POST', '/projects/{project}/work/{kind}/{subject}/parts/{part}/take'),
    ('POST', '/projects/{project}/work/{kind}/{subject}/parts/{part}/release'),
    ('POST', '/projects/{project}/work/{kind}/{subject}/parts/{part}/offer'),
    ('POST', '/projects/{project}/work/{kind}/{subject}/parts/{part}/accept'),
    ('POST', '/projects/{project}/work/{kind}/{subject}/parts/{part}/decline'),
    ('POST', '/projects/{project}/work/{kind}/{subject}/parts/{part}/take-over'),
    # how many people check each kind of task, and submitting a task and signing it off
    ('GET', '/projects/{project}/work/rules'),
    ('PUT', '/projects/{project}/work/rules/{kind}'),
    ('POST', '/projects/{project}/work/preset'),
    ('POST', '/projects/{project}/work/{kind}/{subject}/submit'),
    ('POST', '/projects/{project}/work/{kind}/{subject}/sign'),
    # the work pages: a project's board and one person's own list
    ('GET', '/projects/{project}/work'),
    ('GET', '/work/mine'),
}

ROUTE_MODULE = Path(platform_service.__file__).parent / "routes/connections.py"


def test_every_route_is_still_served():
    from platform_service.routes import ROUTERS
    now = {(m, r.path) for router in ROUTERS for r in router.routes for m in (getattr(r, "methods", None) or ())}
    assert ROUTES - now == set(), "routes no longer served"
    assert now - ROUTES == set(), "routes added by the split"


def test_the_connection_rules_have_a_domain_module():
    assert importlib.util.find_spec("platform_service.connections") is not None, \
        "no platform_service.connections: the connection rules still live in the route module"
    from platform_service import connections
    for name in ("connection_fields", "connection_view", "descriptor_of", "call_descriptor_of",
                 "adapter_connection_of", "secret_values"):
        assert hasattr(connections, name), name


def test_the_route_module_holds_no_domain_rule():
    src = ROUTE_MODULE.read_text()
    kept = [rule for rule in ("def descriptor_of", "def _merged_secret_headers", "def _fingerprint_of",
                              "def secret_values") if rule in src]
    assert kept == [], f"domain rules still in routes/connections.py: {kept}"
    assert len(src.splitlines()) < 400, f"routes/connections.py is {len(src.splitlines())} lines"


def test_targets_run_passes_and_allowed_hosts_have_their_own_routers():
    for name in ("run_passes", "targets", "allowed_hosts"):
        assert importlib.util.find_spec(f"platform_service.routes.{name}") is not None, name
