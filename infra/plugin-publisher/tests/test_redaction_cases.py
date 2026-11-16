"""The publisher keeps its own scrub (plugin_publisher.git.scrub: the values of its secret variables, as they are,
become ***), since it does not carry aisc_redact. It runs the "echo" cases of the shared vectors
(shared/identity/redaction-cases.json) whose secret is echoed as it is, and gives the shared rule's answer; the
encoded forms are the platform's and the plugin interface's to take out, not the publisher's."""
import json
from pathlib import Path

import pytest

from plugin_publisher import git

CASES = json.loads((Path(__file__).resolve().parents[3] / "shared/identity/redaction-cases.json").read_text())
AS_IS = [case for case in CASES["echo"] if case["form"] in ("as_is", "no_secret")]


@pytest.mark.parametrize("case", AS_IS, ids=lambda c: c["id"])
def test_the_scrub_takes_out_a_secret_echoed_as_it_is(case, monkeypatch):
    for var in git.SECRET_VARS:
        monkeypatch.delenv(var, raising=False)
    if case["secrets"]:
        monkeypatch.setenv("GITHUB_TOKEN", case["secrets"][0])
    assert git.scrub(case["in"]) == case["out"]
