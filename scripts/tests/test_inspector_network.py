"""pgAdmin and schema-docs sit on a network of their own, so no plugin or other service can reach them.

Only caddy (which gates /inspect/* behind sign-in and the platform admin check) and postgres (which
both read as inspector_ro) share it. Read-only: the compose files are copied and resolved with
`docker compose config`; nothing starts."""

import pytest

from test_compose import compose  # noqa: F401  (the resolved-config fixture)

INSPECTORS = {"pgadmin", "schema-docs"}
ALLOWED_NEIGHBOURS = {"caddy", "postgres"}
NETWORK = "inspector"


def _networks(svc):
    nets = svc.get("networks") or {}
    return set(nets) if isinstance(nets, (dict, list)) else set()


def test_wp3_compose_stays_valid(compose):  # noqa: F811
    q, cfg = compose
    assert q.returncode == 0, q.stderr[-2000:]
    assert cfg is not None


def test_wp3_inspector_network_is_declared(compose):  # noqa: F811
    q, cfg = compose
    assert NETWORK in (cfg.get("networks") or {})


@pytest.mark.parametrize("name", sorted(INSPECTORS))
def test_wp3_inspector_is_only_on_its_own_network(compose, name):  # noqa: F811
    q, cfg = compose
    assert _networks(cfg["services"][name]) == {NETWORK}


@pytest.mark.parametrize("name", sorted(ALLOWED_NEIGHBOURS))
def test_wp3_caddy_and_postgres_join_the_inspector_network(compose, name):  # noqa: F811
    q, cfg = compose
    assert NETWORK in _networks(cfg["services"][name])


@pytest.mark.parametrize("name", sorted(INSPECTORS))
def test_wp3_no_other_service_shares_a_network_with_an_inspector(compose, name):  # noqa: F811
    q, cfg = compose
    theirs = _networks(cfg["services"][name])
    for other, svc in cfg["services"].items():
        if other in INSPECTORS | ALLOWED_NEIGHBOURS:
            continue
        # a host-networked service does not join the compose networks at all
        assert not (_networks(svc) & theirs), f"{other} shares {_networks(svc) & theirs} with {name}"


def test_wp3_eval_worker_cannot_reach_an_inspector(compose):  # noqa: F811
    q, cfg = compose
    worker = _networks(cfg["services"]["aisc-eval-worker"])
    for name in INSPECTORS:
        assert not (worker & _networks(cfg["services"][name]))


def test_wp3_only_the_four_are_on_the_inspector_network(compose):  # noqa: F811
    q, cfg = compose
    members = {n for n, s in cfg["services"].items() if NETWORK in _networks(s)}
    assert members == INSPECTORS | ALLOWED_NEIGHBOURS


@pytest.mark.parametrize("name", sorted(INSPECTORS))
def test_wp3_inspectors_still_point_at_postgres(compose, name):  # noqa: F811
    """pgAdmin's server list and schema-docs' PGHOST name `postgres`; it must stay resolvable."""
    q, cfg = compose
    svc = cfg["services"][name]
    assert "postgres" in (svc.get("depends_on") or {})
    assert NETWORK in _networks(cfg["services"]["postgres"])
