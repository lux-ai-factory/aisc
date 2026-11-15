"""The eval worker may set the firewall that keeps plugin tests behind its egress proxy, and gains nothing
else: NET_ADMIN is its only added capability and no-new-privileges still holds. Read-only: the compose files
are resolved with `docker compose config`; nothing is started."""

from test_compose import compose  # noqa: F401  (fixture)


def test_the_eval_worker_may_set_its_own_firewall_and_nothing_else(compose):  # noqa: F811
    _q, cfg = compose
    assert cfg is not None, "the compose files do not resolve"
    worker = cfg["services"]["aisc-eval-worker"]
    caps, options = worker.get("cap_add"), worker.get("security_opt") or []  # never the whole service: env holds secrets
    assert caps == ["NET_ADMIN"]
    assert "no-new-privileges:true" in options


def test_the_operators_extra_plugin_hosts_reach_the_worker(compose):  # noqa: F811
    _q, cfg = compose
    env = cfg["services"]["aisc-eval-worker"].get("environment") or {}
    names = sorted(env)  # names only: a value may be a secret
    assert "PLUGIN_EGRESS_ALLOWED_HOSTS" in names
