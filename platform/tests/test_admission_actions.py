"""Who may do what with a project's connections, their uses, model keys and helper models is written in one
table, admission.ACTIONS, and the routes name an action from it, never a role: an auditor's question such as
"who can hand a key to a plugin" is answered by reading the table.

A walk over the routers that handle connections, keys and helpers fails when a route (or a function of its
module) checks a role itself, or names an action the table does not have. Pure: no database."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from platform_service.routes import admission

ROUTES = Path(admission.__file__).parent
#: the routers whose gate is the table
GATED = ("connections.py", "targets.py", "allowed_hosts.py", "run_passes.py", "connectivity.py", "helpers.py",
         "llm.py")
#: the role checks a route must not call itself
ROLE_CHECKS = {"role_or_404", "admin_project", "owner_or_403", "admitted"}
GATES = {"project_for", "allowed_actions"}


def _routes_and_functions(path: Path):
    tree = ast.parse(path.read_text())
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    routes = [f for f in functions.values()
              if any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                     and isinstance(d.func.value, ast.Name) and d.func.value.id == "router" for d in f.decorator_list)]
    return routes, functions


def _called(node) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _name(call: ast.Call) -> str:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def test_every_action_needs_a_known_rank():
    assert admission.ACTIONS
    assert set(admission.ACTIONS.values()) <= {"viewer", "editor", "owner", "admin"}


@pytest.mark.parametrize("module", GATED)
def test_no_route_of_a_gated_router_checks_a_role_itself(module):
    _routes, functions = _routes_and_functions(ROUTES / module)
    direct = sorted(f"{name} calls {_name(c)}" for name, f in functions.items() for c in _called(f)
                    if _name(c) in ROLE_CHECKS)
    assert direct == []


@pytest.mark.parametrize("module", GATED)
def test_every_route_with_a_person_names_an_action_from_the_table(module):
    routes, functions = _routes_and_functions(ROUTES / module)
    gated_helpers = {name for name, f in functions.items() if any(_name(c) in GATES for c in _called(f))}
    missing, unknown = [], []
    for route in routes:
        if "caller" not in [a.arg for a in route.args.args]:
            continue                                          # an internal route, gated by its token
        named = {n.id for n in ast.walk(route) if isinstance(n, ast.Name)} | {_name(c) for c in _called(route)}
        if not named & (GATES | gated_helpers):              # called, or handed to a thread pool
            missing.append(route.name)
    for f in functions.values():
        for c in _called(f):
            args = c.args
            if args and isinstance(args[0], ast.Name) and args[0].id in GATES:   # run_in_threadpool(gate, ...)
                args = args[1:]
            elif _name(c) not in GATES:
                continue
            unknown += [a.value for a in args[2:3] if isinstance(a, ast.Constant) and a.value not in admission.ACTIONS]
    assert missing == [] and unknown == []
