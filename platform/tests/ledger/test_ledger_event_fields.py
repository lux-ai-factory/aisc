"""What an event may carry, checked where it enters: the internal route's own checks (_malformed), the
registry's (actor keys, secret shapes, the run window), and the field lists that have to name the same
fields so an event that passes the route also fits core.outbox and ledger.outbox."""
from __future__ import annotations

import ast
import inspect
import re
import uuid
from datetime import timedelta

import pytest

from platform_service.ledger import outbox, registry, settings
from platform_service.routes import ledger as ledger_routes

TEMPLATE_SQL = (registry.__file__.rsplit("/platform_service/", 1)[0]
                + "/project-template/0020_ledger_outbox.sql")


def _user_action() -> str:
    return next(name for name, a in sorted(registry.REGISTRY.items()) if a.actor_kinds == ("user",))


def _event(**over):
    e = {"event_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()), "action": _user_action(),
         "item_type": "x", "item_id": "x1", "details": {}}
    e.update(over)
    return e


# _malformed: a uuid column gets a uuid, whoever the actor is

@pytest.mark.parametrize("field", ["run_id", "card_version"])
def test_a_user_event_with_a_non_uuid_id_is_refused_at_the_route(field):
    assert ledger_routes._malformed(_event(**{field: "not-a-uuid"})) == f"{field}: a UUID is needed"


@pytest.mark.parametrize("field", ["run_id", "card_version"])
def test_a_user_event_with_a_uuid_or_none_passes(field):
    assert ledger_routes._malformed(_event(**{field: str(uuid.uuid4())})) is None
    assert ledger_routes._malformed(_event(**{field: None})) is None
    assert ledger_routes._malformed(_event()) is None


# the field lists

def _stored_in_sql() -> set[str]:
    text = open(TEMPLATE_SQL).read()
    array = re.search(r"stored\s+text\[\]\s*:=\s*ARRAY\[(.*?)\];", text, re.S).group(1)
    return set(re.findall(r"'([a-z_]+)'", array))


def _outbox_emit_columns() -> set[str]:
    source = inspect.getsource(outbox.emit)
    columns = re.search(r"INSERT INTO core\.outbox \((.*?)\)", source.replace('"\n        "', ""), re.S).group(1)
    return {c.strip() for c in columns.replace('"', "").split(",")}


def _identity_fields() -> set[str]:
    from aisc_identity import ledger_events

    tree = ast.parse(inspect.getsource(ledger_events.event))
    built = next(n for n in ast.walk(tree) if isinstance(n, ast.Dict))
    return {k.value for k in built.keys} | set(ledger_events._OPTIONAL)


#: core.outbox's own: which app sent it (emitter), which project's log it goes to (project_pid), and what
#: the relay keeps beside the event (extra). A project's ledger.outbox needs none of them.
PLATFORM_ONLY = {"emitter", "project_pid", "extra"}
#: what ledger.emit fills in when an app leaves them out (outcome 'ok', the registry version it knows)
DEFAULTED_BY_THE_DATABASE = {"outcome", "registry_version"}


def test_the_event_field_lists_agree():
    stored = _stored_in_sql()
    assert set(ledger_routes._INTERNAL_COLUMNS) == stored
    assert _outbox_emit_columns() - PLATFORM_ONLY == stored
    assert _identity_fields() | DEFAULTED_BY_THE_DATABASE == stored


# the registry

def test_camel_case_actor_keys_are_the_platforms_too():
    """What the TS libraries call a person (createdBy, updatedBy, savedBy) is the witness's to say."""
    for key in ("createdBy", "updatedBy", "savedBy"):
        problems = registry.check({**_event(), "details": {key: "mallory"}})
        assert "actor_supplied" in problems, key


@pytest.mark.parametrize("value", [
    "AKIAIOSFODNN7EXAMPLE",
    "hf_" + "a" * 24,
    "Authorization: Token abcdefghijklmnop1234",
    "https://user:hunter2hunter2@db.example.com/x",
])
def test_the_registry_refuses_every_shape_the_ledger_masks(value):
    """The relay refuses what config_secrets.SECRET_SHAPE recognises, not a narrower copy of it."""
    problems = registry.check({**_event(), "details": {"note": value}})
    assert "secret_in:note" in problems


def test_an_action_without_a_window_of_its_own_uses_the_run_window(monkeypatch):
    action = registry.Action(name="x.y", step=1)
    assert action.window() == settings.RUN_WINDOW
    monkeypatch.setattr(settings, "RUN_WINDOW", timedelta(hours=2))
    assert action.window() == timedelta(hours=2)
    assert registry.Action(name="x.z", step=1, run_window=timedelta(minutes=5)).window() == timedelta(minutes=5)
