"""Secret redaction lives in one module, aisc_redact (shared/identity). Every Python service that can import it does,
and keeps no pattern of its own; the copies that cannot import it (the agents, the plugin publisher, the plugin
interface) run the shared vectors, redaction-cases.json, in their own suites.

Read-only: the source files as text.
"""

import re

from conftest import ROOT

IMPORTERS = {
    "backend": "apps/backend/aisc_backend/config_secrets.py",
    "eval": "apps/eval/aisc_eval/scrub.py",
    "platform ledger": "platform/platform_service/ledger/config_secrets.py",
    "facade": "platform/platform_service/connection_facade.py",
    "control-objectives": "apps/control-objectives/src/aisc_control_objectives/errors.py",
}
#: copies that cannot import the module, and the suite folder that must run the vectors
COPIES = {
    "apps/qualification/services/agents/fill/errors.py": "apps/qualification/services/agents/tests",
    "infra/plugin-publisher/plugin_publisher/git.py": "infra/plugin-publisher/tests",
    "shared/plugin-interface/src/aisc_plugin_interface/connections.py": "shared/plugin-interface/tests",
}


def test_the_one_rule_exists_with_its_vectors():
    assert (ROOT / "shared/identity/aisc_redact/__init__.py").is_file(), "no aisc_redact module"
    assert (ROOT / "shared/identity/redaction-cases.json").is_file(), "no shared redaction vectors"
    assert "aisc_redact" in (ROOT / "shared/identity/pyproject.toml").read_text(), "aisc_redact is not packaged"


#: patterns these files keep that are no secret rule: the facade's checks of a parameter's and a tool's name
NOT_SECRET_RULES = {"PARAM_NAME", "_TOOL_NAME"}
COMPILED = re.compile(r"^(\w+)\s*=\s*re\.compile\(|\bre\.compile\(", re.M)


def _own_patterns(text: str) -> list[str]:
    return [m.group(0) for m in COMPILED.finditer(text) if m.group(1) not in NOT_SECRET_RULES]


def test_every_python_service_that_can_imports_the_one_rule():
    own = []
    for name, f in IMPORTERS.items():
        text = (ROOT / f).read_text()
        if "aisc_redact" not in text or _own_patterns(text):
            own.append(name)
    assert own == [], "these keep a secret rule of their own"


def test_every_copy_that_cannot_import_runs_the_shared_vectors():
    missing = [copy for copy, suite in COPIES.items()
               if not any("redaction-cases.json" in p.read_text() for p in (ROOT / suite).rglob("test_*.py"))]
    assert missing == [], "these copies are not held to the shared vectors"
