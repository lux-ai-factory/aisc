"""Every compose service rotates its log at 10 MB times 5 and runs within memory, CPU and process limits, in three
sizes: small for the proxies and caches, large for the engine, the databases and the agents, medium for the rest.

Read-only: `docker compose config` on copies of the compose files.
"""

import pytest

import compose_cfg

ROTATION = {"max-size": "10m", "max-file": "5"}
SMALL = {"caddy", "redis", "dashboard-redis", "oauth2-proxy", "aisc-webapp"}
LARGE = {"aisc-backend", "postgres", "keycloak", "dashboard", "qualification-agents", "control-objectives"}
#: the workers' limits are set by the run lifecycle, not by these sizes (the declarations worker runs the run
#: worker's image, one plugin at a time)
OWN_SIZE = {"aisc-eval-worker", "aisc-eval-declarations-worker"}

FILE_SETS = {
    "development": dict(files=compose_cfg.FILES, settings_file=compose_cfg.SETTINGS),
    "standalone": dict(files=["docker-compose.engine-standalone.yml"], settings_file=None),
}


@pytest.mark.parametrize("which", FILE_SETS)
def test_every_service_rotates_its_log(tmp_path, which):
    s = compose_cfg.config(tmp_path, "inspect", **FILE_SETS[which])["services"]
    bad = sorted(n for n, v in s.items() if (v.get("logging") or {}).get("driver") != "json-file"
                 or (v.get("logging") or {}).get("options") != ROTATION)
    assert bad == [], "these services keep their log unbounded"


def test_every_service_has_memory_cpu_and_process_limits(tmp_path):
    s = compose_cfg.config(tmp_path, "inspect")["services"]
    missing = sorted(n for n, v in s.items() if not (v.get("mem_limit") and v.get("cpus") and v.get("pids_limit")))
    assert missing == [], "these services run without limits"


def test_the_limits_follow_the_three_sizes(tmp_path):
    s = compose_cfg.config(tmp_path, "inspect")["services"]
    wrong = sorted((n, s[n].get("pids_limit")) for n in s if n not in OWN_SIZE and s[n].get("pids_limit") !=
                   (128 if n in SMALL else 512 if n in LARGE else 256))
    assert wrong == []
