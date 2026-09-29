"""The report renderer is built from two submodules of this repository (2026-09-29): a recursive
clone brings everything its image needs, and it needs no report plugin of any evaluation tool."""
import configparser
import json
import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

FILES = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]
SUBMODULES = {
    "apps/report-generator": "https://github.com/lux-ai-factory/aisc-report-generator.git",
    "shared/report-plugin-interface": "https://github.com/lux-ai-factory/aisc-report-plugin-interface.git",
}


def gitmodules():
    cp = configparser.ConfigParser()
    cp.read(ROOT / ".gitmodules")
    return {cp[s]["path"]: cp[s] for s in cp.sections()}


@pytest.mark.parametrize("path", sorted(SUBMODULES))
def test_the_report_repos_are_submodules_on_the_unified_branch(path):
    mods = gitmodules()
    assert path in mods, sorted(mods)
    assert mods[path]["url"] == SUBMODULES[path]
    assert mods[path].get("branch") == "feat/unified-modules"


def _renderer_build():
    args, required = [], set()
    for f in FILES:
        required |= set(re.findall(r"\$\{([A-Z0-9_]+):\?", (ROOT / f).read_text()))
        args += ["-f", str(ROOT / f)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("REPORT_")}
    env.update({k: "dummy" for k in required})
    r = subprocess.run(["docker", "compose", "-p", "aisc-t-config", "--project-directory", str(ROOT),
                        "--env-file", str(ROOT / "env.development"), *args, "config", "--format", "json"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-1000:]
    return json.loads(r.stdout)["services"]["report-renderer"]["build"]


def test_the_renderer_builds_from_the_report_generator_submodule():
    assert _renderer_build()["context"].rstrip("/") == str(ROOT / "apps/report-generator")


def test_compose_gives_exactly_the_contexts_the_renderer_dockerfile_copies_from():
    dockerfile = (ROOT / "apps/report-generator/Dockerfile").read_text()
    # COPY --from=<name> where <name> is a build context, not an image (images carry / or :)
    wanted = {m for m in re.findall(r"COPY\s+--from=(\S+)", dockerfile) if "/" not in m and ":" not in m}
    given = _renderer_build().get("additional_contexts") or {}
    assert set(given) == wanted, (sorted(given), sorted(wanted))


def test_the_interface_context_is_the_interface_submodule():
    given = _renderer_build().get("additional_contexts") or {}
    assert given.get("interface", "").rstrip("/") == str(ROOT / "shared/report-plugin-interface"), given


def test_no_tool_report_plugin_is_part_of_the_build():
    given = _renderer_build().get("additional_contexts") or {}
    assert not ({"mlareject", "langbite", "strongreject", "promptfoo"} & set(given)), sorted(given)


def test_the_readme_no_longer_asks_for_sibling_report_folders():
    text = (ROOT / "README.md").read_text()
    assert "../aisc-report-" not in text
