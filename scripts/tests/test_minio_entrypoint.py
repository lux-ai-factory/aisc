"""MinIO sets aside a stored server config it cannot read, instead of waiting for it forever.

A volume whose server config was written by another MinIO version can hold a key the stack's release does
not know (sts_trusted_proxies under identity_ldap). That release then logs `found invalid keys (...)` and
`Waiting for LDAP to be initialized` again and again and never becomes healthy. infra/minio/entrypoint.sh
starts the server, watches its log, and on that exact pair moves .minio.sys/config/config.json aside
(buckets, objects and IAM users stay) and starts it once more. These tests run the script with a fake
`minio` on PATH; nothing is built here."""
import os
import signal
import stat
import subprocess
import time

import pytest
import yaml

from conftest import ROOT

ENTRYPOINT = ROOT / "infra/minio/entrypoint.sh"
DOCKERFILE = ROOT / "infra/minio/Dockerfile"

INVALID_KEYS = (
    "Error: Unable to load LDAP configuration (LDAP configuration will be disabled!): found invalid keys "
    "(sts_trusted_proxies= ) for 'identity_ldap:_' sub-system, use 'mc admin config reset myminio "
    "identity_ldap:_' to fix invalid keys (*fmt.wrapError)")
WAITING = "INFO: Waiting for LDAP to be initialized.. (retrying in 2.06693937s)"
NORMAL_START = "MinIO Object Storage Server\nAPI: http://172.18.0.2:9000  http://127.0.0.1:9000"
UNRELATED_ERROR = "ERROR Unable to use the drive /data: drive path full"

# What the fake prints on a launch, and how it ends: `hang` waits to be stopped (as the real server does
# while it waits for LDAP), a number is its exit code.
FAKE_MINIO = r"""#!/bin/sh
state="$FAKE_MINIO_STATE"
launch=$(( $(cat "$state/launches" 2>/dev/null || echo 0) + 1 ))
echo "$launch" > "$state/launches"
echo "$$" > "$state/pid-$launch"
printf '%s\n' "$*" > "$state/args-$launch"
trap 'echo stopped > "$state/stopped-$launch"; exit 0' TERM
cat "$state/says-$launch"
end=$(cat "$state/ends-$launch")
if [ "$end" = hang ]; then
  while :; do sleep 0.1; done
fi
exit "$end"
"""


@pytest.fixture
def bed(tmp_path):
    """A data folder holding a stored config, IAM users and a bucket, and a fake minio on PATH."""
    data = tmp_path / "data"
    config = data / ".minio.sys/config"
    (config / "config.json").mkdir(parents=True)
    (config / "config.json/xl.meta").write_text("stored server config")
    (config / "iam/users/alice").mkdir(parents=True)
    (data / "datasets/report.csv").mkdir(parents=True)
    (data / "datasets/report.csv/xl.meta").write_text("an object")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "minio"
    fake.write_text(FAKE_MINIO)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    state = tmp_path / "state"
    state.mkdir()

    class Bed:
        pass
    b = Bed()
    b.data, b.config, b.state = data, config, state
    b.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_MINIO_STATE": str(state)}

    def launch(n, says, ends):
        (state / f"says-{n}").write_text(says + "\n")
        (state / f"ends-{n}").write_text(str(ends))
    b.launch = launch

    def start():
        return subprocess.Popen(["sh", str(ENTRYPOINT), "server", str(data), "--console-address", ":9001"],
                                env=b.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    b.start = start

    def run():
        proc = start()
        out, _ = proc.communicate(timeout=30)
        return proc, out
    b.run = run
    b.launches = lambda: int((state / "launches").read_text()) if (state / "launches").exists() else 0
    b.set_aside = lambda: sorted(p.name for p in config.iterdir() if p.name.startswith("config.json.set-aside-"))
    return b


def test_invalid_keys_then_waiting_sets_the_config_aside_and_restarts_once(bed):
    bed.launch(1, f"{INVALID_KEYS}\n{WAITING}\n{WAITING}", "hang")
    bed.launch(2, NORMAL_START, 0)
    proc, out = bed.run()

    assert proc.returncode == 0, out
    assert bed.launches() == 2
    assert (bed.state / "stopped-1").exists(), "the first server was stopped"
    [name] = bed.set_aside()
    assert name.startswith("config.json.set-aside-") and name.endswith("Z") and len(name) > len("config.json.set-aside-")
    assert (bed.config / name / "xl.meta").read_text() == "stored server config"
    assert not (bed.config / "config.json").exists()
    assert (bed.config / "iam/users/alice").is_dir()
    assert (bed.data / "datasets/report.csv/xl.meta").read_text() == "an object"
    line = (f"minio: its stored server config was written by another MinIO version (sts_trusted_proxies=); "
            f"set it aside as {bed.config / name} and started with defaults (buckets, objects and users kept)")
    assert line in out.splitlines(), out
    # every line minio printed is still shown
    assert INVALID_KEYS in out and WAITING in out and "MinIO Object Storage Server" in out
    # the second launch replaced the script itself (exec), with the same arguments
    assert (bed.state / "pid-2").read_text().strip() == str(proc.pid)
    assert (bed.state / "args-2").read_text() == (bed.state / "args-1").read_text()
    assert (bed.state / "args-2").read_text().strip() == f"server {bed.data} --console-address :9001"


def test_a_clean_start_moves_nothing(bed):
    bed.launch(1, NORMAL_START, 0)
    proc, out = bed.run()

    assert proc.returncode == 0, out
    assert bed.launches() == 1
    assert bed.set_aside() == []
    assert (bed.config / "config.json/xl.meta").exists()
    assert "MinIO Object Storage Server" in out and "minio: its stored server config" not in out


def test_an_unrelated_error_moves_nothing_and_exits_with_minios_code(bed):
    bed.launch(1, f"{UNRELATED_ERROR}\n{WAITING}", 3)
    proc, out = bed.run()

    assert proc.returncode == 3, out
    assert bed.launches() == 1
    assert bed.set_aside() == []
    assert UNRELATED_ERROR in out and "minio: its stored server config" not in out


def test_invalid_keys_on_the_second_start_too_does_not_loop(bed):
    bed.launch(1, f"{INVALID_KEYS}\n{WAITING}", "hang")
    bed.launch(2, f"{INVALID_KEYS}\n{WAITING}", 5)
    proc, out = bed.run()

    assert proc.returncode == 5, out
    assert bed.launches() == 2
    assert len(bed.set_aside()) == 1
    assert out.count("minio: its stored server config") == 1


def test_a_stop_during_the_watched_start_stops_minio_promptly(bed):
    """docker stop sends TERM to the script (PID 1 in the container): it passes it on to minio."""
    bed.launch(1, NORMAL_START, "hang")
    proc = bed.start()
    deadline = time.time() + 10
    while not (bed.state / "pid-1").exists() and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.3)
    proc.send_signal(signal.SIGTERM)
    out, _ = proc.communicate(timeout=5)

    assert (bed.state / "stopped-1").exists(), out
    assert bed.launches() == 1
    assert bed.set_aside() == []


def test_the_image_starts_the_server_through_the_script_and_the_bucket_job_keeps_its_own():
    text = DOCKERFILE.read_text()
    assert "COPY entrypoint.sh /usr/local/bin/minio-entrypoint.sh" in text
    assert 'ENTRYPOINT ["/usr/local/bin/minio-entrypoint.sh"]' in text
    for f in ["docker-compose-infra.development.yml", "docker-compose-infra.staging.yml",
              "docker-compose.engine-standalone.yml"]:
        s = yaml.safe_load((ROOT / f).read_text())["services"]
        assert "entrypoint" not in s["minio"], f
        assert s["minio"]["command"].startswith("server /data"), f
        assert s["make_buckets"]["entrypoint"].strip().startswith("/bin/sh -c"), f
