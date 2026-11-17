"""Small architectural regression checks for ../../ARCHITECTURE.md.

Standard library only (AST + file checks), so these run with no module venv:

    uv run --no-project --with pytest python -m pytest tests/architecture -q

Named baseline violations are expected failures, but any new detected violation fails normally.
As each baseline clears, its test passes. ADR 0001 governs consolidation baselines; ADR 0003 defers
the execution baseline until the post-port milestone. These checks supplement instructions/review.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SKIP = {"node_modules", ".venv", "__pycache__", ".git"}


def _files(pattern: str):
    for path in ROOT.glob(pattern):
        if _SKIP.isdisjoint(path.parts):
            yield path


def _baseline(actual, known, *, decision="ADR 0001: remaining consolidation baseline"):
    """Fail new findings before marking named debt under its scoped decision."""
    actual, known = set(actual), set(known)
    assert not actual - known, f"new architectural violations: {sorted(actual - known)}"
    if actual:
        pytest.xfail(f"{decision}: {sorted(actual)}")


def test_required_source_trees_exist():
    """An empty/uninitialised submodule checkout must not look compliant."""
    for relative in ("apps/backend/aisc_backend", "apps/eval/aisc_eval",
                     "shared/plugin-interface/src/aisc_plugin_interface"):
        assert list((ROOT / relative).glob("**/*.py")), f"missing Python source: {relative}"


def _import_roots(path: Path) -> set[str]:
    """The top-level names a module imports (absolute imports only)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _importers(pattern: str, forbidden: set[str]) -> list[str]:
    out = []
    for path in _files(pattern):
        hit = _import_roots(path) & forbidden
        if hit:
            out.append(f"{path.relative_to(ROOT)} imports {sorted(hit)}")
    return sorted(out)


def test_i3_plugin_interface_is_independent():
    """The plugin interface is shipped to plugin authors; it must not depend on the engine."""
    bad = _importers("shared/plugin-interface/src/**/*.py",
                     {"aisc_eval", "aisc_backend", "platform_service"})
    assert not bad, "the plugin interface must not depend on the engine:\n" + "\n".join(bad)


def test_i3_eval_worker_has_no_backend_import():
    """The worker reaches the engine over its API; it must not import the engine's code."""
    bad = _importers("apps/eval/aisc_eval/**/*.py", {"aisc_backend", "platform_service"})
    assert not bad, "the eval worker must reach the engine over its API, not by import:\n" + "\n".join(bad)


def test_i1_worker_does_not_fetch_from_backend_midrun():
    """Post-port target (ADR 0003): dispatch contains inputs; only results post back."""
    fetches = {
        "get_evaluation_request", "get_evaluation_inputs", "get_dataset_file_content",
        "get_model_file_content", "get_project_settings_by_pid", "get_evaluation_plugins_status",
    }
    # Scan task code structurally, including attribute calls; networking under new names still
    # requires review and the backend-down acceptance test.
    src = (ROOT / "apps/eval/aisc_eval/celery_tasks.py").read_text(encoding="utf-8")
    used = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                name = getattr(call.func, "id", getattr(call.func, "attr", None))
                if name in fetches:
                    used.append(f"{node.name}:{name}")
    _baseline(used, {
        # Re-recorded for the main + frozen-unified-app merged tree (DOC-01 #121).
        # `run_evaluation` is the dispatcher: it attaches inputs (via `_embed_input_files`) and
        # project settings to the `run_plugin` signature before dispatch, so `run_plugin` itself
        # is self-contained and I1 holds. The AST heuristic cannot distinguish the dispatcher
        # from the runner, so these dispatch-time fetches are recorded as known findings (a
        # heuristic limitation, not debt). Evidence: the eval conformance fold on this branch
        # (`aisc_eval/utils/scrub.py`, `plugin_child_env`, `_embed_input_files`/`_decode_input_file`).
        # ADR 0003 / EXEC-01 #120 own the remaining post-port execution work.
        "run_evaluation:get_evaluation_inputs",
        "run_evaluation:get_project_settings_by_pid",
        "_embed_input_files:get_dataset_file_content",
        "_embed_input_files:get_model_file_content",
        # Status reconciliation during finalisation (results path), not a mid-run input fetch.
        "finalize_evaluation:get_evaluation_plugins_status",
    }, decision="ADR 0003: execution baseline until post-port execution milestone")


def test_i4_one_deployment_contract():
    """The deployment-mode contract lives in exactly one module, or is replaced by feature flags."""
    found = sorted(str(p.relative_to(ROOT)) for p in _files("apps/**/deployment.py"))
    _baseline(found, {"apps/backend/aisc_backend/deployment.py", "apps/eval/aisc_eval/deployment.py"})


def test_i3_one_project_database_module():
    """One project-database path, not two."""
    found = sorted(str(p.relative_to(ROOT)) for p in _files("**/projectdb.py"))
    if len(found) <= 1:
        return
    _baseline(found, {
        "apps/backend/aisc_backend/projectdb.py",
        "apps/control-objectives/src/aisc_control_objectives/projectdb.py",
        "apps/report-composer/report_composer/projectdb.py",
        "platform/platform_service/projectdb.py",
        "shared/identity/aisc_identity/projectdb.py",
    })


def _module_dirs():
    for base in ("apps", "shared"):
        root = ROOT / base
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith((".", "__")):
                yield child


def _is_domain_slice(module: Path) -> bool:
    """A vertical slice re-implements the layers: its own frontend AND API AND database/migrations."""
    frontend = (module / "package.json").is_file() or (module / "frontend").is_dir()
    api = any((module / name).is_dir() for name in ("routers", "services", "api"))
    database = (
        (module / "alembic.ini").is_file()
        or (module / "manage.py").is_file()
        or (module / "prisma").is_dir()
        or (module / "migrations").is_dir()
    )
    return frontend and api and database


def test_i9_no_domain_slice_module():
    """A module is a layer or a published ABI — not a vertical business-domain slice (frontend+API+DB)."""
    slices = sorted(str(d.relative_to(ROOT)) for d in _module_dirs() if _is_domain_slice(d))
    _baseline(slices, {"apps/qualification", "apps/controls"})


_STEP_CONTAINER = re.compile(r"(?:[-_](?:migrate|setup|grants?|buckets|key)|^make_buckets)$")


def _compose_service_names(path: Path) -> list[str]:
    """Top-level service keys under ``services:`` in a compose file (no YAML dependency)."""
    names: list[str] = []
    in_services = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() == "services:":
            in_services = True
            continue
        if in_services:
            if line and not line[0].isspace():
                break
            match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
            if match:
                names.append(match.group(1))
    return names


def test_i11_no_step_containers():
    """A container runs a long-lived process; migrations/setup/grants are steps, not services (I11)."""
    offenders = []
    for path in sorted(ROOT.glob("docker-compose*.yml")):
        for name in _compose_service_names(path):
            if _STEP_CONTAINER.search(name):
                offenders.append(f"{path.name}:{name}")
    _baseline(offenders, {
        # Re-recorded for the main + frozen-unified-app merged tree (DOC-01 #121): INT-01 kept
        # main's compose files, whose one-shot `make_buckets` steps are known I11 debt. The
        # pilot/docs tree renamed these into docker-compose.engine-standalone.yml (ADR 0001);
        # retiring them is REL-01/REL-02 work.
        "docker-compose.yml:make_buckets",
        "docker-compose-infra.yml:make_buckets",
        "docker-compose-infra.development.yml:make_buckets",
        "docker-compose-infra.staging.yml:make_buckets",
    })
