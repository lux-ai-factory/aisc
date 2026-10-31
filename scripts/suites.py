#!/usr/bin/env python3
"""How each module's tests are run: one row per suite, the only place that says so.

    python3 scripts/suites.py rows     # name|dir|marker|needs|command, one line per suite

scripts/verify.sh --modules runs every row. The root CI's python matrix (.github/workflows/ci.yml) holds the
rows marked ci, with the same names and commands; scripts/tests/test_suites.py fails when the two differ, so a
suite added to one is added to the other. Submodule workflows keep their own commands: each runs on its own
checkout, without this file.

A row's command runs from the repository root, in bash. Where a scripts/lib/<suite>-tests.sh wrapper exists
(a throwaway Postgres, the locked environment) the row calls it, so a workstation and CI run the same thing.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Suite:
    #: the name verify.sh prints and the CI job carries
    name: str
    #: the module's folder, from the repository root: no folder, no run (a submodule not checked out)
    dir: str
    #: a file or folder inside dir that exists once the module's dependencies are installed; empty for none
    marker: str
    #: the programs the command needs on PATH; a missing one makes verify.sh skip the row, not fail it
    needs: tuple[str, ...]
    #: whether the root CI's python matrix runs it
    ci: bool
    command: str


SUITES = (
    Suite("identity", "shared/identity", "", ("uv", "docker"), True, "scripts/lib/identity-tests.sh"),
    Suite("platform", "platform", "", ("uv", "docker"), True, "scripts/test-platform.sh -q -p no:warnings"),
    Suite("control-objectives", "apps/control-objectives", "", ("uv", "docker"), True,
          "scripts/lib/co-tests.sh -p no:warnings"),
    Suite("report-composer", "apps/report-composer", "", ("uv", "docker"), True,
          "cd apps/report-composer && uv run --extra dev pytest -q -p no:warnings"),
    # the engine without upstream's integration package (it needs a live stack), then its project database
    # tests on a throwaway Postgres in configurator mode
    Suite("engine", "apps/backend", "", ("uv",), True, "scripts/lib/engine-tests.sh"),
    Suite("engine on postgres", "apps/backend", "", ("uv", "docker"), True, "scripts/lib/engine-tests.sh --postgres"),
    # a few eval tests run only in one deployment mode: both modes
    Suite("eval", "apps/eval", "", ("uv",), True,
          "cd apps/eval && uv run --locked --no-dev --group test pytest -q -p no:cacheprovider"
          " && AISC_DEPLOYMENT=configurator uv run --locked --no-dev --group test pytest -q -p no:cacheprovider"),
    Suite("eval lint", "apps/eval", "", ("uv",), True,
          "cd apps/eval && uv run --locked --only-group dev ruff check . && uv run --locked --only-group dev ruff"
          " format --check ."),
    Suite("plugin-manager", "shared/plugin-manager", "", ("uv",), True,
          "cd shared/plugin-manager && uv run --locked --with pytest python -m pytest -q -p no:cacheprovider"),
    # onnx and onnxruntime, as the submodule's own CI runs it: its model-format tests import them
    Suite("plugin-interface", "shared/plugin-interface", "", ("uv",), True,
          "cd shared/plugin-interface && uv run --locked --with pytest --with pandas --with onnx --with onnxruntime"
          " python -m pytest -q -p no:cacheprovider"),
    # its db tests start throwaway Postgres containers; the caller's database addresses must not reach them
    Suite("report-generator", "apps/report-generator", "", ("uv", "docker"), True,
          "cd apps/report-generator && env -u DATABASE_URL -u PLATFORM_TEST_DATABASE_URL uv run --locked --extra dev"
          " pytest -q -p no:cacheprovider tests"),
    Suite("report-plugin-interface", "shared/report-plugin-interface", "", ("uv",), False,
          "cd shared/report-plugin-interface && uv run --with pytest python -m pytest -q -p no:cacheprovider"),
    Suite("catalogue frontend", "apps/catalogue/frontend", "node_modules", ("npx",), False,
          "cd apps/catalogue/frontend && npx vitest run"),
    Suite("qualification", "apps/qualification", "node_modules", ("npx",), False,
          "cd apps/qualification && npx vitest run"),
    Suite("qualification prefill", "apps/qualification", "node_modules", ("docker",), False,
          "cd apps/qualification && docker run --rm -v \"$PWD:/w\" -w /w/services/prefill python:3.12-slim sh -lc"
          " 'pip install -q -r requirements.txt -r requirements-dev.txt"
          " && PREFILL_FIELDS_PATH=/w/src/data/prefillFields.json python -m pytest -q'"),
    Suite("qualification ontology", "apps/qualification", "node_modules", ("docker",), False,
          "cd apps/qualification && docker run --rm -v \"$PWD:/w\" -w /w/services/ontology python:3.12-slim sh -lc"
          " 'pip install -q -r requirements.txt -r requirements-dev.txt && python -m pytest -q'"),
    Suite("qualification pdf", "apps/qualification", "node_modules", ("docker",), False,
          "cd apps/qualification && docker build -q -t aisc-t-qpdf services/system_card_renderer >/dev/null"
          " && docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v \"$PWD:/w:ro\" -w /w/services/system_card_renderer"
          " aisc-t-qpdf sh -lc 'pip install -q -r requirements-dev.txt && python -m pytest -q -p no:cacheprovider'"),
    Suite("qualification agents", "apps/qualification", "node_modules", ("docker",), False,
          "cd apps/qualification && docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v \"$PWD:/w:ro\" python:3.12-slim"
          " sh -lc 'mkdir -p /tmp/q && cp -r /w/services /w/src /tmp/q/ && cd /tmp/q/services/agents"
          " && pip install -q -r requirements.txt pytest && python -m pytest -q -p no:cacheprovider'"),
    Suite("controls pdf", "apps/controls/services/pdf_renderer", "", ("docker",), False,
          "cd apps/controls/services/pdf_renderer && docker build -q -t aisc-t-cpdf . >/dev/null"
          " && docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v \"$PWD:/w:ro\" -w /w aisc-t-cpdf"
          " sh -lc 'pip install -q pytest httpx && python -m pytest -q -p no:cacheprovider'"),
    Suite("controls", "apps/controls", "node_modules", ("npx",), False, "cd apps/controls && npx vitest run"),
    Suite("engine webapp", "apps/webapp", "node_modules", ("npx",), False, "cd apps/webapp && npx vitest run"),
    # the versions in the aisc-results-dashboard image (pip show pyjwt cryptography flask flask-login werkzeug):
    # PyJWT's behaviour differs between releases
    Suite("dashboard gateway", "dashboard-gateway", "", ("uv",), False,
          "cd dashboard-gateway && PYTHONDONTWRITEBYTECODE=1 uv run --no-project --quiet --with pyjwt==2.8.0"
          " --with cryptography==50.0.2 --with flask==2.3.3 --with flask-login==0.6.3 --with werkzeug==3.0.6"
          " python -m unittest -q test_gateway_identity test_superset_gateway_config"),
    Suite("results dashboard", "apps/results-dashboard", ".venv", (), False,
          "cd apps/results-dashboard && PYTHONPATH=. .venv/bin/python -m pytest -q --ignore=tests/test_sso_login.py"),
)


def rows() -> str:
    return "".join(f"{s.name}|{s.dir}|{s.marker}|{','.join(s.needs)}|{s.command}\n" for s in SUITES)


def main(argv: list[str]) -> int:
    if argv != ["rows"]:
        print("usage: scripts/suites.py rows", file=sys.stderr)
        return 2
    sys.stdout.write(rows())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
