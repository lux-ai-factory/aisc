"""The backup and the stack's verify run on a schedule: two crontab lines tagged with this install, written
only when asked (--install), removed with --remove, other people's lines left alone. Each scheduled run
writes a dated log.

No real crontab is read or written: a fake `crontab` on PATH keeps its table in a scratch file, and the
verify the schedule runs is a fake too.
"""
from __future__ import annotations

import os
import subprocess
from datetime import date

from conftest import ROOT

SCHEDULE = ROOT / "scripts/schedule.sh"
SCHEDULED = ROOT / "scripts/scheduled.sh"


def _fake_crontab(tmp_path, lines=()):
    table = tmp_path / "crontab.txt"
    table.write_text("".join(line + "\n" for line in lines))
    shims = tmp_path / "shims"
    shims.mkdir()
    (shims / "crontab").write_text(
        "#!/bin/sh\n"
        f'T="{table}"\n'
        'if [ "$1" = "-l" ]; then cat "$T"; exit 0; fi\n'
        'if [ "$1" = "-" ]; then cat > "$T"; exit 0; fi\n'
        'cp "$1" "$T"\n')
    (shims / "crontab").chmod(0o755)
    env = {**os.environ, "PATH": f"{shims}:{os.environ['PATH']}"}
    return table, env


def run(args, env=None):
    return subprocess.run(["bash", *map(str, args)], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)


def test_the_schedule_names_both_jobs_and_this_install():
    r = run([SCHEDULE, "--print"])
    assert r.returncode == 0, (r.stdout + r.stderr)[-1000:]
    out = [line for line in r.stdout.splitlines() if line.strip()]
    assert any(line.startswith("30 2 * * * ") and "scheduled.sh backup" in line for line in out), out
    assert any(line.startswith("30 3 * * * ") and "scheduled.sh verify" in line for line in out), out
    assert out and all("# aisc-" in line for line in out), out


def test_install_then_remove_leaves_other_lines(tmp_path):
    table, env = _fake_crontab(tmp_path, ["0 1 * * * someone-else"])
    r = run([SCHEDULE, "--install"], env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1000:]
    assert len([line for line in table.read_text().splitlines() if "# aisc-" in line]) == 2
    r = run([SCHEDULE, "--remove"], env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1000:]
    assert table.read_text().splitlines() == ["0 1 * * * someone-else"]


def test_the_verify_log_is_dated(tmp_path):
    shims = tmp_path / "fake"
    shims.mkdir()
    fake_verify = shims / "verify.sh"
    fake_verify.write_text("#!/bin/sh\necho verify ran\n")
    fake_verify.chmod(0o755)
    logs = tmp_path / "logs"
    env = {**os.environ, "AISC_VERIFY_SCRIPT": str(fake_verify)}
    r = run([SCHEDULED, "verify", "--log-dir", logs], env=env)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1000:]
    assert sorted(p.name for p in logs.iterdir()) == [f"verify-{date.today().isoformat()}.log"]
