"""Every number the ledger's rules depend on, named once. Tests use these names, never the
numbers, so a decision changes one line."""
from __future__ import annotations

from datetime import timedelta

#: The longest an event may come after the request it cites, on the databases' clocks.
WINDOW = timedelta(minutes=5)
#: How far before its request an event may seem to be, for clock differences.
CLOCK_SKEW = timedelta(seconds=2)
#: How long an AI or worker run may keep producing events after its start event.
RUN_WINDOW = timedelta(hours=24)
#: Leeway on a token's exp and nbf.
LEEWAY = timedelta(seconds=30)
#: How long an action from a newer registry is held before it is rejected.
HOLD_UNKNOWN = timedelta(hours=24)
#: How long page views are kept.
PAGE_VIEW_RETENTION = timedelta(days=90)
#: The largest canonical entry kept in immudb; more goes to the evidence store.
MAX_ENTRY_BYTES = 64 * 1024
#: Beacons per person per minute.
BEACON_PER_MINUTE = 60
#: Who may export a project's ledger: its owners; admins always may.
EXPORT_ROLES = frozenset({"owner"})
#: How many databases the operator's pool script makes at a time.
LEDGER_POOL = 50
#: How often the relay worker passes over every log.
RELAY_EVERY = timedelta(seconds=5)
#: How many rows the relay reads from each source of a log per pass.
RELAY_BATCH = 500
#: How often page views past PAGE_VIEW_RETENTION are deleted.
EXPIRE_EVERY = timedelta(hours=24)
