"""Every state-changing route of every app writes a ledger event.

Routes are found in the code (ledger_routes.py), keyed by app, file and function. Each state-changing
one must be named by a registry action's `routes`, or be on the reviewed exception list with a reason
(fixtures/ledger_route_exceptions.tsv). No registry route may name code that is not there. For the
apps in EMITTING_APPS, the handler of a registered route must itself call the emitter with that
action, so a registry entry alone covers nothing. Some apps do not emit yet, so this file is expected
to fail until they do.
"""
import ast
import re
import sys

import pytest

from conftest import ROOT
from ledger_routes import SCOPED_OUT, WRITES, discovered

sys.path.insert(0, str(ROOT / "platform"))

EXCEPTIONS = ROOT / "scripts/tests/fixtures/ledger_route_exceptions.tsv"
#: The apps whose handlers emit their own events. The engine is not changed here: its events come from
#: the one registered forwarding module.
EMITTING_APPS = {"platform", "qualification", "controls", "control_objectives", "report_composer", "dashboard",
                 "qualification_agents"}
EMIT_CALL = re.compile(r"\b(ledger\.emit|emit_event|emitEvent|ledgerEmit|ledger_emit)\s*\(")


def found():
    return discovered(ROOT)


def writes():
    return {r for r in found() if r[1] in WRITES}


def key(route):
    app, _, file, function = route
    return (app, file, function)


def exceptions() -> dict:
    out = {}
    for line in EXCEPTIONS.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        assert len(parts) == 4, f"exception line needs 4 tab-separated fields: {line!r}"
        out[tuple(parts[:3])] = parts[3].strip()
    return out


def registered() -> dict:
    """route -> the actions it emits (a handler can emit several, such as retire and restore)."""
    from platform_service.ledger.registry import REGISTRY

    out: dict = {}
    for name, action in REGISTRY.items():
        for r in action.routes:
            out.setdefault(tuple(r), set()).add(name)
    return out


def test_discovery_finds_what_the_review_said_was_missed():
    f = {key(r) for r in found()}
    assert ("platform", "platform/platform_service/app.py", "add_project") in f
    assert ("control_objectives", "apps/control-objectives/src/aisc_control_objectives/api/app.py", "rate") in f
    assert ("engine", "apps/backend/aisc_backend/routers/audit.py", "post_audit") in f
    assert any(a == "dashboard" and m == "MODELVIEW" for a, m, _, _ in found())         # FAB views
    assert any(a == "connectors" for a, _, _, _ in writes())                             # connectors admin
    assert any(a == "qualification_agents" for a, _, _, _ in writes())                   # the AI run
    assert any(a == "qualification" and m == "ACTION" for a, m, _, _ in found())         # server actions
    assert any(m == "GET" for _, m, _, _ in found())                                     # reads are found too


def test_routes_with_the_same_relative_path_stay_apart():
    """Ninja routers all declare `@router.post("")`: one key per handler, not one per path."""
    engine_posts = [r for r in writes() if r[0] == "engine" and r[1] == "POST"]
    assert len({key(r) for r in engine_posts}) == len(engine_posts) > 1


def test_scoped_out_code_has_a_reason():
    for path, reason in SCOPED_OUT.items():
        assert (ROOT / path).exists() and reason, path


def test_every_discovered_app_is_known():
    from platform_service.ledger.registry import KNOWN_APPS

    assert {r[0] for r in found()} <= set(KNOWN_APPS)


def test_every_exception_has_a_reason_and_still_exists():
    keys = {key(r) for r in found()}
    for route, reason in exceptions().items():
        assert reason, f"{route}: an exception needs its reason"
        assert route in keys, f"{route}: the exception names a route that no longer exists"


def test_every_state_changing_route_has_its_event():
    covered = set(registered()) | set(exceptions())
    missing = sorted(key(r) for r in writes() if key(r) not in covered)
    assert not missing, "routes with no ledger event (add one to the registry, or a reasoned exception):\n" + \
        "\n".join(" ".join(r) for r in missing)


def test_no_registry_route_names_code_that_is_not_there():
    keys = {key(r) for r in found()}
    stale = sorted(r for r in registered() if r not in keys)
    assert not stale, "registry routes not found in the code:\n" + "\n".join(" ".join(r) for r in stale)


def _source(file: str, function: str) -> str:
    text = (ROOT / file).read_text(errors="replace")
    if file.endswith(".py"):
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == function:
                return ast.get_source_segment(text, node) or ""
        return ""
    return text                                                     # a TS module: the whole file


@pytest.mark.parametrize("app", sorted(EMITTING_APPS))
def test_a_registered_handler_emits_its_action(app):
    """The handler (or its module, for TypeScript) calls the emitter with the action's name."""
    problems = []
    for (route_app, file, function), actions in registered().items():
        if route_app != app:
            continue
        body = _source(file, function)
        for action in sorted(actions):
            named = f'"{action}"' in body or f"'{action}'" in body
            if not (EMIT_CALL.search(body) and named):
                problems.append(f"{file}:{function} does not emit {action}")
    assert registered(), "the registry names no routes yet"
    assert not problems, "\n".join(problems)
