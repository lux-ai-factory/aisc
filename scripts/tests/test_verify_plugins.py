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


def test_the_check_no_longer_reads_what_the_removed_downloader_cloned():
    """Plugins are fetched when a person installs a test: there is no def_plugins folder to glob and no
    plugin-downloader container to read logs from."""
    text = SCRIPT.read_text()
    assert "def_plugins" not in text and "plugin-downloader" not in text


def _load(run):
    import types
    ns = {"__name__": "verify_plugins"}
    exec(compile(_definitions(), str(SCRIPT), "exec"), ns)
    ns["subprocess"] = types.SimpleNamespace(run=run)
    lines = []
    ns["say"] = lambda kind, check, text: lines.append((kind, check, text))
    return ns, lines


def _answer(stdout, returncode=0):
    import types
    return lambda cmd, **kw: types.SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)


def test_a_healthy_publisher_passes_and_says_when_the_interface_is_not_published_yet():
    ns, lines = _load(_answer('{"interface_published": true}'))
    ns["publisher_health"]()
    assert [k for k, c, _ in lines if c == "publisher"] == ["PASS"]
    ns, lines = _load(_answer('{"interface_published": false}'))
    ns["publisher_health"]()
    assert [k for k, c, _ in lines if c == "publisher"] == ["FAIL"]


def test_a_publisher_that_does_not_answer_fails_naming_its_logs():
    ns, lines = _load(_answer("", returncode=1))
    ns["publisher_health"]()
    kind, check, text = lines[0]
    assert (kind, check) == ("FAIL", "publisher") and "docker logs plugin-publisher" in text


def test_install_mode_takes_a_slug_and_needs_no_secret_on_the_command_line():
    """The admin password stays in the environment; the argument is the catalogue entry's slug only."""
    text = SCRIPT.read_text()
    assert "--install" in text
    assert "/install\"" in text or "/install'" in text or "/install\"," in text
    ns, _ = _load(_answer(""))
    assert ns["install_slug"](["--install", "langbite"]) == "langbite"
    assert ns["install_slug"]([]) is None


def test_a_catalogue_chosen_on_an_earlier_run_is_not_a_failure():
    """The project is reused, and a catalogue choice is final: the platform answers 409 "this project chose its
    catalogue already". That is "already chosen", so the check goes on; any other 409 is still a failure."""
    class Session:
        def __init__(self, detail):
            self.detail, self.asked = detail, []

        def call(self, method, path, body=None, timeout=60):
            self.asked.append((method, path))
            if method == "POST":
                return 409, {"detail": self.detail}
            return 200, []

    ns, lines = _load(_answer(""))
    again = Session("this project chose its catalogue already")
    ns["private_catalogue"](again, "verify-plugins", {})
    assert not [k for k, _, _ in lines if k == "FAIL"], lines
    assert ("GET", "/api/projects/verify-plugins/catalogue/api/tool/?detailed=true") in again.asked

    ns, lines = _load(_answer(""))
    other = Session("some other conflict")
    ns["private_catalogue"](other, "verify-plugins", {})
    assert [k for k, c, _ in lines] == ["FAIL"] and len(other.asked) == 1
