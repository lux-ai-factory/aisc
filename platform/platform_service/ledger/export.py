"""A project's log as a file an auditor checks offline (spec 6.3, 7.4; I4, R4.9, PR8).

JSON lines, then `{"head": ...}`; the store decides the proof (`head.format`):
- `immudb`: every transaction of the log's database with its entries, then each entry with its
  transaction; the head is the state immudb signed (immudb_proof.py, open item S9);
- `chain` (the memory store): each entry with its hash link, `sha256(previous + canonical(entry))`
  from 32 zero bytes, and a head `{log, seq, chain}` signed by the store's key.
Every entry line may carry its frozen `content`. The head also carries `keys.content`: this project's
  content key in every kept version, so `--check-content` can recompute each `content_sha256`.
  Never another project's key, never a master key, never the `state` key (spec 6.1).

The checker is scripts/verify-ledger-export.py: it trusts only the public key it is given.
"""
from __future__ import annotations

import hashlib

from platform_service.ledger import secrets
from platform_service.ledger.canonical import canonical

GENESIS = "00" * 32


def link(previous: str, entry: dict) -> str:
    return hashlib.sha256(bytes.fromhex(previous) + canonical(entry)).hexdigest()


def lines(pid: str) -> list[dict]:
    """Every entry of the project's log, verified on the way out, then the signed head."""
    from platform_service import db, ledger
    from platform_service.ledger import provision

    log = provision.database_for(pid)
    out = ledger.current().export(log)
    with db.pool().connection() as conn:
        frozen = {r["event_id"]: r["content"] for r in conn.execute(
            "SELECT event_id, content FROM ledger.content WHERE log = %s AND content IS NOT NULL", (log,))}
    for line in out:
        if "entry" in line and line["entry"].get("event_id") in frozen:
            line["content"] = frozen[line["entry"]["event_id"]]
    out[-1]["head"]["keys"] = {"content": {v: k.hex() for v, k in secrets.derive_all(pid, "content").items()}}
    return out
