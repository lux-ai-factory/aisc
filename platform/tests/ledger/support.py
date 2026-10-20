"""The ledger suite's fakes and hooks, kept out of the shipped package.

`MemoryLedger` is the store contract in memory (test_ledger_store.py's `any_store` tests keep it honest
against immudb); `fill_pool`, `seed` and `rehash_export` were platform_service.ledger.testing;
`tamper_mapping` was actors.tamper. Not a test module."""
from __future__ import annotations

import hashlib
import json
import threading
import uuid

from platform_service.ledger import actors, pool
from platform_service.ledger.canonical import canonical
from platform_service.ledger.naming import PLATFORM_DB, is_ledger_name, pool_name
from platform_service.ledger.state import State
from platform_service.ledger.store import (
    DuplicateEvent,
    Entry,
    Head,
    HeadChanged,
    LedgerUnavailable,
    TamperAlarm,
    UnknownDatabase,
    _prepare,
)


class MemoryLedger:
    """The contract in memory, with a hash chain so tampering is detected as in immudb. Test hooks:
    `create`, `drop`, `tamper`, `down`, `crash_after_appends`, `public_key_pem`."""

    def __init__(self):
        self.server_id = f"memory:{uuid.uuid4()}"
        self.down = False
        self.crash_after_appends: int | None = None
        self._appends = 0
        self._dbs: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._key = None

    # pool side
    def create(self, db: str) -> None:
        if not is_ledger_name(db):
            raise ValueError(f"not a ledger name: {db!r}")
        with self._lock:
            self._dbs.setdefault(db, {"rows": [], "chain": [b"\0" * 32], "ids": {}, "verified": 0})

    def drop(self, db: str) -> None:
        with self._lock:
            self._dbs.pop(db, None)

    def databases(self) -> set[str]:
        with self._lock:
            return set(self._dbs)

    # the contract
    def _db(self, db: str) -> dict:
        if self.down:
            raise LedgerUnavailable("the ledger store is down (test)")
        if not is_ledger_name(db) or db not in self._dbs:
            raise UnknownDatabase(db)
        return self._dbs[db]

    def append(self, db: str, entry: dict) -> int:
        body, digest = _prepare(entry)                               # the size cap first, as in immudb
        with self._lock:
            d = self._db(db)
            if d["verified"] > len(d["rows"]):
                raise TamperAlarm("the server holds less than was verified: a rollback")
            known = d["ids"].get(entry["event_id"])
            if known is not None:
                if known[1] != digest:
                    raise DuplicateEvent(entry["event_id"])
                return known[0]
            seq = len(d["rows"]) + 1
            body["seq"] = seq
            raw = canonical(body)
            d["rows"].append(raw)
            d["chain"].append(hashlib.sha256(d["chain"][-1] + raw).digest())
            d["ids"][entry["event_id"]] = (seq, digest)
            d["verified"] = seq
            self._appends += 1
            if self.crash_after_appends is not None and self._appends >= self.crash_after_appends:
                self.crash_after_appends = None
                raise RuntimeError("the store died after this append (test)")
            return seq

    def _check(self, d: dict, seq: int) -> Entry:
        if d["verified"] > len(d["rows"]):
            raise TamperAlarm("the server holds less than was verified: a rollback")
        if not 1 <= seq <= len(d["rows"]):
            raise KeyError(seq)
        raw = d["rows"][seq - 1]
        if hashlib.sha256(d["chain"][seq - 1] + raw).digest() != d["chain"][seq]:
            raise TamperAlarm(f"entry {seq} changed")
        return Entry(json.loads(raw))

    def get(self, db: str, seq: int) -> Entry:
        with self._lock:
            return self._check(self._db(db), seq)

    def scan(self, db: str, after_seq: int = 0, limit: int = 100) -> list[Entry]:
        with self._lock:
            d = self._db(db)
            last = min(len(d["rows"]), after_seq + limit)
            return [self._check(d, seq) for seq in range(after_seq + 1, last + 1)]

    def head(self, db: str) -> Head:
        with self._lock:
            d = self._db(db)
            return Head(len(d["rows"]), d["chain"][-1].hex())

    def seq_of(self, db: str, event_id: str) -> int | None:
        """The seq the store gave this event id, or None (checked before judging an event again)."""
        with self._lock:
            known = self._db(db)["ids"].get(event_id)
            return known[0] if known else None

    def state(self, db: str) -> State:
        with self._lock:
            d = self._db(db)
            return State(db, d["verified"], d["chain"][d["verified"]] if d["verified"] < len(d["chain"]) else b"")

    def set_state(self, db: str, state: State) -> None:
        with self._lock:
            self._db(db)["verified"] = state.tx_id

    def tamper(self, db: str, seq: int, field: str, value) -> None:
        with self._lock:
            d = self._dbs[db]
            data = json.loads(d["rows"][seq - 1])
            data[field] = value
            d["rows"][seq - 1] = canonical(data)

    def export_head(self, db: str, seq: int, chain: str) -> dict:
        """The head an export ends with, signed by this store's key (P-256, over the canonical head)."""
        import base64

        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec

        with self._lock:
            d = self._db(db)
            if seq != len(d["rows"]) or d["chain"][seq].hex() != chain:
                raise TamperAlarm("the export's chain is not this store's whole chain: nothing is signed")
        head = {"log": db, "seq": seq, "chain": chain}
        signature = self._signing_key().sign(canonical(head), ec.ECDSA(hashes.SHA256()))
        return {**head, "signature": base64.b64encode(signature).decode()}

    def export(self, db: str) -> list[dict]:
        """Every entry with its hash link, then the signed head (format `chain`, the contract's own)."""
        from platform_service.ledger import export

        with self._lock:
            rows = list(self.scan(db, after_seq=0, limit=len(self._db(db)["rows"])))
            lines, chain = [], export.GENESIS
            for e in rows:
                previous, chain = chain, export.link(chain, e.as_dict())
                lines.append({"entry": e.as_dict(), "proof": {"previous": previous, "chain": chain}})
            return lines + [{"head": {"format": "chain", **self.export_head(db, len(rows), chain)}}]

    def server_head(self, db: str) -> dict:
        """What the store holds now, not yet trusted: {tx, hash} (the memory store counts entries)."""
        with self._lock:
            d = self._db(db)
            return {"tx": len(d["rows"]), "hash": d["chain"][len(d["rows"])].hex()}

    def trusted_head(self, db: str) -> dict:
        with self._lock:
            d = self._db(db)
            v = d["verified"]
            return {"tx": v, "hash": d["chain"][v].hex() if v < len(d["chain"]) else None}

    def reanchor(self, db: str, expected: dict) -> tuple[dict, dict]:
        """After a restore: trust what the store holds now, if it is what the admin checked.
        Returns (old, new) heads; HeadChanged if the store moved since."""
        with self._lock:
            new = self.server_head(db)
            if new != expected:
                raise HeadChanged(f"{db}: the store holds {new}, not {expected}")
            old = self.trusted_head(db)
            self._dbs[db]["verified"] = new["tx"]
            return old, new

    def public_key_pem(self) -> str:
        from cryptography.hazmat.primitives import serialization

        return self._signing_key().public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def _signing_key(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        if self._key is None:
            self._key = ec.generate_private_key(ec.SECP256R1())
        return self._key


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


def tamper_mapping(pid, actor_ref: str, *, sub: str | None = None, name: str | None = None) -> None:
    """Test hook: edit a mapping row the way someone with database rights could, without its MAC."""
    with actors._connect() as conn:
        if sub is not None:
            conn.execute("UPDATE identity.actor SET sub = %s WHERE actor_ref = %s", (sub, actor_ref))
        if name is not None:
            conn.execute("UPDATE identity.actor SET name = %s WHERE actor_ref = %s", (name, actor_ref))
