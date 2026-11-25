"""The Superset upgrade check: scripts/check-superset-upgrade.sh.

Static checks always; the live run (it starts containers, about 3 minutes) only with AISC_SUPERSET_CHECK=1:
it passes on the stack's Superset and fails, naming the charts, when a column they read is removed."""
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts/check-superset-upgrade.sh"
CHECKER = ROOT / "scripts/superset_upgrade_check.py"
FIXTURES = ROOT / "scripts/fixtures/superset_upgrade"


def test_it_uses_throwaway_containers_only_and_removes_them():
    text = SCRIPT.read_text()
    assert os.access(SCRIPT, os.X_OK)
    names = re.findall(r'(NET|PG|REDIS|SUP)="(aisc-t-sup-[a-z-]*)\$TAG"', text)
    assert {n for n, _ in names} == {"NET", "PG", "REDIS", "SUP"}
    assert "trap cleanup EXIT" in text and "docker rm -f" in text and "docker network rm" in text
    published = re.findall(r"-p\s+(\S+)", text)                       # only Superset, on a free local port
    assert published == ['"127.0.0.1:$PORT:8088"'], published


STAGED = """# syntax=docker/dockerfile:1.19
FROM apache/superset:1.0.0@sha256:aaa AS shared
RUN true
FROM scratch AS gateway
FROM apache/superset:2.0.0@sha256:bbb
COPY --from=shared /identity /identity
"""


def _default_image(dockerfile: str, tmp_path) -> str:
    """What the script's default image is for a dashboard Dockerfile with this text."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "apps/results-dashboard").mkdir(parents=True)
    (tmp_path / "apps/results-dashboard/Dockerfile").write_text(dockerfile)
    script = tmp_path / "scripts/check-superset-upgrade.sh"
    line = re.search(r"^IMAGE=(.*)$", SCRIPT.read_text(), re.M).group(1).replace("$0", str(script))
    return subprocess.run(["bash", "-c", f"echo {line}"], capture_output=True, text=True).stdout.strip()


def test_it_runs_the_stacks_superset_by_default_and_the_real_extension():
    text = SCRIPT.read_text()
    # the default is the image the dashboard Dockerfile builds: its last FROM, so an upgrade there is the one place
    # to change; the stages before it are stand-ins for build contexts, not the Superset the stack runs
    froms = re.findall(r"^FROM (\S+)", (ROOT / "apps/results-dashboard/Dockerfile").read_text(), re.M)
    stock = froms[-1]
    default = subprocess.run(["bash", "-c", re.search(r'^IMAGE=(.*)$', text, re.M).group(1).replace('$0', str(SCRIPT))
                              .join(["echo ", ""])], capture_output=True, text=True).stdout.strip()
    assert default == stock
    assert "superset_config.py:/app/pythonpath/superset_config.py:ro" in text
    assert "aisc_ext:/app/pythonpath/aisc_ext:ro" in text


def test_the_default_image_is_the_last_stages_not_a_named_stage_before_it(tmp_path):
    assert _default_image(STAGED, tmp_path) == "apache/superset:2.0.0@sha256:bbb"


def test_a_given_image_replaces_only_the_last_stages_from_line(tmp_path):
    text = SCRIPT.read_text()
    program = re.search(r"awk -v image=\"\$IMAGE\" '([^']*)'", text).group(1)
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(STAGED)
    out = subprocess.run(["awk", "-v", "image=apache/superset:9.9.9", program, str(dockerfile)],
                         capture_output=True, text=True).stdout
    assert out == STAGED.replace("FROM apache/superset:2.0.0@sha256:bbb", "FROM apache/superset:9.9.9")


def test_the_image_is_built_with_the_dashboard_folder_as_its_context(tmp_path):
    """The Dockerfile copies the configuration, extension and branding from the dashboard folder, so a build in
    any other folder fails. A stand-in docker records the build's arguments and fails it, which stops the script."""
    log = tmp_path / "docker.log"
    stub = tmp_path / "bin/docker"
    stub.parent.mkdir()
    stub.write_text(f'#!/bin/sh\n[ "$1" = build ] && {{ printf "%s\\n" "$@" > {log}; exit 1; }}\nexit 0\n')
    stub.chmod(0o755)
    subprocess.run([str(SCRIPT)], capture_output=True, text=True, timeout=60,
                   env={**os.environ, "PATH": f"{stub.parent}:{os.environ['PATH']}"})
    args = log.read_text().splitlines()
    assert args[-1] == str(ROOT / "apps/results-dashboard"), args
    dockerfile = args[args.index("-f") + 1]
    assert dockerfile.endswith("/Dockerfile") and not dockerfile.startswith(args[-1]), args


def test_the_fixture_holds_the_plugins_real_default_charts():
    fixture = json.loads((FIXTURES / "visualizations.json").read_text())
    labels = [p["label"] for p in fixture["plugins"]]
    assert labels == ["Data Drift", "LangBiTe"]
    assert all(p["visualizations"] for p in fixture["plugins"])
    sql = (FIXTURES / "project.sql").read_text()
    assert "data-monitor::DataDriftPlugin (v0.4.1)" in sql and "LangBiteEvaluationPlugin (v0.2.6)" in sql


def test_verify_offers_it_as_an_opt_in():
    assert "--superset-upgrade" in (ROOT / "scripts/verify.sh").read_text()


@pytest.mark.skipif(os.environ.get("AISC_SUPERSET_CHECK") != "1" or not shutil.which("docker"),
                    reason="the live check starts containers: AISC_SUPERSET_CHECK=1")
def test_it_passes_and_fails_when_it_should():
    ok = subprocess.run([str(SCRIPT)], capture_output=True, text=True, timeout=1200)
    assert ok.returncode == 0, ok.stdout[-2000:]
    assert "all checks held" in ok.stdout
    broken = subprocess.run([str(SCRIPT), "--break"], capture_output=True, text=True, timeout=1200)
    assert broken.returncode != 0
    assert "FAIL Data Drift: chart 'Default · PSI per feature'" in broken.stdout


def test_supersets_own_data_is_in_postgres_as_on_the_stack():
    """The project lock is a Postgres advisory lock: on SQLite the syncs-at-once check would prove nothing."""
    text = SCRIPT.read_text()
    assert 'CREATE DATABASE superset' in text
    assert 'SUPERSET_DB_URI="postgresql+psycopg2://aisc-postgres-user:$PG_PW@$PG:5432/superset"' in text
    assert "sqlite:" not in text


def test_the_check_reads_langbites_failed_answers_on_its_tile():
    """LangBiTe 0.2.6: the tile lists every failed answer as the target gave it (fixture project.sql)."""
    sql = (FIXTURES / "project.sql").read_text()
    text = (ROOT / "scripts/superset_upgrade_check.py").read_text()
    for answer in ("Yes, on average women are less suited to engineering.", "No, gender does not decide that."):
        assert answer in sql and answer in text
    fixture = json.loads((FIXTURES / "visualizations.json").read_text())
    langbite = next(p for p in fixture["plugins"] if p["label"] == "LangBiTe")
    assert [v["title"] for v in langbite["visualizations"]] == ["Pass rate per concern", "Failed cases"]


@pytest.mark.parametrize("given, passed", [((), ""), (("apache/superset:9.9.9",), "apache/superset:9.9.9")])
def test_verify_passes_on_the_image_it_was_given_and_no_other(tmp_path, given, passed):
    """With no image, verify.sh passed apache/superset:4.1.1, an older Superset than the
    stack's (the check's own default is the Dockerfile's FROM line); now it passes none."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/verify.sh", tmp_path / "scripts/verify.sh")
    stub = tmp_path / "scripts/check-superset-upgrade.sh"
    stub.write_text('#!/bin/sh\necho "args=$#:$*"\n')
    stub.chmod(0o755)
    r = subprocess.run(["bash", str(tmp_path / "scripts/verify.sh"), "--superset-upgrade", *given],
                       capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == f"args={len(given)}:{passed}", r.stdout + r.stderr


def test_the_export_zip_is_written_in_a_folder_removed_afterwards():
    """The import check's chart export goes in a temporary folder that is removed with it, not a bare
    tempfile.mktemp name (racy, and left behind)."""
    text = CHECKER.read_text()
    assert "mktemp(" not in text
    assert "tempfile.TemporaryDirectory()" in text
