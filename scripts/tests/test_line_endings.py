"""A clone on Windows keeps Linux line endings: Git there may turn LF into CRLF (core.autocrlf), and a shell
script, an SQL file or the Caddyfile with CRLF breaks in the Linux containers that read them
($'\\r': command not found). .gitattributes fixes it for every clone, whatever its Git settings."""
import subprocess

import pytest

from conftest import ROOT, submodule_missing

FILES = ["scripts/start.sh", "scripts/secrets.sh", "scripts/lib/dev-accounts.sh", "Caddyfile",
         "init/platform-db.sql", "platform/migrations/0001_project_membership.sql", "keycloak/aisc-realm.json",
         "env.plugin_downloader", "docker-compose.development.yml"]


@pytest.mark.parametrize("path", FILES)
def test_the_file_is_checked_out_with_lf_on_every_system(path):
    out = subprocess.run(["git", "-C", str(ROOT), "check-attr", "eol", "--", path],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip().endswith("eol: lf"), out


# The submodules whose scripts and Dockerfiles end up in Linux containers. The three in shared/ have none.
# The webapp is held to its upstream: the README's clone command (git -c core.autocrlf=false) covers it.
SUBMODULES = ["apps/backend", "apps/catalogue", "apps/control-objectives",
              "apps/controls", "apps/eval", "apps/qualification", "apps/report-generator", "apps/results-dashboard"]


def container_files(repo):
    out = subprocess.run(["git", "-C", str(ROOT / repo), "ls-files"], capture_output=True, text=True,
                         check=True).stdout.splitlines()
    return [p for p in out if p.endswith(".sh") or p.split("/")[-1].startswith("Dockerfile") or "entrypoint" in p]


@pytest.mark.parametrize("repo", SUBMODULES)
def test_a_submodules_container_scripts_are_checked_out_with_lf(repo):
    if submodule_missing(repo):
        pytest.skip(f"{repo} is not checked out here")
    files = container_files(repo)
    assert files, f"{repo} has no scripts or Dockerfiles any more: take it off the list"
    out = subprocess.run(["git", "-C", str(ROOT / repo), "check-attr", "eol", "--", *files],
                         capture_output=True, text=True, check=True).stdout
    assert [l for l in out.splitlines() if not l.endswith("eol: lf")] == []
