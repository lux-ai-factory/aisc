"""The eval worker runs a fixed number of plugins at a time, each child under a memory ceiling, inside a
capped container, and runs the sweep of lost runs from its own beat. A run key lasts as long as a test may
run plus a margin, not half a day."""
import re

import yaml

from conftest import ROOT

COMPOSE = ROOT / "docker-compose.development.yml"


def services() -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"]


def worker() -> dict:
    return services()["aisc-eval-worker"]


def worker_hard_limit_s() -> int:
    text = (ROOT / "apps/eval/aisc_eval/celery_app.py").read_text()
    return int(re.search(r'"task_time_limit":\s*(\d+)', text).group(1))


def test_the_worker_runs_a_fixed_number_of_plugins_with_a_memory_ceiling_and_the_sweep():
    command = worker()["command"]
    assert "--concurrency=" in command and "--max-memory-per-child=" in command and "--beat" in command, command


def test_the_worker_container_is_capped():
    service = worker()
    assert service.get("mem_limit") and service.get("cpus") and int(service.get("pids_limit") or 0) > 0


def test_a_run_key_lasts_no_longer_than_a_test_may_run():
    ttl = re.search(r":-(\d+)\}", services()["platform"]["environment"]["CONNECTIONS_RUN_KEY_TTL_S"]).group(1)
    assert int(ttl) == worker_hard_limit_s() + 300
