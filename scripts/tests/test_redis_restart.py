"""The shared Redis writes its config (the password) to /tmp/redis.conf as root, then runs as the redis user. A
container that restarts (a VM reboot, Docker restarted) runs the same command again on the same filesystem: the
kernel's fs.protected_regular (2 on Ubuntu) refuses root's write to a file the redis user owns in the sticky /tmp,
and Redis restarts for ever. The command must start the same way the second time."""
import shutil
import subprocess

import pytest
import yaml

from conftest import ROOT


def _redis():
    return yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]["redis"]


def test_the_redis_command_starts_again_in_the_same_container():
    if not shutil.which("docker"):
        pytest.skip("docker is not available")
    service = _redis()
    command = service["command"][0].replace("$$", "$")
    tail = "exec docker-entrypoint.sh redis-server /tmp/redis.conf"
    assert command.endswith(tail), command
    setup = command[: -len(tail)] + "true"          # everything but the server, which would not return
    script = f"{setup} && {setup} && grep -c requirepass /tmp/redis.conf && stat -c %U /tmp/redis.conf"
    r = subprocess.run(["docker", "run", "--rm", "-e", "REDIS_PASSWORD=test-password", "--entrypoint", "/bin/sh",
                        service["image"], "-c", script], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["1", "redis"]
