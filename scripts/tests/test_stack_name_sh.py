"""scripts/lib/stack-name.sh gives the names scripts/aisc.py gives, and no script addresses a stack container
by its bare name."""
import os
import re
import shutil
import subprocess

from conftest import ROOT


def sh(folder, code, **env):
    (folder / "scripts/lib").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "scripts/lib/stack-name.sh", folder / "scripts/lib/stack-name.sh")
    base = {k: v for k, v in os.environ.items() if k != "AISC_PROJECT"}
    r = subprocess.run(["bash", "-c", code], cwd=folder, env={**base, **env}, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


NAMES = ". scripts/lib/stack-name.sh; aisc_stack; aisc_container postgres"


def test_the_shell_helper_agrees_with_aisc_py(tmp_path):
    (tmp_path / "env.secrets").write_text("AISC_INSTALL=a1b2c3\n")
    assert sh(tmp_path, NAMES).split() == ["aisc-a1b2c3", "aisc-a1b2c3-postgres"]
    (tmp_path / "env.secrets").write_text("X=1\n")
    assert sh(tmp_path, NAMES).split() == ["aisc", "postgres"]


def test_an_empty_id_or_no_file_keeps_the_shared_names(tmp_path):
    (tmp_path / "env.secrets").write_text("AISC_INSTALL=\n")
    assert sh(tmp_path, NAMES).split() == ["aisc", "postgres"]
    (tmp_path / "env.secrets").unlink()
    assert sh(tmp_path, NAMES).split() == ["aisc", "postgres"]


def test_aisc_project_renames_the_stack_but_not_the_prefix(tmp_path):
    (tmp_path / "env.secrets").write_text("AISC_INSTALL=a1b2c3\n")
    assert sh(tmp_path, NAMES, AISC_PROJECT="aisc-ports").split() == ["aisc-ports", "aisc-a1b2c3-postgres"]


def test_only_the_checkouts_own_secrets_are_read(tmp_path):
    (tmp_path / "env.secrets").write_text("AISC_INSTALL=a1b2c3\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "env.secrets").write_text("AISC_INSTALL=ffffff\n")
    out = sh(tmp_path, f"cd {elsewhere}; . {tmp_path}/scripts/lib/stack-name.sh; aisc_stack; aisc_container postgres")
    assert out.split() == ["aisc-a1b2c3", "aisc-a1b2c3-postgres"]


def test_a_windows_line_ending_is_not_part_of_the_id(tmp_path):
    (tmp_path / "env.secrets").write_bytes(b"AISC_INSTALL=a1b2c3\r\n")
    assert sh(tmp_path, NAMES).split() == ["aisc-a1b2c3", "aisc-a1b2c3-postgres"]


def test_no_script_names_a_container_without_the_prefix():
    fixed = (r"docker (exec|inspect|logs|cp|restart|port|stop|start|kill|top|wait)( -[-\w=\"$]+)* \"?"
             r"(postgres|platform|keycloak|minio|caddy|dashboard|aisc-backend|aisc-webapp|oauth2-proxy|immudb)\b")
    for f in [*ROOT.glob("scripts/*.sh"), *ROOT.glob("scripts/lib/*.sh")]:
        assert not re.search(fixed, f.read_text()), f.name
