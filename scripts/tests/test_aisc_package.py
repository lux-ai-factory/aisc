"""The install script is a package, scripts/aisc/, one module per job (secrets, ports, keycloak, docker, stack,
settings), while scripts/aisc.py keeps its commands and every name the tests and the wrappers read. Every docker
call goes through the Stack, and the docker command is never rebound as a global.

Read-only: the files as text, and scripts/aisc.py loaded as a module.
"""

import ast
import re

from conftest import ROOT, aisc_py

PACKAGE = ROOT / "scripts/aisc"
MODULES = ("secrets", "ports", "keycloak", "docker", "stack", "settings")
PUBLIC = ["SECRETS", "VOLUME_BOUND", "KEPT_ON_ROTATE", "FRESH_ON_ROTATE", "account", "fresh", "settle_ports",
          "choose_port", "published_ports", "sign_in_clients", "Stack", "hide_secrets", "make_secrets", "main",
          "caddy_bind_address", "realm_hardening_commands", "optional_compose_files"]


def test_the_package_has_one_module_per_job():
    assert PACKAGE.is_dir(), "scripts/aisc.py is still one file"
    assert [m for m in MODULES if not (PACKAGE / f"{m}.py").is_file()] == []


def test_the_entry_script_keeps_every_name_and_is_small():
    m = aisc_py()
    assert [n for n in PUBLIC if not hasattr(m, n)] == []
    lines = len((ROOT / "scripts/aisc.py").read_text().splitlines())
    assert lines < 200, f"scripts/aisc.py has {lines} lines"


def test_no_module_is_large():
    assert PACKAGE.is_dir(), "scripts/aisc.py is still one file"
    large = {f.name: n for f in PACKAGE.glob("*.py") if (n := len(f.read_text().splitlines())) >= 600}
    assert large == {}


def test_no_docker_call_bypasses_the_stack():
    sources = [f for f in PACKAGE.glob("*.py") if f.name != "docker.py"] if PACKAGE.is_dir() else \
        [ROOT / "scripts/aisc.py"]
    bypass = []
    for f in sources:
        for node in ast.walk(ast.parse(f.read_text())):
            if isinstance(node, ast.Attribute) and node.attr in ("run", "Popen") and \
                    isinstance(node.value, ast.Name) and node.value.id == "subprocess":
                bypass.append((f.name, node.lineno))
    assert bypass == [], "these call docker past the Stack"


def test_global_docker_is_never_rebound():
    files = [ROOT / "scripts/aisc.py", *(PACKAGE.glob("*.py") if PACKAGE.is_dir() else [])]
    # the docker command itself, not another flag whose name starts with it (DOCKER_UNANSWERED)
    assert [f.name for f in files if re.search(r"global DOCKER\b", f.read_text())] == []
