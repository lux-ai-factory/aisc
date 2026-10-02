"""C1, C3: every state-changing route of every app is in the ledger's registry (I7, T16).

The routes are read from the code: FastAPI and Django Ninja decorators, the dashboard's Flask-AppBuilder
`@expose(..., methods=[...])`, Next.js route handlers (`route.ts` exporting POST/PUT/PATCH/DELETE) and
Next.js server actions (exported async functions of a "use server" file). Each must be named by a
registry action's `routes`, or be on the reviewed exception list with a reason. And no registry route
may name code that is not there. A route added without its event fails here.
"""
import re
import sys
from pathlib import Path

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "platform"))

EXCEPTIONS = ROOT / "scripts/tests/fixtures/ledger_route_exceptions.txt"

PY_APPS = {
    "platform": ["platform/platform_service/*.py"],
    "control_objectives": ["apps/control-objectives/src/aisc_control_objectives/api/*.py"],
    "report_composer": ["apps/report-composer/report_composer/*.py"],
    "report_renderer": ["apps/report-generator/report_service.py"],
    "catalogue": ["apps/catalogue/backend/*.py"],
    "engine": ["apps/backend/aisc_backend/routers/*.py"],
}
FLASK_APPS = {"dashboard": ["apps/results-dashboard/aisc_ext/**/*.py"]}
NEXT_APPS = {"qualification": "apps/qualification/src/app", "controls": "apps/controls/src/app"}

DECORATOR = re.compile(r'@(?:app|router)\.(post|put|patch|delete)\(\s*"([^"]*)"')
EXPOSE = re.compile(r'@expose\(\s*"([^"]*)"[^)]*methods\s*=\s*\[([^\]]*)\]', re.S)
HANDLER = re.compile(r"export\s+(?:async\s+)?(?:function|const)\s+(POST|PUT|PATCH|DELETE)\b")
ACTION = re.compile(r"export\s+async\s+function\s+(\w+)")


def discovered() -> set[tuple[str, str, str]]:
    found = set()
    for app, globs in PY_APPS.items():
        for pattern in globs:
            for path in ROOT.glob(pattern):
                for method, route in DECORATOR.findall(path.read_text()):
                    found.add((app, method.upper(), route))
    for app, globs in FLASK_APPS.items():
        for pattern in globs:
            for path in ROOT.glob(pattern):
                for route, methods in EXPOSE.findall(path.read_text()):
                    for method in re.findall(r"POST|PUT|PATCH|DELETE", methods):
                        found.add((app, method, route))
    for app, base in NEXT_APPS.items():
        root = ROOT / base
        for path in root.rglob("route.ts"):
            route = "/" + str(path.parent.relative_to(root)).replace("\\", "/")
            for method in HANDLER.findall(path.read_text()):
                found.add((app, method, route))
        for path in list(root.rglob("*.ts")) + list(root.rglob("*.tsx")):
            text = path.read_text()
            if not re.match(r"\s*['\"]use server['\"]", text):
                continue
            rel = str(path.relative_to(ROOT / base.rsplit("/src/app", 1)[0]))
            for name in ACTION.findall(text):
                found.add((app, "ACTION", f"{rel}#{name}"))
    return found


def exceptions() -> dict[tuple[str, str, str], str]:
    out = {}
    for line in EXCEPTIONS.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        spec, _, reason = line.partition("#")
        app, method, route = spec.split()
        out[(app, method, route)] = reason.strip()
    return out


def registered() -> set[tuple[str, str, str]]:
    from platform_service.ledger.registry import REGISTRY

    return {tuple(r) for action in REGISTRY.values() for r in action.routes}


def test_the_code_has_state_changing_routes_to_check():
    # the discovery itself works: a broken pattern would let every route through unnoticed
    found = discovered()
    assert ("platform", "POST", "/projects") in found
    assert ("control_objectives", "POST", "/p/{project}/api/projects/{project_id}/ratings") in found
    assert any(app == "qualification" and method == "ACTION" for app, method, _ in found)
    assert any(app == "engine" for app, _, _ in found)


def test_every_exception_has_a_reason_and_still_exists():
    found = discovered()
    for route, reason in exceptions().items():
        assert reason, f"{route}: an exception needs its reason"
        assert route in found, f"{route}: the exception names a route that no longer exists"


def test_every_state_changing_route_has_its_event():
    missing = sorted(discovered() - registered() - set(exceptions()))
    assert not missing, "routes with no ledger event (add one to the registry, or a reasoned exception):\n" + \
        "\n".join(" ".join(r) for r in missing)


def test_no_registry_route_names_code_that_is_not_there():
    stale = sorted(registered() - discovered())
    assert not stale, "registry routes not found in the code:\n" + "\n".join(" ".join(r) for r in stale)
