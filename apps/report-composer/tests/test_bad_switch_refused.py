"""The report composer refuses to build its app when AUTH_ENABLED or LEDGER_MODE holds a value that is not a
switch word: a misspelt value used to turn sign-in or the ledger off without a word.

No database: create_app connects to nothing, and the refusal comes first.
"""

import importlib

import pytest

from report_composer.app import create_app


def _switch_invalid():
    try:
        return importlib.import_module("aisc_identity.switches").SwitchInvalid
    except ModuleNotFoundError:
        pytest.fail("aisc_identity.switches is missing: there is no strict switch parser")


@pytest.mark.parametrize("name,value", [("AUTH_ENABLED", "enabled"), ("LEDGER_MODE", ""),
                                        ("LEDGER_MODE", "recrod")])
def test_a_bad_switch_refuses_to_build_the_app(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    invalid = _switch_invalid()
    with pytest.raises(invalid, match=name):
        create_app(database_url="postgresql://x/y", project_database_url="postgresql://x/{database}")
