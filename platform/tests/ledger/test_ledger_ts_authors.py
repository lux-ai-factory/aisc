"""The TypeScript emitter and the relay agree on which fields name a person.

shared/ledger-ts emit.ts strips WHO_FIELDS from every event it writes; the registry refuses an event
whose details still hold one of its actor keys. A name the emitter strips that the registry does not
know would pass unnoticed if an emitter ever forgot to strip it.
"""
from __future__ import annotations

import re
from pathlib import Path

from platform_service.ledger import registry

EMIT_TS = Path(__file__).resolve().parents[3] / "shared/ledger-ts/emit.ts"


def test_every_field_the_typescript_emitter_strips_is_an_actor_key_of_the_registry():
    found = re.search(r"const WHO_FIELDS = new Set\(\[(.*?)\]\)", EMIT_TS.read_text(), re.S)
    assert found, f"WHO_FIELDS not found in {EMIT_TS}"
    who = set(re.findall(r'"([^"]+)"', found.group(1)))
    assert who and who <= registry._ACTOR_KEYS, who - registry._ACTOR_KEYS
