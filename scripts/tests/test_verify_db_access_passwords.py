"""scripts/verify-db-access.sh logs in as each role with that role's generated password.

report_composer_rw and report_ro have generated passwords since the report stack (scripts/secrets.sh,
init/report-roles.sql), but the access check still logged in as them with their own names. On a stack
with generated passwords their "allow" checks then fail, and worse, their "deny" checks pass only
because the login is refused, so they prove nothing about the grants.

The script is run with a fake `docker` on PATH that records the user and password of every connection
string (to a file, never printed), with each role's password variable set to a value of its own."""
import os
import re
import subprocess

from conftest import ROOT

SCRIPT = ROOT / "scripts/verify-db-access.sh"

#: every role the script logs in as, and the variable scripts/secrets.sh writes its password to
PASSWORDS = {
    "platform_rw": "PLATFORM_RW_PASSWORD",
    "qualification_rw": "QUALIFICATION_RW_PASSWORD",
    "control_objectives_rw": "CONTROL_OBJECTIVES_RW_PASSWORD",
    "controls_rw": "CONTROLS_RW_PASSWORD",
    "engine_rw": "ENGINE_RW_PASSWORD",
    "dashboard_ro": "DASHBOARD_RO_PASSWORD",
    "report_composer_rw": "REPORT_COMPOSER_PASSWORD",
    "report_ro": "REPORT_RO_PASSWORD",
}

FAKE_DOCKER = """#!/usr/bin/env bash
for a in "$@"; do
  case "$a" in postgresql://*) u=${a#postgresql://}; printf '%s\\n' "${u%%@*}" >> "$LOGINS" ;; esac
done
exit 0
"""


def logins(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(0o755)
    log = tmp_path / "logins"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "LOGINS": str(log)}
    env.update({var: f"generated-{role}" for role, var in PASSWORDS.items()})
    subprocess.run(["bash", str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    return [line.split(":", 1) for line in log.read_text().splitlines()]


def test_every_role_logs_in_with_its_generated_password(tmp_path):
    seen = logins(tmp_path)
    users = {u for u, _ in seen}
    assert set(PASSWORDS) <= users, f"the script no longer logs in as {set(PASSWORDS) - users}"
    wrong = sorted({u for u, p in seen if u in PASSWORDS and p != f"generated-{u}"})
    assert not wrong, f"logs in with a password other than its generated one: {wrong}"


def test_the_script_reads_the_report_passwords_from_env_runtime():
    text = SCRIPT.read_text()
    for var in ("REPORT_COMPOSER_PASSWORD", "REPORT_RO_PASSWORD"):
        assert re.search(rf"^{var}=\${{{var}:-\$\(awk 'index\(\$0, \"{var}=\"\) == 1", text, re.M), var
