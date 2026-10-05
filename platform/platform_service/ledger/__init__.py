"""The ledger: who did what, in each project's own immudb log.

The platform is the only writer. This package keeps the store it writes to; `use` swaps it (tests),
`current` returns it. Standard library only, so the repo-level tests can import the registry without
the platform's dependencies.
"""
from __future__ import annotations

_store = None


def current():
    """The ledger store in use: set by `use`, or made from the environment on first use."""
    global _store
    if _store is None:
        from platform_service.ledger.store import from_environment

        _store = from_environment()
    return _store


def use(store):
    """Use `store` from now on; returns the one it replaces (None if none was made yet)."""
    global _store
    previous, _store = _store, store
    return previous
