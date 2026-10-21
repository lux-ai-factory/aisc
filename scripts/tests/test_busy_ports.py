"""Busy browser ports, really occupied: a listening socket on each, and the ports the real compose files publish.

No stand-in for the port check here: aisc.py's own port_is_free decides, as it does for a person whose
launcher, dashboard or sign-in port is held by another program. A test whose ports are already taken on the
machine running it (an AISC stack, another program) cannot occupy them itself, so it is skipped there.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import socket
import subprocess
import uuid

import pytest

import compose_cfg
from conftest import aisc_py

#: Keycloak is published on loopback only; the other browser ports on every address
LOOPBACK_ONLY = {8081}


def host_of(port):
    return "127.0.0.1" if port in LOOPBACK_ONLY else "0.0.0.0"


def skip_unless_free(m, *ports):
    """The ports a test occupies or expects a role to land on must be free before it starts."""
    busy = [port for port in ports if not m.port_is_free(port, host_of(port))]
    if busy:
        pytest.skip(f"already taken on this machine: {', '.join(map(str, busy))}")


@contextlib.contextmanager
def occupied(*ports, host=None):
    """A real listening socket on each port, on the address Docker would publish it on (or `host`)."""
    with contextlib.ExitStack() as stack:
        for port in ports:
            listener = stack.enter_context(socket.socket())
            try:
                listener.bind((host or host_of(port), port))
            except OSError:
                pytest.skip(f"port {port} cannot be occupied on this machine")
            listener.listen()
        yield


@pytest.fixture
def published(tmp_path):
    """What the real compose files publish, read with `docker compose config` (nothing is started)."""
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    variables = tuple(port.variable for port in aisc_py().BROWSER_PORTS)
    r = compose_cfg.run(tmp_path, drop=variables)
    if r.returncode != 0:
        pytest.skip(f"docker compose cannot read the files here: {r.stderr.strip()[-300:]}")
    return aisc_py().published_ports(json.loads(r.stdout))


def settle(m, published):
    return m.settle_ports(published, set(), {}, True, m.port_is_free)


def no_problem_names(problems, *ports):
    """Before the infrastructure ports are opt-in, one held on a developer's machine is a problem of its own;
    none may name a browser port the test occupied."""
    return not [problem for problem in problems for port in ports if f"Port {port} " in problem]


def test_busy_launcher_dashboard_and_sign_in_ports_are_moved(published):
    m = aisc_py()
    skip_unless_free(m, 8100, 8188, 8081, 8110, 8198, 8091)
    with occupied(8100, 8188, 8081):
        settings, problems, moved = settle(m, published)
    assert settings["HOMEPAGE_PORT_EXTERNAL"] == "8110"
    assert settings["DASHBOARD_PORT_EXTERNAL"] == "8198"
    assert settings["KEYCLOAK_PORT_EXTERNAL"] == "8091"
    assert settings["LAUNCHER_EXTERNAL_URL"] == "http://localhost:8110/"
    assert settings["DASHBOARD_EXTERNAL_URL"] == "http://localhost:8198"
    assert settings["KEYCLOAK_URL_EXTERNAL"] == "http://localhost:8091"
    assert len(moved) == 3
    assert no_problem_names(problems, 8100, 8188, 8081)


def test_a_busy_first_fallback_is_skipped(published):
    m = aisc_py()
    skip_unless_free(m, 8100, 8110, 8120)
    with occupied(8100, 8110):
        settings, problems, _moved = settle(m, published)
    assert settings["HOMEPAGE_PORT_EXTERNAL"] == "8120"
    assert settings["LAUNCHER_EXTERNAL_URL"] == "http://localhost:8120/"
    assert no_problem_names(problems, 8100, 8110)


def test_a_listener_on_loopback_only_still_blocks_the_sign_in_port(published):
    """Keycloak is published on 127.0.0.1: a program there blocks it, whatever the other addresses hold."""
    m = aisc_py()
    skip_unless_free(m, 8081, 8091)
    with occupied(8081, host="127.0.0.1"):
        settings, problems, _moved = settle(m, published)
    assert settings["KEYCLOAK_PORT_EXTERNAL"] == "8091"
    assert settings["KEYCLOAK_URL_EXTERNAL"] == "http://localhost:8091"
    assert no_problem_names(problems, 8081)


def test_a_busy_engine_port_is_moved(published):
    """Port 80 cannot be opened without root on Linux, so a stand-in container holds it, as a stack or a
    forwarder left from an earlier run would."""
    m = aisc_py()
    skip_unless_free(m, 80, 8080)
    name = f"aisc-test-busy-80-{uuid.uuid4().hex[:8]}"
    try:
        run = subprocess.run(["docker", "run", "-d", "--name", name, "-p", "80:80", "nginx:1.27-alpine"],
                             capture_output=True, text=True, timeout=300)
        if run.returncode != 0:
            pytest.skip(f"a stand-in container cannot hold port 80 here: {run.stderr.strip()[-300:]}")
        settings, problems, _moved = settle(m, published)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
    assert settings["ENGINE_PORT"] == "8080"
    assert settings["API_URL_EXTERNAL"] == "http://localhost:8080"
    assert no_problem_names(problems, 80)
