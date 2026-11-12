"""Architectural guards — one check per invariant in ../../ARCHITECTURE.md.

Standard library only (AST + file checks), so these run with no module venv:

    uv run --no-project --with pytest python -m pytest tests/architecture -q

A guard marked ``xfail`` is an invariant the current code does not yet meet. It documents the gap and
starts passing (``xpass``) once the code is fixed — then remove the marker, never the test. Do not relax or
delete a guard to make a change merge; add an allowlist entry plus the ADR (see ../../docs/adr).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SKIP = {"node_modules", ".venv", "__pycache__", ".git"}


def _files(pattern: str):
    for path in ROOT.glob(pattern):
        if _SKIP.isdisjoint(path.parts):
            yield path


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


def _function_source(path: Path, name: str) -> str:
    """The source of one function, so a guard can scan a path rather than a file."""
    text = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(text, node) or ""
    return ""


def test_i1_worker_does_not_fetch_from_backend_midrun():
    """The run path uses only what it was dispatched with; the only run->backend call posts results.

    Only ``run_plugin`` — the run path — is scanned. Fetching at *dispatch* (``run_evaluation``)
    is how a run is made self-contained, so those calls are expected and allowed; a fetch inside
    ``run_plugin`` is the violation.
    """
    fetches = {
        "get_evaluation_request", "get_evaluation_inputs", "get_dataset_file_content",
        "get_model_file_content", "get_project_settings_by_pid", "get_evaluation_plugins_status",
    }
    src = _function_source(ROOT / "apps/eval/aisc_eval/celery_tasks.py", "run_plugin")
    assert src, "could not locate the run path (run_plugin)"
    used = sorted(name for name in fetches if f"{name}(" in src)
    assert not used, f"mid-run backend fetches in the run path: {used}"


def test_i4_one_deployment_contract():
    """The deployment-mode contract lives in exactly one module, or is replaced by feature flags."""
    found = sorted(str(p.relative_to(ROOT)) for p in _files("apps/**/deployment.py"))
    assert not found, f"the deployment-mode contract is implemented in {len(found)} places: {found}"


def test_i3_one_project_database_module():
    """One project-database path, not two."""
    found = sorted(str(p.relative_to(ROOT)) for p in _files("**/projectdb.py"))
    assert len(found) <= 1, f"more than one project-DB module: {found}"


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


@pytest.mark.xfail(reason="I9: qualification and controls are domain slices (ARCHITECTURE.md I9)",
                   strict=False)
def test_i9_no_domain_slice_module():
    """A module is a layer or a published ABI — not a vertical business-domain slice (frontend+API+DB)."""
    slices = sorted(str(d.relative_to(ROOT)) for d in _module_dirs() if _is_domain_slice(d))
    assert not slices, "modules that re-implement the layers as a domain slice: " + ", ".join(slices)


_STEP_CONTAINER = re.compile(r"-(migrate|setup|grants|buckets|key)$")


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


@pytest.mark.xfail(reason="I11: steps run as containers in the compose files (ARCHITECTURE.md I11)",
                   strict=False)
def test_i11_no_step_containers():
    """A container runs a long-lived process; migrations/setup/grants are steps, not services (I11)."""
    offenders = []
    for path in sorted(ROOT.glob("docker-compose*.yml")):
        for name in _compose_service_names(path):
            if _STEP_CONTAINER.search(name):
                offenders.append(f"{path.name}:{name}")
    assert not offenders, "step containers that should be steps/profiles: " + ", ".join(offenders)


# ---------------------------------------------------------------------------
# Guards added in Phase 0 (see docs/refactor-plan.md §2 step 0.6).
# Each is a mechanical check on today's code; an xfail names the gap a later
# step closes. A guard is never deleted or relaxed — an ADR plus an allowlist
# entry is the only sanctioned exception (docs/adr/README.md).
# ---------------------------------------------------------------------------

ALLOWLIST = Path(__file__).with_name("allowlist.json")


def _allowlisted(invariant: str, path: str) -> bool:
    """True when an ADR-backed allowlist entry covers this path for the invariant."""
    if not ALLOWLIST.exists():
        return False
    entries = json.loads(ALLOWLIST.read_text(encoding="utf-8")).get(invariant, [])
    return any(path == e["path"] or path.startswith(e["path"].rstrip("/") + "/") for e in entries)


def _backend_settings() -> ast.Module:
    return ast.parse((ROOT / "apps/backend/config/settings.py").read_text(encoding="utf-8"))


def _assigned_value(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return node.value
    return None


def _mutates(tree: ast.Module, name: str) -> bool:
    """True when a module-level statement rewrites a setting (``+=``, ``.append``, a ternary)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return True
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"append", "extend", "insert", "update"}
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == name
        ):
            return True
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.IfExp):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return True
    return False


def test_i4_app_graph_is_static():
    """INSTALLED_APPS/MIDDLEWARE are literals: no configuration rewrites the app graph (I4)."""
    tree = _backend_settings()
    problems = []
    for name in ("INSTALLED_APPS", "MIDDLEWARE"):
        value = _assigned_value(tree, name)
        if value is None:
            problems.append(f"{name} is not a module-level assignment")
            continue
        if not isinstance(value, (ast.List, ast.Tuple)):
            problems.append(f"{name} is not a literal list")
        if _mutates(tree, name):
            problems.append(f"{name} is rewritten at import time")
    assert not problems, "the app graph changes with configuration: " + "; ".join(problems)


def test_i4_urlconf_is_static():
    """The URLconf is assembled without branching on configuration (I4)."""
    src = (ROOT / "apps/backend/config/urls.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    branchy = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.If, ast.IfExp))
        and any(
            isinstance(sub, ast.Name) and sub.id in {"urlpatterns", "api", "v1_router"}
            for sub in ast.walk(node)
        )
    ]
    assert not branchy, f"the URLconf branches on configuration at lines {branchy}"


def _installed_local_apps() -> list[str]:
    value = _assigned_value(_backend_settings(), "INSTALLED_APPS")
    if not isinstance(value, (ast.List, ast.Tuple)):
        return []
    names = []
    for element in value.elts:
        if isinstance(element, ast.Constant) and isinstance(element.value, str):
            if element.value.startswith("aisc_backend"):
                names.append(element.value)
    return names


def test_i5_installed_app_owns_tables():
    """An installed app owns tables: it carries models and its own migrations (I5/D11)."""
    offenders = []
    for app in _installed_local_apps():
        path = ROOT / "apps/backend" / Path(*app.split("."))
        has_models = (path / "models.py").is_file() or (path / "models").is_dir()
        has_migrations = (path / "migrations").is_dir()
        if not (has_models and has_migrations):
            offenders.append(app)
    assert not offenders, "installed apps that own no tables (a concern dressed as an app): " + ", ".join(offenders)


def _migration_tools() -> list[str]:
    """Second migration tools: Alembic configs and Prisma schemas under ``apps/``."""
    found = []
    for pattern in ("apps/*/alembic.ini", "apps/*/*/alembic.ini", "apps/*/prisma/schema.prisma",
                    "apps/*/*/prisma/schema.prisma", "apps/*/*/schema.prisma"):
        for path in ROOT.glob(pattern):
            if _SKIP.isdisjoint(path.parts):
                found.append(str(path.relative_to(ROOT)))
    return sorted(found)


@pytest.mark.xfail(reason="I5: qualification and controls carry their own Prisma migration tool "
                          "(ARCHITECTURE.md I5)", strict=False)
def test_i5_one_migration_tool():
    """Schema changes go through one migration tool — Django's (I5)."""
    found = _migration_tools()
    assert not found, "additional migration tools beside Django's: " + ", ".join(found)


def test_i3_no_second_ledger():
    """Who changed what is recorded once: no outbox/relay beside the audit writer (I3/I6)."""
    offenders = []
    for path in _files("**/*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"class\s+LedgerOutbox\b", text) or re.search(r"class\s+\w*Outbox\b", text):
            offenders.append(str(path.relative_to(ROOT)))
    for path in _files("**/outbox.py"):
        offenders.append(str(path.relative_to(ROOT)))
    assert not sorted(set(offenders)), "a second record of governed changes: " + ", ".join(sorted(set(offenders)))


@pytest.mark.xfail(reason="I3/I9: qualification and controls carry product UI outside the webapp "
                          "(ARCHITECTURE.md I9)", strict=False)
def test_i3_no_product_ui_outside_webapp():
    """Product UI lives in the webapp: no static launcher site beside it (I3/I9/D12)."""
    offenders = []
    for candidate in ROOT.iterdir():
        if not candidate.is_dir() or candidate.name.startswith((".", "apps", "shared", "tests", "docs")):
            continue
        if any(candidate.glob("*.html")) and _allowlisted("I3", candidate.name) is False:
            offenders.append(candidate.name)
    for candidate in (ROOT / "apps").iterdir() if (ROOT / "apps").is_dir() else []:
        if candidate.is_dir() and candidate.name not in {"webapp", "backend", "eval"}:
            if any(candidate.glob("*.html")) or (candidate / "public").is_dir():
                if not _allowlisted("I3", f"apps/{candidate.name}"):
                    offenders.append(f"apps/{candidate.name}")
    assert not offenders, "product UI outside the webapp: " + ", ".join(sorted(set(offenders)))


_OPTIONAL = {"qualification", "controls", "control_objectives", "control_objectives_app", "report"}


def test_i10_core_does_not_import_optional():
    """The core imports no optional domain; dependencies point coreward (I10)."""
    bad = []
    for pattern in ("apps/backend/aisc_backend/**/*.py", "apps/eval/aisc_eval/**/*.py",
                    "apps/webapp/src/**/*.ts", "apps/webapp/src/**/*.tsx"):
        for path in _files(pattern):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for name in _OPTIONAL:
                if re.search(rf"(^|\s)(from|import)\s+{name}\b", text, re.MULTILINE) or re.search(
                    rf"from\s+['\"][^'\"]*{name}", text
                ):
                    bad.append(f"{path.relative_to(ROOT)} -> {name}")
    assert not bad, "core code depends on an optional domain: " + ", ".join(sorted(set(bad)))


def test_i2_plugin_environment_is_an_allowlist():
    """The plugin subprocess gets a filtered environment, not the worker's whole environment (I2/I7)."""
    src = (ROOT / "apps/eval/aisc_eval/celery_tasks.py").read_text(encoding="utf-8")
    assert "os.environ.copy()" not in src, (
        "the plugin subprocess inherits the worker's environment; build its environment from an "
        "allowlist so no worker credential reaches untrusted plugin code"
    )


_SCRUB = re.compile(r"\bscrub\w*\(")


def test_i7_outbound_paths_scrub():
    """Every path that can carry a secret outward (log, artifact, error, message) scrubs it (I7)."""
    src = (ROOT / "apps/eval/aisc_eval/celery_tasks.py").read_text(encoding="utf-8")
    offenders = []
    if "plugin_execution.log" in src and not _SCRUB.search(src):
        offenders.append("plugin_execution.log is written without a scrub")
    if "upload_artifact(" in src and not _SCRUB.search(src):
        offenders.append("artifacts are uploaded without a scrub")
    if "_fail_plugin_and_revoke(" in src and not _SCRUB.search(src):
        offenders.append("failure messages are sent without a scrub")
    assert not offenders, "; ".join(offenders)


def test_i3_shared_artifacts_are_acyclic():
    """The published shared ABIs do not depend on each other (I3/I9)."""
    bad = _importers("shared/plugin-interface/**/*.py", {"aisc_plugin_manager", "aisc_backend", "aisc_eval"})
    bad += _importers("shared/plugin-manager/**/*.py", {"aisc_backend", "aisc_eval"})
    assert not bad, "shared ABIs depend on each other or on the engine:\n" + "\n".join(bad)


def test_allowlist_entries_are_adr_backed():
    """An allowlist entry is a waiver with an accepted ADR — the only sanctioned exception (I8)."""
    if not ALLOWLIST.exists():
        return
    entries = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    problems = []
    for invariant, items in entries.items():
        if invariant.startswith("_"):
            continue
        for item in items:
            adr = ROOT / "docs/adr" / f"{item['adr']}"
            if not adr.is_file():
                problems.append(f"{invariant}: {item['path']} names missing ADR {item['adr']}")
                continue
            head = adr.read_text(encoding="utf-8").splitlines()[:4]
            if not any("Status:" in line and "accepted" in line.lower() for line in head):
                problems.append(f"{invariant}: {item['path']} ADR {item['adr']} is not accepted")
    assert not problems, "allowlist entries without an accepted ADR:\n" + "\n".join(problems)
