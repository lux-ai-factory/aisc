"""Reading a plugin's manifest and running its form hooks have a queue of their own, served by a worker process of
their own, one task at a time, so a configure page never waits behind the runs. Every shipped compose file that
starts the eval worker also starts that one. It runs plugin code just as the run worker does, so it is kept apart
the same way: the firewall capability, a first process that reaps, the same egress hosts, no database credential.
The run worker never reads that queue.

Read-only: the compose files and the two sources that name the queue, as text.
"""
import re
import shlex

import pytest
import yaml

from conftest import ROOT

QUEUE = "plugin-declarations"
RUN_WORKER = "aisc-eval-worker"
DECLARATIONS_WORKER = "aisc-eval-declarations-worker"
FILES = ["docker-compose.development.yml", "docker-compose.staging.yml", "docker-compose.engine-standalone.yml"]
#: environment names that would give a process a database credential or address
DATABASE_NAME = re.compile(r"^(DB_|DATABASE|POSTGRES|PG)|DATABASE_URL|_DB_|MIGRAT")


def services(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text())["services"]


def argv(service: dict) -> list[str]:
    """The command's words; a `sh -c "..."` command's inner words."""
    command = service.get("command") or []
    words = shlex.split(command) if isinstance(command, str) else list(command)
    if words[:2] == ["sh", "-c"] and len(words) == 3:
        words = shlex.split(words[2])
    return words


def option(words: list[str], short: str, long: str) -> list[str]:
    """Every value given to the option, as `-Q x`, `--queues x` or `--queues=x`."""
    found = []
    for i, word in enumerate(words):
        if word in (short, long) and i + 1 < len(words):
            found.append(words[i + 1])
        elif word.startswith(long + "="):
            found.append(word.split("=", 1)[1])
    return found


def environment(service: dict) -> dict:
    env = service.get("environment") or {}
    return env if isinstance(env, dict) else dict(e.split("=", 1) for e in env)


def test_the_eval_worker_and_the_engine_name_the_same_queue():
    assert f'"{QUEUE}"' in (ROOT / "apps/eval/aisc_eval/celery_app.py").read_text()
    assert f'"{QUEUE}"' in (ROOT / "apps/backend/aisc_backend/plugin_declarations.py").read_text()


@pytest.mark.parametrize("name", FILES)
def test_a_worker_of_its_own_reads_only_the_declarations_queue_one_task_at_a_time(name):
    s = services(name)
    assert RUN_WORKER in s, f"{name} starts no eval worker"
    assert DECLARATIONS_WORKER in s, f"{name} starts no worker for manifests and form hooks"
    words = argv(s[DECLARATIONS_WORKER])
    assert "worker" in words and any("aisc_eval.celery_worker" in w for w in words), words
    assert option(words, "-Q", "--queues") == [QUEUE], words
    assert option(words, "-c", "--concurrency") == ["1"], words
    assert "--beat" not in words and "-B" not in words, "the run worker runs the sweep's beat, once"


@pytest.mark.parametrize("name", FILES)
def test_the_run_worker_never_reads_the_declarations_queue(name):
    words = argv(services(name)[RUN_WORKER])
    assert option(words, "-Q", "--queues") == [], words
    assert QUEUE not in " ".join(words)


@pytest.mark.parametrize("name", FILES)
def test_the_declarations_worker_is_kept_apart_as_the_run_worker_is(name):
    s = services(name)
    run, declarations = s[RUN_WORKER], s[DECLARATIONS_WORKER]
    assert "NET_ADMIN" in (declarations.get("cap_add") or []), "the plugin firewall cannot be set without it"
    assert declarations.get("init") is True, "nothing reaps what a plugin leaves"
    assert set(run.get("security_opt") or []) <= set(declarations.get("security_opt") or [])
    assert set(run.get("cap_add") or []) <= set(declarations.get("cap_add") or [])
    env = environment(declarations)
    assert env.get("PLUGIN_EGRESS_ALLOWED_HOSTS") == environment(run).get(
        "PLUGIN_EGRESS_ALLOWED_HOSTS", "${PLUGIN_EGRESS_ALLOWED_HOSTS-raw.githubusercontent.com}")
    assert sorted(n for n in env if DATABASE_NAME.search(n)) == []
    assert {n: v for n, v in env.items() if n != "PLUGIN_EGRESS_ALLOWED_HOSTS"} == {
        n: v for n, v in environment(run).items() if n != "PLUGIN_EGRESS_ALLOWED_HOSTS"}
    assert declarations.get("volumes") == run.get("volumes")
    assert declarations.get("networks") == run.get("networks")


@pytest.mark.parametrize("name", FILES)
def test_the_declarations_worker_runs_the_run_workers_image_without_building_it_again(name):
    s = services(name)
    assert s[DECLARATIONS_WORKER]["image"] == s[RUN_WORKER]["image"]
    assert "build" not in s[DECLARATIONS_WORKER], "two builds of one tag race"
