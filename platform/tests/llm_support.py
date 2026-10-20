"""Test helpers for the per-project LLM keys.

Not a test module. The Fernet keys the suite encrypts with and the tokens; the fake
provider is tests.http_stub.FakeServer, so no test reaches a real provider or uses a real key.

Test API keys look like `sk-test-<hex>`, so a leak anywhere is greppable.
"""
from __future__ import annotations

import uuid

from cryptography.fernet import Fernet

#: One Fernet key for the whole session, so every stored key the suite writes can be
#: read by every later test (the rotation test re-encrypts every project's keys).
SECRETS_KEY = Fernet.generate_key().decode()
INTERNAL_TOKEN = "pytest-internal-" + uuid.uuid4().hex  # the card agent's
#: the risk mapper's: each agentic system has a token of its own and resolves only itself
RISK_TOKEN = "pytest-risk-" + uuid.uuid4().hex


def new_key() -> str:
    return "sk-test-" + uuid.uuid4().hex


def field_of(entry, name):
    """A catalogue entry's field, whether the entry is a mapping or an object."""
    if isinstance(entry, dict):
        return entry[name]
    return getattr(entry, name)
