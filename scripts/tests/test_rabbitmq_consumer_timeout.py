"""RabbitMQ may hold a task's delivery unacknowledged longer than the worker may run the task. The worker
acknowledges a task when it ends (task_acks_late); RabbitMQ's default consumer timeout (30 min) closed the
channel of a 78-minute jailbreak run and handed the test out again, which ran it a second time against the
system under test (4 November 2026). The timeout is set above the worker's own hard limit."""
import re

import yaml

from conftest import ROOT

CONF = ROOT / "infra/rabbitmq/conf.d/10-aisc.conf"


def consumer_timeout_ms() -> int:
    found = re.search(r"^\s*consumer_timeout\s*=\s*(\d+)\s*$", CONF.read_text(), re.M)
    assert found, f"no consumer_timeout in {CONF.relative_to(ROOT)}"
    return int(found.group(1))


def worker_hard_limit_s() -> int:
    text = (ROOT / "apps/eval/aisc_eval/celery_app.py").read_text()
    return int(re.search(r'"task_time_limit":\s*(\d+)', text).group(1))


def test_rabbitmq_waits_longer_than_the_worker_may_run_a_task():
    assert consumer_timeout_ms() > worker_hard_limit_s() * 1000


def test_every_compose_file_with_rabbitmq_mounts_the_setting():
    found = 0
    for path in sorted(ROOT.glob("docker-compose*.yml")):
        services = (yaml.safe_load(path.read_text()) or {}).get("services") or {}
        if "image" not in (services.get("rabbitmq") or {}):
            continue                       # no RabbitMQ here, or an overlay (admin ports) on one defined elsewhere
        found += 1
        build = services["rabbitmq"].get("build") or {}
        if build:
            # the baked overlay's image carries the setting at the same place instead of a mount
            dockerfile = ROOT / build["context"] / build.get("dockerfile", "Dockerfile")
            assert re.search(r"^COPY\b.*\bconf\.d/10-aisc\.conf /etc/rabbitmq/conf\.d/10-aisc\.conf$",
                             dockerfile.read_text(), re.M), path.name
            continue
        volumes = services["rabbitmq"].get("volumes") or []
        assert "./infra/rabbitmq/conf.d/10-aisc.conf:/etc/rabbitmq/conf.d/10-aisc.conf:ro" in volumes, path.name
    assert found >= 1
