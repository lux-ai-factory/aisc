"""A project's log as a file an auditor checks offline.

JSON lines, then `{"head": ...}`; the store decides the proof (`head.format`):
- `immudb`: every transaction of the log's database with its entries, then each entry with its
  transaction; the head is the state immudb signed (see immudb_proof.py);
- `chain` (the memory store): each entry with its hash link, `sha256(previous + canonical(entry))`
  from 32 zero bytes, and a head `{log, seq, chain}` signed by the store's key.
Every entry line may carry its frozen `content`, or `content_redacted` (the reason) when that content was
redacted; a `ledger.content.redacted` entry of the same log names each redacted event id. The head also carries `keys.content`: this project's
content key in every kept version, so `--check-content` can recompute each `content_sha256`.
Never another project's key, never a master key, never the `state` key.

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
        rows = conn.execute("SELECT event_id, content, redaction FROM ledger.content WHERE log = %s"
                            " AND (content IS NOT NULL OR redacted_at IS NOT NULL)", (log,)).fetchall()
    frozen = {r["event_id"]: r for r in rows}
    for line in out:
        row = frozen.get(line["entry"].get("event_id")) if "entry" in line else None
        if row is None:
            continue
        if row["content"] is not None:
            line["content"] = row["content"]
        else:                                                         # named by a ledger.content.redacted entry
            line["content_redacted"] = row["redaction"]
    out[-1]["head"]["keys"] = {"content": {v: k.hex() for v, k in secrets.derive_all(pid, "content").items()}}
    return out
