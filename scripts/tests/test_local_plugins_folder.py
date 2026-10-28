"""local_plugins/ of an install: its README says how a plugin of one's own reaches the catalogue (drop the folder,
private catalogue, Install) with no step by hand, and everything else in it stays out of git."""
import subprocess

from conftest import ROOT

README = ROOT / "local_plugins/README.md"


def test_the_readme_says_how_a_plugin_of_ones_own_is_installed():
    text = README.read_text()
    for needed in ("pyproject.toml", "aisc-plugin-interface", "Private", "Local", "Install", "publisher",
                   "version"):
        assert needed in text, f"the README does not say {needed!r}"
    for manual in ("twine", "docker cp", "docker exec"):
        assert manual not in text, f"the README asks for a step by hand: {manual}"
    # a project that has the plugin shows it as Installed: the catalogue offers no second install there
    assert "press **Install** again" not in text and "Installed" in text
    assert ".env" in text


def test_everything_but_the_readme_is_ignored_by_git():
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    assert "local_plugins/*" in ignore and "!local_plugins/README.md" in ignore
    assert subprocess.run(["git", "check-ignore", "-q", "local_plugins/my-plugin/pyproject.toml"], cwd=ROOT).returncode == 0
    assert subprocess.run(["git", "check-ignore", "-q", "local_plugins/README.md"], cwd=ROOT).returncode == 1
