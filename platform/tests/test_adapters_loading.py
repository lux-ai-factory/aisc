"""Adapter plugins: the folder the platform reads them from, and what makes one load or be skipped."""
from __future__ import annotations

import logging
import shutil
import textwrap
import threading
import time

import pytest

from platform_service import adapters

VALID = '''
PROTOCOL = {
    "name": "example-chat",
    "label": "Example chat site",
    "base_url": "https://chat.example.org",
    "fields": [{"name": "token", "label": "Token", "secret": True, "required": True},
               {"name": "assistant", "label": "Assistant"}],
    "capabilities": ["text", "history"],
    "max_concurrent": 1,
}

def call(connection, input, history, params, open):
    return "hello"
'''


def write_adapter(root, folder, source, extra_files=None):
    path = root / folder
    path.mkdir(parents=True)
    (path / "adapter.py").write_text(textwrap.dedent(source))
    for name, text in (extra_files or {}).items():
        (path / name).write_text(text)
    return path


def with_protocol(**changes):
    """VALID's source with PROTOCOL entries replaced (None removes one)."""
    lines = {
        "name": '"example-chat"', "label": '"Example chat site"',
        "fields": '[{"name": "token", "label": "Token", "secret": True, "required": True}]',
        "capabilities": '["text", "history"]',
    }
    lines.update(changes)
    body = ",\n    ".join(f'"{k}": {v}' for k, v in lines.items() if v is not None)
    return f"PROTOCOL = {{\n    {body},\n}}\n\ndef call(connection, input, history, params, open):\n    return 'x'\n"


def test_a_valid_adapter_loads_with_its_fields_and_capabilities(tmp_path):
    write_adapter(tmp_path, "example", VALID)
    adapter = adapters.load(tmp_path)["example-chat"]
    assert adapter.label == "Example chat site"
    assert adapter.base_url == "https://chat.example.org"
    assert [f.name for f in adapter.fields] == ["token", "assistant"]
    assert adapter.fields[0].secret is True and adapter.fields[0].required is True
    assert adapter.fields[1].secret is False and adapter.fields[1].required is False
    assert adapter.capabilities == ("text", "history")
    assert adapter.max_concurrent == 1
    assert adapter.call({}, "hi", [], {}, None) == "hello"
    assert adapter.public() == {
        "name": "example-chat", "label": "Example chat site", "base_url": "https://chat.example.org",
        "fields": [{"name": "token", "label": "Token", "secret": True, "required": True, "help": ""},
                   {"name": "assistant", "label": "Assistant", "secret": False, "required": False, "help": ""}],
        "capabilities": ["text", "history"], "adapter": True}


def test_a_folder_without_adapter_py_and_a_missing_directory_load_nothing(tmp_path):
    (tmp_path / "empty").mkdir()
    (tmp_path / "README.md").write_text("not a folder")
    assert adapters.load(tmp_path) == {}
    assert adapters.load(tmp_path / "absent") == {}


@pytest.mark.parametrize("source", [
    "PROTOCOL = {",
    "def call(connection, input, history, params, open):\n    return 'x'\n",
    with_protocol().split("def call")[0],
    with_protocol().replace("def call(connection, input, history, params, open):\n    return 'x'", "call = 3"),
    with_protocol(name='"openai"'),
    with_protocol(name='"Bad Name"'),
    with_protocol(label=None),
    with_protocol(capabilities='["text", "tools"]'),
    with_protocol(capabilities='["history"]'),
    with_protocol(fields='[{"label": "No name"}]'),
    with_protocol(fields='[{"name": "a", "label": "A"}, {"name": "a", "label": "B"}]'),
    with_protocol(fields='[{"name": "a", "label": "A", "secret": "yes"}]'),
    with_protocol(max_concurrent="0"),
    "raise RuntimeError('broken on import')",
], ids=["syntax", "no-protocol", "no-call", "call-not-callable", "built-in-name", "bad-name", "no-label",
        "tools", "no-text", "field-without-name", "duplicate-field", "secret-not-bool", "max-concurrent-0",
        "import-error"])
def test_a_broken_adapter_is_skipped_and_logged(tmp_path, caplog, source):
    write_adapter(tmp_path, "broken-one", source)
    with caplog.at_level(logging.WARNING, logger="platform_service.adapters"):
        assert adapters.load(tmp_path) == {}
    assert any("broken-one" in r.getMessage() for r in caplog.records), caplog.text


def test_two_folders_with_one_name_keep_the_first_in_name_order(tmp_path, caplog):
    write_adapter(tmp_path, "a", VALID)
    write_adapter(tmp_path, "b", VALID.replace("Example chat site", "Second"))
    with caplog.at_level(logging.WARNING, logger="platform_service.adapters"):
        loaded = adapters.load(tmp_path)
    assert loaded["example-chat"].label == "Example chat site"
    assert any("b" in r.getMessage() and "example-chat" in r.getMessage() for r in caplog.records)


def test_an_adapter_imports_its_own_sibling_modules(tmp_path):
    source = VALID.replace('return "hello"', "return VALUE").replace("PROTOCOL = {", "from helper import VALUE\n\nPROTOCOL = {")
    write_adapter(tmp_path, "example", source, {"helper.py": "VALUE = 'from the helper'\n"})
    assert adapters.load(tmp_path)["example-chat"].call({}, "", [], {}, None) == "from the helper"


def test_two_adapters_each_get_their_own_helper_module(tmp_path):
    for folder, name, value in (("one", "ad-one", "first"), ("two", "ad-two", "second")):
        source = (VALID.replace('"example-chat"', f'"{name}"').replace('return "hello"', "return VALUE")
                  .replace("PROTOCOL = {", "from helper import VALUE\n\nPROTOCOL = {"))
        write_adapter(tmp_path, folder, source, {"helper.py": f"VALUE = {value!r}\n"})
    loaded = adapters.load(tmp_path)
    assert loaded["ad-one"].call({}, "", [], {}, None) == "first"
    assert loaded["ad-two"].call({}, "", [], {}, None) == "second"
    assert "helper" not in __import__("sys").modules


def test_a_module_named_like_one_the_platform_has_loaded_is_refused(tmp_path, caplog):
    write_adapter(tmp_path, "shadow", VALID, {"logging.py": "x = 1\n"})
    with caplog.at_level(logging.WARNING, logger="platform_service.adapters"):
        assert adapters.load(tmp_path) == {}
    assert any("shadow" in r.getMessage() and "logging" in r.getMessage() for r in caplog.records)


def test_the_registry_loads_once_when_first_used_at_the_same_time(monkeypatch):
    loads = []

    def slow_load(directory):
        loads.append(directory)
        time.sleep(0.2)
        return {}

    monkeypatch.setattr(adapters, "load", slow_load)
    adapters.reset()
    try:
        threads = [threading.Thread(target=adapters.registry) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        assert len(loads) == 1
    finally:
        adapters.reset()


def test_registry_reads_the_configured_folder_once(tmp_path, monkeypatch):
    folder = write_adapter(tmp_path, "example", VALID)
    monkeypatch.setenv("PLATFORM_ADAPTERS_DIR", str(tmp_path))
    adapters.reset()
    try:
        assert adapters.get("example-chat") is not None
        shutil.rmtree(folder)
        assert adapters.get("example-chat") is not None
        adapters.reset()
        assert adapters.get("example-chat") is None
        assert adapters.get("openai") is None
    finally:
        adapters.reset()
