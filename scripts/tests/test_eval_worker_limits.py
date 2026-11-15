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


def _default(text: str) -> int:
    return int(re.search(r":-(\d+)\}", text).group(1))


def test_the_tests_running_at_once_each_at_their_process_cap_leave_room_in_the_container():
    """Each test runs as a user of its own, so the process cap is per test: the worker's concurrency times
    that cap stays under the container's process limit, with room for the worker, its children and installs."""
    service = worker()
    per_test = _default(service["environment"]["PLUGIN_MAX_PROCESSES"])
    at_once = _default(re.search(r"--concurrency=(\$\{[^}]*\})", service["command"]).group(1))
    assert per_test * at_once <= int(service["pids_limit"]) - 256, (per_test, at_once, service["pids_limit"])
    eval_default = re.search(r'"PLUGIN_MAX_PROCESSES":\s*(\d+)',
                             (ROOT / "apps/eval/aisc_eval/plugin_process.py").read_text()).group(1)
    assert int(eval_default) == per_test
