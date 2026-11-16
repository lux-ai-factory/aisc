"""Which values of a plugin configuration are secrets, in a ledger copy.

The rule lives in one module shared by every Python service, aisc_redact (shared/identity), held to the shared
vectors redaction-cases.json; this module keeps the platform's names for it. Used to mask the platform's copies of
old configuration events (secret_cleanup.py), to accept the engine's masked re-send of one as a replay
(routes/ledger.py) and by the relay's registry (SECRET_SHAPE). See aisc_redact for what the rule hides and what
it does not catch.
"""
from __future__ import annotations

from aisc_redact import (  # noqa: F401 (the platform's names for the shared rule)
    CREDENTIAL,
    REDACTED,
    SECRET_ASSIGNMENT,
    SECRET_SET,
    SECRET_SHAPE,
    STRONG_LAST,
    STRONG_PAIRS,
    WEAK_LAST,
    WEAK_MIN_LENGTH,
    holds_plaintext_secret,
    masked_for_ledger,
    name_words,
    plaintext_secret_paths,
    stored_secret_name,
)
