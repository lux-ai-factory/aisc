"""A project's log as a file an auditor checks offline (spec 6.3, 7.4; I4, R4.9, PR8).

JSON lines: one `{"entry", "proof", "content"?}` per entry, oldest first, then `{"head": ...}`.
- `proof` is the hash link: `chain = sha256(previous + canonical(entry))`, from 32 zero bytes;
- `head` is `{log, seq, chain}` signed by the store's signing key, plus `keys.content`: this project's
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
    store = ledger.current()
    out, chain, after = [], GENESIS, 0
    while True:
        page = store.scan(log, after_seq=after, limit=500)
        if not page:
            break
        for e in page:
            entry = e.as_dict()
            previous, chain = chain, link(chain, entry)
            out.append({"entry": entry, "proof": {"previous": previous, "chain": chain}})
        after = page[-1].seq
    with db.pool().connection() as conn:
        frozen = {r["event_id"]: r["content"] for r in conn.execute(
            "SELECT event_id, content FROM ledger.content WHERE log = %s AND content IS NOT NULL", (log,))}
    for line in out:
        if line["entry"].get("event_id") in frozen:
            line["content"] = frozen[line["entry"]["event_id"]]
    head = store.export_head(log, after, chain)
    head["keys"] = {"content": {v: k.hex() for v, k in secrets.derive_all(pid, "content").items()}}
    return out + [{"head": head}]
