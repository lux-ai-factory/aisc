"""scripts/verify-plugins.sh: every downloaded plugin installs, from the private catalogue, on the running
stack. It runs with the other checks of the running stack, and it takes its throwaway project away."""
import re

from conftest import ROOT

SCRIPT = ROOT / "scripts/verify-plugins.sh"
VERIFY = ROOT / "scripts/verify.sh"


def test_verify_stack_runs_the_plugin_check():
    text = VERIFY.read_text()
    stack = re.search(r"for s in ([^;]+); do", text).group(1).split()
    assert "verify-plugins.sh" in stack, stack


def test_the_check_is_executable_and_cleans_up_and_never_prints_the_password():
    assert SCRIPT.stat().st_mode & 0o111, "not executable"
    text = SCRIPT.read_text()
    assert "finally:" in text and '"DELETE", f"/api/projects/' in text, "the throwaway project must go, also after a failure"
    assert "VERIFY_ADMIN_PASSWORD" in text
    assert not re.search(r"(print|say)\([^)]*(password|PASSWORD)", text), "a password reaches the output"


def test_the_check_proves_the_index_holds_the_shared_plugin_interface():
    """Without it a run takes PyPI's aisc-plugin-interface, which has no connector: every plugin that
    reaches its target would fail to import."""
    text = SCRIPT.read_text()
    assert "shared/plugin-interface/pyproject.toml" in text and '"P0"' in text
