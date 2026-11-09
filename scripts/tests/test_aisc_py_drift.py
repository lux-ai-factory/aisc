"""`aisc.py drift`: which running containers of a stack no longer run what their image holds. Read-only: it only
lists, inspects and diffs. The docker on PATH is fixtures/fake_docker_stack.py, which serves a stack from a file.

    uv run --no-project --with pytest python -m pytest -q scripts/tests/test_aisc_py_drift.py
"""
import json
import shutil
import sys

from conftest import ROOT, aisc_py, copy_install_scripts
from test_aisc_py import fake_path, run

BACKEND = "aaaaaaaaaaaa" + "0" * 52
OLDER_BACKEND = "bbbbbbbbbbbb" + "0" * 52


def stack_docker(tmp_path, containers):
    """A docker on PATH serving `containers` (see fixtures/fake_docker_stack.py); returns the log of its calls."""
    tools = tmp_path / "fake-tools"
    tools.mkdir(exist_ok=True)
    logic = tools / "fake_docker_stack.py"
    shutil.copy(ROOT / "scripts/tests/fixtures/fake_docker_stack.py", logic)
    log = tmp_path / "docker.log"
    docker = tools / "docker"
    docker.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{logic}" "{log}" "{tmp_path}" "$@"\n')
    docker.chmod(0o755)
    (tools / "docker.cmd").write_text(f'@"{sys.executable}" "{logic}" "{log}" "{tmp_path}" %*\r\n')
    (tmp_path / "stack.json").write_text(json.dumps(containers))
    return log


def checkout(tmp_path):
    d = tmp_path / "checkout"
    d.mkdir()
    copy_install_scripts(d)
    return d


def drift(tmp_path, containers, *args):
    d = checkout(tmp_path)
    log = stack_docker(tmp_path, containers)
    return run(d, "drift", "--prefix", "aisc-test", *args, path=fake_path(tmp_path)), log


def clean(**over):
    return {"image": "aisc-backend:latest", "id": BACKEND, "workdir": "/app",
            "diff": ["C /app", "C /app/.venv", "A /app/shared", "C /usr/local",
                     "A /app/aisc_backend/routers/__pycache__/internal.cpython-312.pyc", "A /root/.cache/uv/x.py",
                     "A /app/application.log", "A /tmp/tmp.GGBoAL/x.py"],
            "mounts": ["/app/shared"], **over}


def test_a_stack_running_what_its_images_hold_has_not_drifted(tmp_path):
    r, _ = drift(tmp_path, {"aisc-test-aisc-backend": clean(), "aisc-test-platform": clean(image="aisc-platform:latest",
                                                                                            id="c" * 64)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "aisc-test-aisc-backend" in r.stdout and "aisc-test-platform" in r.stdout
    assert "no container drifted" in r.stdout.lower()


def test_code_changed_in_a_container_is_named_with_its_paths(tmp_path):
    copied = clean(diff=[*clean()["diff"], "C /app/aisc_backend/routers", "C /app/aisc_backend/routers/internal.py",
                         "A /app/aisc_backend/new_module.py"])
    r, _ = drift(tmp_path, {"aisc-test-aisc-backend": copied})
    assert r.returncode == 1, r.stdout + r.stderr
    assert "C /app/aisc_backend/routers/internal.py" in r.stdout
    assert "A /app/aisc_backend/new_module.py" in r.stdout
    # folders, caches, logs, the venv and what is outside the app folders are not code
    for noise in ("C /app/aisc_backend/routers\n", "__pycache__", ".venv", "application.log", "/root/.cache",
                  "/tmp/tmp.GGBoAL", "/usr/local"):
        assert noise not in r.stdout, noise


def test_files_served_from_the_web_folders_count_as_code(tmp_path):
    webapp = {"image": "aisc-webapp:latest", "id": "d" * 64, "workdir": "/",
              "diff": ["C /etc/nginx", "C /etc/nginx/conf.d", "A /usr/share/nginx/html/assets/extra-1a2b.js",
                       "A /var/cache/nginx/x.js"]}
    r, _ = drift(tmp_path, {"aisc-test-aisc-webapp": webapp})
    assert r.returncode == 1
    assert "A /usr/share/nginx/html/assets/extra-1a2b.js" in r.stdout
    assert "C /etc/nginx/conf.d\n" not in r.stdout and "/var/cache" not in r.stdout


def test_what_the_webapps_own_start_script_writes_is_not_drift(tmp_path):
    # env.sh (in /docker-entrypoint.d) writes the deployment mode into the bundle and the config at every start
    webapp = {"image": "aisc-webapp:latest", "id": "d" * 64, "workdir": "/",
              "diff": ["C /etc/nginx/conf.d/default.conf", "C /usr/share/nginx/html/assets/index-BIVOPe-Z.js"]}
    r, _ = drift(tmp_path, {"aisc-test-aisc-webapp": webapp})
    assert r.returncode == 0, r.stdout
    # the same paths in another image are still drift
    other = {**webapp, "image": "aisc-catalogue-private:latest"}
    r, _ = drift(tmp_path / "other" if (tmp_path / "other").mkdir() is None else tmp_path, {"aisc-test-catalogue": other})
    assert r.returncode == 1, r.stdout


def test_code_bind_mounted_from_the_tree_is_not_drift(tmp_path):
    dashboard = {"image": "aisc-results-dashboard:latest", "id": "e" * 64, "workdir": "/app",
                 "mounts": ["/app/pythonpath/aisc_ext", "/app/pythonpath/superset_config.py"],
                 "diff": ["A /app/pythonpath/aisc_ext", "A /app/pythonpath/superset_config.py",
                          "A /app/pythonpath/aisc_ext/branding.py"]}
    r, _ = drift(tmp_path, {"aisc-test-dashboard": dashboard})
    assert r.returncode == 0, r.stdout


def test_services_built_from_one_image_running_different_ones_are_named(tmp_path):
    r, _ = drift(tmp_path, {"aisc-test-aisc-backend": clean(),
                            "aisc-test-aisc-backend-ledger": clean(id=OLDER_BACKEND)})
    assert r.returncode == 1, r.stdout
    assert "aisc-backend:latest" in r.stdout
    assert "aaaaaaaaaaaa" in r.stdout and "bbbbbbbbbbbb" in r.stdout
    assert "aisc-test-aisc-backend-ledger" in r.stdout


def test_an_upstream_image_is_listed_but_not_checked(tmp_path):
    pgadmin = {"image": "dpage/pgadmin4:9.18", "id": "f" * 64, "workdir": "/pgadmin4",
               "diff": ["C /pgadmin4/config_distro.py"]}
    r, _ = drift(tmp_path, {"aisc-test-pgadmin": pgadmin})
    assert r.returncode == 0, r.stdout
    assert "aisc-test-pgadmin" in r.stdout and "upstream" in r.stdout


def test_drift_only_reads(tmp_path):
    r, log = drift(tmp_path, {"aisc-test-aisc-backend": clean(), "aisc-test-aisc-backend-ledger": clean()})
    assert r.returncode == 0, r.stdout + r.stderr
    verbs = {line.split()[0] for line in log.read_text().splitlines()}
    assert verbs <= {"ps", "inspect", "diff"}, verbs
    ps = [line for line in log.read_text().splitlines() if line.startswith("ps ")]
    assert ps and "label=com.docker.compose.project=aisc-test" in ps[0]


def test_an_unknown_drift_option_is_refused(tmp_path):
    d = checkout(tmp_path)
    log = stack_docker(tmp_path, {})
    r = run(d, "drift", "--prefx", "x", path=fake_path(tmp_path))
    assert r.returncode == 2 and "--prefix" in r.stderr
    assert not log.exists()


def test_a_stack_with_no_running_container_is_said_to_be_so(tmp_path):
    r, _ = drift(tmp_path, {})
    assert r.returncode == 1 and "no running container" in (r.stdout + r.stderr)


def test_the_code_rule_in_process():
    m = aisc_py()
    assert m.code_path("/app/x/y.py", "/app", []) and m.code_path("/aisc/apps/r/t.html.j2", "/aisc/apps/r", [])
    assert not m.code_path("/app/x", "/app", [])                                   # a folder
    assert not m.code_path("/app/x/__pycache__/y.cpython-312.pyc", "/app", [])
    assert not m.code_path("/app/node_modules/a/index.js", "/app", [])
    assert not m.code_path("/app/x.py", "/app", ["/app"])                          # bind-mounted
    assert not m.code_path("/opt/thing/x.py", "/", [])                             # outside the app folders
    assert m.code_path("/opt/thing/x.py", "/opt/thing", [])                        # the image's working folder
