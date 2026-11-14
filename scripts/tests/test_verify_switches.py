"""scripts/verify-switches.sh: after a restart, the stack's switches, its ledger mode, its Redis and its logs are
what the strict switches and the leak fixes promise.

1. every running container given AUTH_ENABLED or LEDGER_MODE holds a switch word and is running (a service that
   refused its switch has exited);
2. the latest `ledger.mode` event the platform wrote at start reads the stack's mode and was delivered to the
   platform's log without a rejection;
3. the shared Redis refuses a client without its password (NOAUTH);
4. no container's log since the restart holds a token-shaped string. Only the count is printed, never a match.

The script is run with a fake `docker` on PATH that answers from the test's scenario, so no stack is touched.
"""
import os
import subprocess

from conftest import ROOT

SCRIPT = ROOT / "scripts/verify-switches.sh"
TOKEN = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzb21lb25lIn0.c2lnbmF0dXJlLXZhbHVl"

FAKE_DOCKER = r"""#!/usr/bin/env bash
case "$1" in
  ps)
    printf 'stack-platform\tplatform\nstack-dashboard\tdashboard\nstack-redis\tredis\nstack-postgres\tpostgres\n' ;;
  inspect)
    c="${@: -1}"
    case "$*" in
      *State.Status*) if [ "$c" = "$FAKE_EXITED" ]; then echo exited; else echo running; fi ;;
      *Config.Env*)
        case "$c" in
          stack-platform) printf 'AUTH_ENABLED=true\nLEDGER_MODE=%s\nPLATFORM_RW_PASSWORD=not-printed\n' "$FAKE_PLATFORM_MODE" ;;
          stack-dashboard) printf 'LEDGER_MODE=record\n' ;;
          *) printf 'PATH=/bin\n' ;;
        esac ;;
    esac ;;
  exec)
    case "$*" in
      *redis-cli*) echo "$FAKE_REDIS" ;;
      *psql*) echo "$FAKE_MODE_ROW" ;;
    esac ;;
  logs)
    c="${@: -1}"
    if [ "$c" = stack-dashboard ]; then printf 'GET /x 200\n%s\n' "$FAKE_LOG_LINE" >&2; fi ;;
esac
exit 0
"""


def run(tmp_path, **scenario):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AISC_PROJECT": "stack",
           "FAKE_PLATFORM_MODE": "record", "FAKE_EXITED": "", "FAKE_REDIS": "NOAUTH Authentication required.",
           "FAKE_MODE_ROW": "record|t|", "FAKE_LOG_LINE": "a quiet line"}
    env.update(scenario)
    return subprocess.run(["bash", str(SCRIPT), "--since", "2026-11-14T10:00:00"], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=60)


def test_a_sound_stack_passes(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL" not in result.stdout


def test_a_bad_switch_on_a_running_container_fails(tmp_path):
    result = run(tmp_path, FAKE_PLATFORM_MODE="recrod")
    assert result.returncode != 0
    assert "stack-platform" in result.stdout and "LEDGER_MODE" in result.stdout


def test_a_service_that_exited_fails(tmp_path):
    result = run(tmp_path, FAKE_EXITED="stack-dashboard")
    assert result.returncode != 0
    assert "stack-dashboard" in result.stdout


def test_the_latest_mode_must_be_the_stacks_and_delivered(tmp_path):
    assert run(tmp_path, FAKE_MODE_ROW="off|t|").returncode != 0
    assert run(tmp_path, FAKE_MODE_ROW="record|f|").returncode != 0
    assert run(tmp_path, FAKE_MODE_ROW="record|t|emitter").returncode != 0
    assert run(tmp_path, FAKE_MODE_ROW="").returncode != 0


def test_a_redis_that_answers_without_a_password_fails(tmp_path):
    result = run(tmp_path, FAKE_REDIS="PONG")
    assert result.returncode != 0
    assert "NOAUTH" in result.stdout


def test_a_token_in_a_log_is_counted_and_never_printed(tmp_path):
    result = run(tmp_path, FAKE_LOG_LINE=f"Authorization: Bearer {TOKEN}")
    assert result.returncode != 0
    assert "1 token-shaped" in result.stdout
    assert TOKEN not in result.stdout + result.stderr
    assert "eyJ" not in result.stdout + result.stderr


def test_no_secret_value_is_printed(tmp_path):
    result = run(tmp_path, FAKE_PLATFORM_MODE="recrod")
    assert "not-printed" not in result.stdout + result.stderr


def test_the_stack_check_runs_it():
    assert "verify-switches.sh" in (ROOT / "scripts/verify.sh").read_text()
