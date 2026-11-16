"""The eval worker may set the firewall that keeps plugin tests behind its egress proxy, and gains nothing
else: NET_ADMIN is the only capability it holds beyond Docker's defaults (of which it keeps only those it uses)
and no-new-privileges still holds. Read-only: the compose files
are resolved with `docker compose config`; nothing is started."""

import compose_cfg
import json

from test_compose import compose  # noqa: F401  (fixture)

#: what Docker gives a container unless told otherwise
DOCKER_DEFAULT_CAPABILITIES = {"CHOWN", "DAC_OVERRIDE", "FSETID", "FOWNER", "MKNOD", "NET_RAW", "SETGID", "SETUID",
                               "SETFCAP", "SETPCAP", "NET_BIND_SERVICE", "SYS_CHROOT", "KILL", "AUDIT_WRITE"}


def test_the_eval_worker_may_set_its_own_firewall_and_nothing_else(compose):  # noqa: F811
    _q, cfg = compose
    assert cfg is not None, "the compose files do not resolve"
    worker = cfg["services"]["aisc-eval-worker"]
    caps, options = worker.get("cap_add"), worker.get("security_opt") or []  # never the whole service: env holds secrets
    assert worker.get("cap_drop") == ["ALL"]
    assert set(caps) - DOCKER_DEFAULT_CAPABILITIES == {"NET_ADMIN"}
    assert "no-new-privileges:true" in options


def test_the_operators_extra_plugin_hosts_reach_the_worker(compose):  # noqa: F811
    _q, cfg = compose
    env = cfg["services"]["aisc-eval-worker"].get("environment") or {}
    names = sorted(env)  # names only: a value may be a secret
    assert "PLUGIN_EGRESS_ALLOWED_HOSTS" in names


def test_by_default_plugins_may_reach_the_dataset_host(tmp_path):
    """StrongREJECT reads its datasets from raw.githubusercontent.com; an operator may narrow or extend the list."""
    for files, settings in ((compose_cfg.FILES, compose_cfg.SETTINGS), (["docker-compose.engine-standalone.yml"], None)):
        done = compose_cfg.run(tmp_path, files=files, drop=("PLUGIN_EGRESS",), settings_file=settings)
        assert done.returncode == 0, done.stderr[-500:]
        env = json.loads(done.stdout)["services"]["aisc-eval-worker"].get("environment") or {}
        assert env.get("PLUGIN_EGRESS_ALLOWED_HOSTS") == "raw.githubusercontent.com", files


def test_an_operator_may_narrow_the_extra_hosts_to_none(tmp_path):
    done = compose_cfg.run(tmp_path, drop=("PLUGIN_EGRESS",), env={"PLUGIN_EGRESS_ALLOWED_HOSTS": ""})
    assert done.returncode == 0, done.stderr[-500:]
    env = json.loads(done.stdout)["services"]["aisc-eval-worker"].get("environment") or {}
    assert env.get("PLUGIN_EGRESS_ALLOWED_HOSTS") == ""
