"""The README is the short way in: what AISC is, how to install it, how to contribute. Everything else
(components, how it works, configuration, tests) is in docs/guide.md, which the README points to."""
from conftest import ROOT

README = ROOT / "README.md"
GUIDE = ROOT / "docs" / "guide.md"


def test_the_readme_is_short_and_points_to_the_guide():
    text = README.read_text()
    assert len(text.splitlines()) <= 90
    assert "docs/guide.md" in text and GUIDE.exists()
    for heading in ("## Install and run", "## Contributing"):
        assert heading in text, heading


def test_the_readme_sets_no_branch_rule_for_contributors():
    contributing = README.read_text().split("## Contributing", 1)[1]
    assert "only branch" not in contributing and "side branches" not in contributing


def test_the_details_moved_to_the_guide_not_away():
    guide = GUIDE.read_text()
    for heading in ("## Components", "## How it works", "## Configuration", "## Tests", "### PostgreSQL 15"):
        assert heading in guide, heading


def test_the_readme_lists_what_an_install_needs():
    """2026-10-06: every requirement to install and run the whole stack is in the README itself."""
    pre = README.read_text().split("## Prerequisites", 1)[1].split("\n## ", 1)[0]
    for needed in ("Compose 2.17", "x86_64", "RAM", "GB of disk", "private", "catalogue", "report-generator",
                   "report-plugin-interface", "token", "bash", "openssl", "Internet",
                   "PyPI", "npm", "GITHUB_TOKEN", "8081", "5432"):
        assert needed in pre, needed
