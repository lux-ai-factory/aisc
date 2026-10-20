"""scripts/verify-plugins.sh: every downloaded plugin installs, from the private catalogue, on the running
stack. It runs with the other checks of the running stack, in a project of its own that every run reuses."""
import re

from conftest import ROOT

SCRIPT = ROOT / "scripts/verify-plugins.sh"
VERIFY = ROOT / "scripts/verify.sh"


def test_verify_stack_runs_the_plugin_check():
    text = VERIFY.read_text()
    stack = re.search(r"for s in ([^;]+); do", text).group(1).split()
    assert "verify-plugins.sh" in stack, stack


def test_the_check_is_executable_reuses_its_project_and_never_prints_the_password():
    """A project keeps its ledger database for good, deleted or not: a project made per run would use up the
    pool, so the check finds its project by name and makes it only the first time."""
    assert SCRIPT.stat().st_mode & 0o111, "not executable"
    text = SCRIPT.read_text()
    assert '"DELETE", f"/api/projects/' not in text
    assert re.search(r'^PROJECT_NAME = "verify plugins"$', text, re.M)
    assert "secrets.token_hex" not in text
    assert "VERIFY_ADMIN_PASSWORD" in text
    assert not re.search(r"(print|say)\([^)]*(password|PASSWORD)", text), "a password reaches the output"


def test_the_check_proves_the_index_holds_the_shared_plugin_interface():
    """Without it a run takes PyPI's aisc-plugin-interface, which has no connector: every plugin that
    reaches its target would fail to import."""
    text = SCRIPT.read_text()
    assert "shared/plugin-interface/pyproject.toml" in text and '"interface"' in text


def _definitions():
    """The check's Python (the heredoc), up to its main lines: the functions only."""
    text = SCRIPT.read_text()
    source = re.search(r"<<'PY'\n(.*)\nPY\n", text, re.S).group(1)
    return source.split("\nheld = index()")[0]


def test_the_install_check_installs_the_newest_version_not_the_lexically_last():
    """sorted(["0.2.9", "0.2.10"]) ends with 0.2.9, so the install check installed and passed an older
    release and never proved the one just published."""
    import json
    import types

    answers = {"root/public": {"projects": ["aisc-langbite"]},
               "root/public/aisc-langbite": {"0.2.9": {}, "0.2.10": {}, "0.2.8": {}}}

    def run(cmd, **kw):
        path = cmd[-1].split("http://localhost:3141/", 1)[1]
        return types.SimpleNamespace(stdout=json.dumps({"result": answers[path]}), returncode=0)

    ns = {"__name__": "verify_plugins"}
    exec(compile(_definitions(), str(SCRIPT), "exec"), ns)
    ns["subprocess"] = types.SimpleNamespace(run=run)
    held = ns["index"]()
    assert held["aisc-langbite"][1] == ["0.2.8", "0.2.9", "0.2.10"]
