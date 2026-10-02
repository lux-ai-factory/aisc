"""Every number the ledger's rules depend on, named once (spec 6.1). Tests use these names, never the
numbers, so a decision changes one line (review R6.8)."""
from __future__ import annotations

from datetime import timedelta

#: The longest an event may come after the request it cites (W3), on the databases' clocks.
WINDOW = timedelta(minutes=5)
#: How far before its request an event may seem to be, for clock differences.
CLOCK_SKEW = timedelta(seconds=2)
#: How long an AI or worker run may keep producing events after its start event.
RUN_WINDOW = timedelta(hours=24)
#: Leeway on a token's exp and nbf.
LEEWAY = timedelta(seconds=30)
#: How long an action from a newer registry is held before it is rejected (R2.12).
HOLD_UNKNOWN = timedelta(hours=24)
#: How long an old and a new gateway secret or ledger token are both accepted.
ROTATION_OVERLAP = timedelta(hours=24)
#: How long page views are kept (D10).
PAGE_VIEW_RETENTION = timedelta(days=90)
#: How long a clean reconciliation must last before `enforce` (spec 5.2).
RECONCILE_DAYS = 14
#: The largest canonical entry kept in immudb; more goes to the evidence store (L2).
MAX_ENTRY_BYTES = 64 * 1024
#: Beacons per person per minute.
BEACON_PER_MINUTE = 60
#: How long Postgres backups keep erased mapping rows (spec 7.5).
BACKUP_RETENTION = timedelta(days=30)
#: Who may export a project's ledger (D1): its owners; admins always may.
EXPORT_ROLES = frozenset({"owner"})
#: Whether a non-member's request is recorded at all (D11): yes, in the platform log only.
KEEP_STRANGER_REQUESTS = True
#: How many databases the operator's pool script makes at a time (spec 7.1).
LEDGER_POOL = 20
#: The relay's limit on open project connections (spec 7.2).
RELAY_CONNECTIONS = 4
