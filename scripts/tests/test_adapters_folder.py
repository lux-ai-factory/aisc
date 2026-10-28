"""The adapters/ folder of an install: its README is the adapter contract, and everything else in it stays out
of git, so an operator's adapters (and the systems they name) are never committed with AISC."""
import re
import subprocess

from conftest import ROOT

README = ROOT / "adapters/README.md"


def test_the_readme_documents_the_contract_with_a_made_up_example():
    assert README.is_file(), "missing feature: adapters/README.md does not exist"
    text = README.read_text()
    for needed in ("PROTOCOL", "def call(connection, input, history, params, open)", "max_concurrent",
                   "refused", "auth", "not_found", "timeout", "bad_response", "restart", "example-chat",
                   "PLATFORM_ADAPTERS_DIR"):
        assert needed in text, f"the README does not say {needed!r}"
    hosts = set(re.findall(r"https?://([^/\s`\"')]+)", text))
    assert hosts and all(h.endswith("example.org") for h in hosts), f"the README names a real system: {hosts}"


def test_everything_but_the_readme_is_ignored_by_git():
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    assert "adapters/*" in ignore and "!adapters/README.md" in ignore
    ignored = subprocess.run(["git", "check-ignore", "-q", "adapters/example/adapter.py"], cwd=ROOT)
    assert ignored.returncode == 0, "an adapter folder would be committed"
    kept = subprocess.run(["git", "check-ignore", "-q", "adapters/README.md"], cwd=ROOT)
    assert kept.returncode == 1, "the README would be ignored"
