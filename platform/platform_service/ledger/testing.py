"""Helpers for the ledger's own tests. Never used by the service."""
from __future__ import annotations

from platform_service.ledger import pool
from platform_service.ledger.naming import PLATFORM_DB, pool_name


def fill_pool(store, n: int) -> list[str]:
    """Make `n` databases (and the platform log) in a memory store and register them, as the operator's
    script does for immudb."""
    if not hasattr(store, "create"):
        raise TypeError("fill_pool makes databases in a MemoryLedger; use scripts/ledger-pool.sh for immudb")
    names = [pool_name() for _ in range(n)]
    for name in names + [PLATFORM_DB]:
        store.create(name)
    pool.register(store, names)
    return names


def seed(pid: str, events: list[dict]) -> list[int]:
    """Entries written the way the relay writes them (store, read index, actor mapping), for the read
    routes' tests: `actor_sub` becomes an `actor_ref`."""
    from platform_service import ledger
    from platform_service.ledger import actors, provision, relay

    log = provision.database_for(pid)
    seqs = []
    for event in events:
        entry = dict(event)
        sub = entry.pop("actor_sub", None)
        if sub:
            entry["actor_ref"] = actors.ref_for(pid, sub, entry.pop("actor_name", sub))
        entry.setdefault("project_pid", pid)
        entry.setdefault("verified", True)
        seq = ledger.current().append(log, entry)
        relay._index(log, seq, entry, pid)
        seqs.append(seq)
    return seqs


def rehash_export(lines: list[dict]) -> list[dict]:
    """An attacker's best effort on an edited export: recompute every proof and the head's chain. It
    can't sign the new head, so the offline checker still refuses the file."""
    from platform_service.ledger import export

    chain = export.GENESIS
    out = []
    for line in lines[:-1]:
        previous = chain
        chain = export.link(previous, line["entry"])
        out.append({**line, "proof": {"previous": previous, "chain": chain}})
    head = dict(lines[-1]["head"])
    head["chain"] = chain
    return out + [{"head": head}]
