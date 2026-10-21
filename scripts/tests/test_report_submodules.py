"""The report renderer is built from two submodules of this repository: a recursive clone brings
everything its image needs, and it needs no report plugin of any evaluation tool."""
import configparser
import re
import tempfile
from pathlib import Path

import pytest

import compose_cfg
from conftest import ROOT, needs_submodule

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
    """The renderer's build, with the host's own REPORT_* left out so they cannot mask the files'."""
    with tempfile.TemporaryDirectory() as d:
        return compose_cfg.config(Path(d), drop=("REPORT_",))["services"]["report-renderer"]["build"]


def test_the_renderer_builds_from_the_report_generator_submodule():
    assert _renderer_build()["context"].rstrip("/") == str(ROOT / "apps/report-generator")


@needs_submodule("apps/report-generator")
def test_compose_gives_exactly_the_contexts_the_renderer_dockerfile_copies_from():
    dockerfile = (ROOT / "apps/report-generator/Dockerfile").read_text()
    # COPY --from=<name> where <name> is a build context, not an image (images carry / or :)
    wanted = {m for m in re.findall(r"COPY\s+--from=(\S+)", dockerfile) if "/" not in m and ":" not in m}
    given = _renderer_build().get("additional_contexts") or {}
    assert set(given) == wanted, (sorted(given), sorted(wanted))


def test_the_interface_context_is_the_interface_submodule():
    given = _renderer_build().get("additional_contexts") or {}
    assert given.get("interface", "").rstrip("/") == str(ROOT / "shared/report-plugin-interface"), given
