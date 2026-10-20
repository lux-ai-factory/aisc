"""The README lists everything an install needs."""
from conftest import ROOT

README = ROOT / "README.md"


def test_the_readme_lists_what_an_install_needs():
    """Every requirement to install and run the whole stack is in the README itself."""
    pre = README.read_text().split("## Prerequisites", 1)[1].split("\n## ", 1)[0]
    for needed in ("Compose 2.17", "x86_64", "RAM", "GB of disk", "private", "catalogue", "uv", "Git LFS", "Docker Desktop", "Windows", "Internet",
                   "PyPI", "npm", "GITHUB_TOKEN", "8081", "5432"):
        assert needed in pre, needed


def test_the_readme_names_the_one_private_submodule_and_that_the_install_does_not_need_it():
    pre = README.read_text().split("## Prerequisites", 1)[1].split("\n## ", 1)[0]
    assert "aisc-add-controls-catalogue" in pre and "Four submodules are private" not in pre


def test_installing_needs_no_unix_tool_and_is_the_same_command_everywhere():
    """Windows users run what everyone runs: no bash, openssl or curl to install, Linux line endings kept."""
    text = README.read_text()
    install = text.split("## Install and run", 1)[1].split("\n## ", 1)[0]
    assert "uv run scripts/aisc.py start" in install and "uv run scripts/aisc.py password" in install
    assert "git -c core.autocrlf=false clone --recursive" in install
    pre = text.split("## Prerequisites", 1)[1].split("\n## ", 1)[0]
    assert "openssl" not in pre and "curl" not in pre


def test_the_readme_walks_the_four_steps_of_the_project_page():
    intro = README.read_text().split("## Prerequisites", 1)[0]
    assert "four steps" in intro and "six steps" not in intro
    for step in ("**1** Qualify the AI system", "**2** Set control objectives", "**3** Choose tests and checklists",
                 "**4** Collect evidence"):
        assert step in intro, step
