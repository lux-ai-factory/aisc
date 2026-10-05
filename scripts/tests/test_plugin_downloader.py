"""The plugin downloader's own script, run in alpine as compose would run it, with git and apk
replaced by stubs: which repos it clones, what it does without a GitHub token, and that the token
never reaches git's arguments or the log."""

import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT
from test_compose import FILES, PLUGIN_REPOS

PRIVATE = {f"aisc-plugin-{n}" for n in ("agentseal", "counterfactual", "evasion", "example", "luxeval",
                                         "uncertainty")}
TOKEN = "ghp_not-a-real-token-1f2c9e"

# Records its arguments, makes the clone's folder, and fails for the repo named in FAIL_REPO.
STUB_GIT = r"""#!/bin/sh
echo "$*" >> /downloads/.git-argv
while [ "$1" = "-c" ]; do echo "$2" >> /downloads/.git-config; shift 2; done
if [ "$1" = "ls-remote" ]; then
  repo=$(basename "$4" .git)
  case " $UNIFIED " in *" $repo "*) echo "abc123	refs/heads/feat/unified-modules"; exit 0 ;; esac
  exit 2
fi
if [ "$1" = "clone" ]; then
  shift
  if [ "$1" = "--branch" ]; then shift 2; fi
  repo=$(basename "$1" .git)
  if [ -n "$FAIL_REPO" ] && [ "$repo" = "$FAIL_REPO" ]; then echo "fatal: stub failure" >&2; exit 128; fi
  mkdir -p "$repo/.git"
fi
exit 0
"""


def _service():
    with_downloader = FILES + ["docker-compose.plugin_downloader.yml"]
    args, required = [], set()
    for f in with_downloader:
        args += ["-f", str(ROOT / f)]
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
    env.update({k: "dummy" for k in required})
    j = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.plugin_downloader"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert j.returncode == 0, j.stderr[-2000:]
    return json.loads(j.stdout)["services"]["plugin-downloader"]


def _run(tmp_path, token="", fail_repo="", unified=""):
    service = _service()
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "git").write_text(STUB_GIT)
    (stubs / "apk").write_text("#!/bin/sh\nexit 0\n")
    for f in stubs.iterdir():
        f.chmod(0o755)
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    # `config` keeps compose's $$ escapes; compose itself turns them into $ when it runs the command
    env = dict(service.get("environment") or {})
    env["GITHUB_TOKEN"] = token
    env["FAIL_REPO"] = fail_repo
    env["UNIFIED"] = unified
    env_args = [a for k, v in env.items() for a in ("-e", f"{k}={v or ''}")]
    r = subprocess.run(["docker", "run", "--rm", "-u", f"{os.getuid()}:{os.getgid()}",
                        "-v", f"{stubs}:/stubs:ro", "-v", f"{downloads}:/downloads", *env_args,
                        "-e", "PATH=/stubs:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                        service["image"], *[c.replace("$$", "$") for c in service["command"]]], capture_output=True, text=True, timeout=120)
    cloned = {p.name for p in downloads.iterdir() if (p / ".git").is_dir()}
    argv = (downloads / ".git-argv").read_text() if (downloads / ".git-argv").exists() else ""
    return r, cloned, argv


@pytest.fixture(autouse=True)
def _docker():
    if not shutil.which("docker"):
        pytest.skip("needs docker")


def test_without_a_token_it_clones_the_public_plugins_and_names_the_private_ones_it_skips(tmp_path):
    r, cloned, _ = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert cloned == PLUGIN_REPOS - PRIVATE
    out = r.stdout + r.stderr
    for repo in PRIVATE:
        assert re.search(rf"skipped {repo}\b.*GITHUB_TOKEN", out), out


def test_with_a_token_it_clones_every_plugin_and_never_shows_the_token(tmp_path):
    r, cloned, argv = _run(tmp_path, token=TOKEN)
    assert r.returncode == 0, r.stdout + r.stderr
    assert cloned == PLUGIN_REPOS
    assert TOKEN not in argv, "the token is in git's arguments (visible in ps and in the URL)"
    assert TOKEN not in r.stdout + r.stderr


def test_one_repo_that_fails_to_clone_does_not_stop_the_others(tmp_path):
    r, cloned, _ = _run(tmp_path, fail_repo="aisc-plugin-fairness")
    assert r.returncode == 0, r.stdout + r.stderr
    assert cloned == PLUGIN_REPOS - PRIVATE - {"aisc-plugin-fairness"}
    assert re.search(r"could not (clone|update) aisc-plugin-fairness", r.stdout + r.stderr)


def test_every_clone_and_pull_asks_for_http_1_1(tmp_path):
    """git 2.49 and later, over HTTP/2, gets a 401 from GitHub on a public repo's upload-pack POST
    (after a 103 Early Hints), so every clone fails; over HTTP/1.1 they work (2026-10-04, alpine 3.22
    and latest; 3.21's git 2.47 works either way)."""
    r, cloned, argv = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = [line for line in argv.splitlines() if " clone " in f" {line} " or " pull " in f" {line} "]
    assert calls and all("http.version=HTTP/1.1" in line for line in calls), calls


def test_a_repo_with_feat_unified_modules_is_cloned_on_that_branch_the_others_on_their_default(tmp_path):
    """Every AISC change is made on feat/unified-modules, plugin repos included: the stack must build
    that branch where a repo has it, and the default branch where it doesn't (yet)."""
    r, cloned, argv = _run(tmp_path, unified="aisc-plugin-langbite aisc-plugin-fairness")
    assert r.returncode == 0, r.stdout + r.stderr
    clones = {line.split("lux-ai-factory/")[1].split(".git")[0]: line for line in argv.splitlines() if " clone " in f" {line} "}
    assert set(clones) == PLUGIN_REPOS - PRIVATE
    for repo, line in clones.items():
        on_branch = "--branch feat/unified-modules" in line
        assert on_branch == (repo in ("aisc-plugin-langbite", "aisc-plugin-fairness")), line
