"""The eval worker's image carries a pinned Node and a pinned promptfoo CLI for plugins to run: a stage from the
official Node image of a full version, and promptfoo installed globally at a full version in the runtime stage,
with npm's cache cleaned in the same layer. Nothing is fetched at `latest`.

The static checks read apps/eval/Dockerfile. The image check builds the image and asks it for both versions as
the plugin user; it runs only with AISC_CHECK_EVAL_IMAGE=1 (it needs Docker and builds an image), after `df -h /`:

    AISC_CHECK_EVAL_IMAGE=1 uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_eval_image_promptfoo.py

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_eval_image_promptfoo.py
"""

import os
import re
import shutil
import subprocess

import pytest

from conftest import ROOT

DOCKERFILE = ROOT / "apps/eval/Dockerfile"
NODE_STAGE = re.compile(r"^FROM node:(\d+)\.(\d+)\.(\d+)-bookworm-slim AS node$", re.M)
IMAGE = "aisc-must-fixes-eval:check"


def _text() -> str:
    return DOCKERFILE.read_text()


def _runtime_part() -> str:
    text = _text()
    marker = "FROM base AS runtime"
    assert marker in text, "apps/eval/Dockerfile has no runtime stage"
    return text[text.index(marker):]


def _run_instructions(text: str) -> list[str]:
    """Each RUN instruction with its continuation lines joined."""
    joined = re.sub(r"\\\n", " ", text)
    return [line for line in joined.splitlines() if line.lstrip().startswith("RUN ")]


def test_one_node_stage_of_a_full_22_version():
    stages = NODE_STAGE.findall(_text())
    assert len(stages) == 1, f"node stages: {stages}"
    assert stages[0][0] == "22"


def test_promptfoo_is_installed_at_a_pinned_version_in_the_runtime_stage():
    runtime = _runtime_part()
    assert re.search(r"^ARG PROMPTFOO_VERSION=\d+\.\d+\.\d+$", runtime, re.M), \
        "the runtime stage has no ARG PROMPTFOO_VERSION=<x.y.z>"
    installs = [r for r in _run_instructions(runtime)
                if "npm install --global" in r and '"promptfoo@${PROMPTFOO_VERSION}"' in r]
    assert installs, 'no npm install --global of "promptfoo@${PROMPTFOO_VERSION}" in the runtime stage'


def test_nothing_is_fetched_at_latest():
    text = _text()
    assert "promptfoo@latest" not in text
    assert "npx -y promptfoo" not in text
    assert "@latest" not in text


def test_the_npm_cache_is_cleaned_in_the_install_layer():
    [install] = [r for r in _run_instructions(_runtime_part()) if '"promptfoo@${PROMPTFOO_VERSION}"' in r]
    assert install.index("npm cache clean --force") > install.index("npm install --global")


def _versions_from_dockerfile() -> tuple[str, str]:
    node = ".".join(NODE_STAGE.findall(_text())[0])
    promptfoo = re.search(r"^ARG PROMPTFOO_VERSION=(\S+)$", _text(), re.M).group(1)
    return node, promptfoo


@pytest.mark.skipif(os.environ.get("AISC_CHECK_EVAL_IMAGE") != "1",
                    reason="builds the eval image: set AISC_CHECK_EVAL_IMAGE=1 to run it")
def test_the_built_image_runs_the_pinned_node_and_promptfoo_as_the_plugin_user():
    assert shutil.which("docker"), "docker is not on PATH"
    print(subprocess.run(["df", "-h", "/"], capture_output=True, text=True).stdout)
    node, promptfoo = _versions_from_dockerfile()
    try:
        subprocess.run(["docker", "build", "-t", IMAGE, "."], cwd=ROOT / "apps/eval", check=True)

        def version(entrypoint):
            return subprocess.run(["docker", "run", "--rm", "--user", "aisc-plugin", "--entrypoint", entrypoint,
                                   IMAGE, "--version"], capture_output=True, text=True, check=True).stdout.strip()

        assert version("promptfoo") == promptfoo
        assert version("node") == f"v{node}"
    finally:
        subprocess.run(["docker", "image", "rm", IMAGE], capture_output=True)
