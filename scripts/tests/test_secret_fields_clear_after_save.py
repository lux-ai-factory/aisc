"""A key typed into Manage, Helper models or Manage, Connections stays in its field until the save succeeds:
a refused save (a 422 asking for the key again, a bad field) must not throw away what the person typed.
Linking a connection to a target is its own call, so the page never rebuilds a connection from its list."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPERS = ROOT / "homepage/helpers.html"
CONNECTIONS = ROOT / "homepage/connections.html"


def _function(script: str, head: str) -> str:
    """The text of the function whose first line matches `head`, up to its closing line at the same indent."""
    start = re.search(r"^( *)\S*" + head, script, re.M)
    assert start, head
    indent = start.group(1)
    end = re.compile(r"^" + indent + r"\}", re.M).search(script, start.end())
    return script[start.start():end.end()]


def test_the_helper_form_clears_the_key_only_after_a_save():
    html = HELPERS.read_text()
    handler = _function(html, r"getElementById\('helper-form'\)\.addEventListener\('submit'")
    before_call = handler.split("api(helpersPath(", 1)[0]
    assert "f-key').value = ''" not in before_call, "the key is cleared before the platform answered"
    after = handler.split("if (!res.ok)", 1)[1]
    assert "clearForm()" in after


def test_the_connection_editor_clears_secrets_only_after_a_save():
    html = CONNECTIONS.read_text()
    submit = _function(html, r"function submit\(ev\) \{")
    for part in submit.split("write('PUT'")[:-1]:
        assert not re.search(r"\.value\s*=\s*''", part), "a typed secret is cleared before the platform answered"
    assert submit.count("if (ok) closeEditor()") == 2
    close = _function(html, r"function closeEditor\(\) \{")
    for field in ("f-secret", "f-secret-header-add-value"):
        assert f"$('{field}').value = ''" in close, field
    assert ".adapter-field" in close, "the adapter's secret fields are not cleared after a save"


def test_linking_a_target_is_its_own_call():
    html = CONNECTIONS.read_text()
    link = _function(html, r"function linkTo\(c, key, msg\) \{")
    assert "write('POST', base() + '/' + enc(c.name) + '/target', {key: key}, msg)" in link
    assert "savedFields" not in html and "var SAVED" not in html
