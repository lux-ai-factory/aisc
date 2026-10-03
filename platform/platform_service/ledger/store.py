"""The ledger store: one log per project database, append-only, every read verified.

The contract, kept by both stores and tested on both:
- `append(db, entry) -> seq`: increasing per database; the same event id with the same content is a
  no-op returning the first seq, with other content `DuplicateEvent`; over `MAX_ENTRY_BYTES`
  `EntryTooLarge`; a database the pool never made `UnknownDatabase`.
- `get(db, seq)`, `scan(db, after_seq, limit)`: verified; anything that doesn't verify, a rolled-back
  server included, is `TamperAlarm`, never "unavailable".
- `head(db)`, `state(db)`, `set_state(db, state)` (the last two are test hooks), `databases()`,
  `server_id`.

`ImmudbLedger` uses immudb's key-value API only: `e:<seq>` holds the canonical entry, `id:<event
id>` its seq and digest, `seq:last` the head, all three written in one transaction. It keeps one
client per database, each behind its own lock, and never switches a shared client between databases:
a shared client was seen to put entries in the wrong database without an error. The
verified state lives in a `StateStore` outside immudb, moved forward by compare-and-set.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from platform_service.ledger import settings
from platform_service.ledger.canonical import canonical
from platform_service.ledger.naming import is_ledger_name
from platform_service.ledger.state import State

#: Every field an entry may have; a missing one reads as None.
ENTRY_FIELDS = ("seq", "event_id", "occurred_at", "recorded_at", "project_pid", "card_version", "step",
                "source_app", "action", "actor_kind", "actor_ref", "on_behalf_of_ref", "program", "model",
                "request_id", "run_id", "next_action", "verified", "reported_by", "item_type", "item_id",
                "item_version", "before_sha256", "after_sha256", "content_sha256", "evidence_ref",
                "depends_on", "outcome", "details", "registry_version")


class LedgerError(Exception):
    pass


class TamperAlarm(LedgerError):
    """What was read doesn't verify: an edit, a rewrite or a rollback."""


class DuplicateEvent(LedgerError):
    """The same event id with other content."""


class EntryTooLarge(LedgerError):
    pass


class UnknownDatabase(LedgerError):
    """Not a database of this store's pool (or not a ledger name at all)."""


class LedgerCredentials(LedgerError):
    """immudb refused the platform's user name or password: a configuration error, not a database."""


class HeadChanged(LedgerError):
    """A re-anchor's expected head is not the store's any more: look again."""


class LedgerUnavailable(LedgerError):
    """The store can't be reached now: the caller keeps the event pending."""


class Entry:
    """One verified ledger entry."""

    def __init__(self, data: dict):
        self._data = dict(data)
        for field in ENTRY_FIELDS:
            setattr(self, field, data.get(field))
        if self.details is None:
            self.details = {}

    def as_dict(self) -> dict:
        return dict(self._data)

    def __repr__(self) -> str:
        return f"Entry(seq={self.seq}, action={self.action!r}, item_id={self.item_id!r})"


@dataclass(frozen=True)
class Head:
    seq: int
    state_hash: str


def _digest(entry: dict) -> str:
    """What makes two appends of one event id the same: its content, without what the store adds."""
    return hashlib.sha256(canonical({k: v for k, v in entry.items() if k not in ("seq", "recorded_at")})).hexdigest()


def _prepare(entry: dict) -> tuple[dict, str]:
    if not entry.get("event_id"):
        raise ValueError("an entry needs an event_id")
    digest = _digest(entry)
    body = dict(entry)
    body["recorded_at"] = datetime.now(timezone.utc).isoformat()
    if len(canonical(body)) + 32 > settings.MAX_ENTRY_BYTES:
        raise EntryTooLarge(f"entry {entry['event_id']} is over {settings.MAX_ENTRY_BYTES} bytes")
    return body, digest


# In memory (tests)

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


# immudb

class _StateAdapter:
    """immudb-py's RootService, backed by the platform's state store (compare-and-set)."""

    def __init__(self, db: str, store):
        self._db, self._store, self._service = db, store, None

    def init(self, dbname, service):
        self._service = service

    def get(self):
        from immudb.rootService import State as ImmuState

        saved = self._store.get(self._db)
        if saved is not None:
            return ImmuState(db=self._db, txId=saved.tx_id, txHash=saved.tx_hash, publicKey=b"",
                             signature=saved.signature or b"")
        from google.protobuf import empty_pb2

        return self._service.CurrentState(empty_pb2.Empty())       # first sight: nothing to compare yet

    def set(self, root):
        """Move the verified state forward, never back. An older proof than the stored state is not
        tampering: another worker sharing the state moved it on meanwhile. A rollback is
        caught by immudb's own proof against the stored state, before this is called."""
        new = State(self._db, int(root.txId), bytes(root.txHash), bytes(getattr(root, "signature", b"") or b"") or None)
        for _ in range(5):
            current = self._store.get(self._db)
            if current is not None and new.tx_id <= current.tx_id:
                return
            try:
                self._store.put(self._db, new, expected=current)
                return
            except ValueError:
                continue                                             # lost the race: look again


class ImmudbLedger:
    """The contract on immudb 1.11, as the `aisc_ledger` user (never the superuser)."""

    #: How long an unreachable server is remembered before it is tried again.
    DOWN_FOR = 30.0

    def __init__(self, url: str, *, user: str, password: str, state_store, public_key_file: str | None = None,
                 timeout: float = 10):
        self._url, self._user, self._password, self._states = url, user, password, state_store
        self._public_key_file = public_key_file                      # immudb's --signingKey, public half
        self._timeout = timeout                                      # every gRPC call: a black hole never hangs
        self._down_until = 0.0
        self._clients: dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._server_id = None

    @property
    def server_id(self) -> str:
        """immudb's own server UUID, sent in every response's metadata."""
        if self._server_id is None:
            import time

            from google.protobuf import empty_pb2
            from immudb import ImmudbClient

            if time.monotonic() < self._down_until:
                raise LedgerUnavailable(f"immudb at {self._url} was unreachable moments ago")
            # Health needs no login, and aisc_ledger has no right on immudb's defaultdb anyway. A short
            # deadline: an unreachable server must never hold up project creation.
            try:
                _, call = ImmudbClient(self._url)._stub.Health.with_call(empty_pb2.Empty(),
                                                                         timeout=min(self._timeout, 5))
            except Exception as exc:
                self._down_until = time.monotonic() + self.DOWN_FOR
                raise LedgerUnavailable(f"immudb at {self._url} did not answer: {type(exc).__name__}") from exc
            self._server_id = "immudb:" + dict(call.initial_metadata())["immudb-uuid"]
        return self._server_id

    def databases(self) -> set[str]:
        """The ledger databases this user may use. It logs in to the platform log, which the pool
        command always makes: aisc_ledger has no right on immudb's defaultdb."""
        from immudb import ImmudbClient

        from platform_service.ledger.naming import PLATFORM_DB

        client = ImmudbClient(self._url, timeout=self._timeout)
        try:
            client.login(self._user, self._password, database=PLATFORM_DB.encode())
            listed = client.databaseListV2().databases
        except Exception as exc:
            raise _classify(exc, PLATFORM_DB, login=True) from exc
        return {d.name for d in listed if is_ledger_name(d.name)}

    def _client(self, db: str):
        """One client and one lock per database; a new database gets its own login."""
        if not is_ledger_name(db):
            raise UnknownDatabase(db)
        with self._lock:
            if db not in self._clients:
                from immudb import ImmudbClient

                client = ImmudbClient(self._url, rs=_StateAdapter(db, self._states),
                                      publicKeyFile=self._public_key_file, timeout=self._timeout)
                try:
                    client.login(self._user, self._password, database=db.encode())
                except Exception as exc:
                    raise _classify(exc, db, login=True) from exc
                self._clients[db] = (client, threading.Lock())
            return self._clients[db]

    def _forget_client(self, db: str, client) -> None:
        with self._lock:
            if self._clients.get(db, (None,))[0] is client:
                del self._clients[db]

    def _call(self, db: str, fn):
        """Run `fn` with the database's client. A lost session (an immudb restart) is logged in again
        once and retried, so the same store recovers on its own. An unreachable server drops the
        client too: its gRPC channel would stay in reconnect backoff, up to about 2 minutes, after
        the server is back; the next call dials afresh."""
        for attempt in (1, 2):
            client, lock = self._client(db)
            with lock:
                try:
                    return fn(client)
                except (LedgerError, KeyError):
                    raise
                except Exception as exc:
                    if attempt == 1 and _session_lost(exc):
                        self._forget_client(db, client)
                        continue
                    classified = _classify(exc, db)
                    if isinstance(classified, LedgerUnavailable):
                        self._forget_client(db, client)
                    raise classified from exc

    @staticmethod
    def _verified(client, key: bytes):
        try:
            return client.verifiedGet(key).value
        except Exception as exc:
            if "key not found" in str(exc):
                raise KeyError(key) from None
            raise

    def _last(self, client) -> int:
        try:
            return int(self._verified(client, b"seq:last"))
        except KeyError:
            return 0

    def append(self, db: str, entry: dict) -> int:
        body, digest = _prepare(entry)

        def run(client):
            try:
                known = json.loads(self._verified(client, f"id:{entry['event_id']}".encode()))
                if known["digest"] != digest:
                    raise DuplicateEvent(entry["event_id"])
                return known["seq"]
            except KeyError:
                pass
            # Two writers may race for a number: the entry's key and the event's key must not exist yet,
            # or immudb refuses the whole transaction and the loser looks again.
            for _ in range(50):
                seq = self._last(client) + 1
                body["seq"] = seq
                try:
                    _set_new(client, {f"e:{seq:020d}".encode(): canonical(body),
                                      f"id:{entry['event_id']}".encode():
                                          json.dumps({"seq": seq, "digest": digest}).encode(),
                                      b"seq:last": str(seq).encode()},
                             must_not_exist=(f"e:{seq:020d}".encode(), f"id:{entry['event_id']}".encode()))
                except _Taken:
                    try:                                             # the same event, written meanwhile?
                        known = json.loads(self._verified(client, f"id:{entry['event_id']}".encode()))
                        if known["digest"] != digest:
                            raise DuplicateEvent(entry["event_id"])
                        return known["seq"]
                    except KeyError:
                        continue                                     # the number was taken: next one
                self._verified(client, f"e:{seq:020d}".encode())      # proves the write, moves the state
                return seq
            raise LedgerUnavailable(f"{db}: no free sequence number after 50 tries (heavy contention): retry")
        return self._call(db, run)

    def get(self, db: str, seq: int) -> Entry:
        return self._call(db, lambda client: Entry(json.loads(self._verified(client, f"e:{seq:020d}".encode()))))

    def seq_of(self, db: str, event_id: str) -> int | None:
        def run(client):
            try:
                return json.loads(self._verified(client, f"id:{event_id}".encode()))["seq"]
            except KeyError:
                return None
        return self._call(db, run)

    def scan(self, db: str, after_seq: int = 0, limit: int = 100) -> list[Entry]:
        def run(client):
            last = min(self._last(client), after_seq + limit)
            return [Entry(json.loads(self._verified(client, f"e:{seq:020d}".encode())))
                    for seq in range(after_seq + 1, last + 1)]
        return self._call(db, run)

    def head(self, db: str) -> Head:
        def run(client):
            seq = self._last(client)
            saved = self._states.get(db)
            return Head(seq, saved.tx_hash.hex() if saved else "")
        return self._call(db, run)

    def state(self, db: str) -> State:
        self._client(db)
        return self._states.get(db)

    def set_state(self, db: str, state: State) -> None:
        self._states.put(db, state, expected=self._states.get(db))

    def export(self, db: str) -> list[dict]:
        """Every transaction of the database, 1..N, with its entries, then each ledger entry, then the
        head: the state immudb signed at N (format `immudb`). Checked here before it
        leaves: the chain must hold, end at the signed state, and pass through the state this platform
        verified (a server rolled back behind it is a TamperAlarm, never a file)."""
        import base64

        from google.protobuf import empty_pb2
        from immudb import schema as immu_schema
        from immudb.grpc import schema_pb2

        from platform_service.ledger import immudb_proof

        def run(client):
            state = client._stub.CurrentState(empty_pb2.Empty(), timeout=self._timeout)
            # two scans: the entries' digests (what the header hashes) and, separately, their values
            resolve = schema_pb2.EntriesSpec(kvEntriesSpec=schema_pb2.EntryTypeSpec(action=schema_pb2.RESOLVE))
            txs, values, at = [], {}, 1
            while at <= state.txId:
                limit = min(1000, state.txId - at + 1)
                page = client._stub.TxScan(schema_pb2.TxScanRequest(initialTx=at, limit=limit),
                                           timeout=self._timeout).txs
                if not page:
                    break
                for tx in client._stub.TxScan(schema_pb2.TxScanRequest(initialTx=at, limit=limit, entriesSpec=resolve),
                                              timeout=self._timeout).txs:
                    for kv in tx.kvEntries:
                        values[(tx.header.id, kv.key)] = kv.value
                for tx in page:
                    if tx.header.id > state.txId:
                        break
                    h = tx.header
                    txs.append({"id": h.id, "ts": h.ts, "version": h.version, "nentries": h.nentries,
                                "prevAlh": h.prevAlh.hex(), "eH": h.eH.hex(), "blTxId": h.blTxId,
                                "blRoot": h.blRoot.hex(),
                                "md": (immu_schema.TxMetadataFromProto(h.metadata).Bytes() or b"").hex()
                                      if h.HasField("metadata") else "",
                                "entries": [{"key": e.key.hex(), "hValue": e.hValue.hex(),
                                             "md": (immu_schema.KVMetadataFromProto(e.metadata).Bytes() or b"").hex()
                                                   if e.HasField("metadata") else ""} for e in tx.entries]})
                at = page[-1].header.id + 1
            return state, txs, values

        state, txs, values = self._call(db, run)
        try:
            alhs = immudb_proof.check_txs(txs)
        except ValueError as exc:
            raise TamperAlarm(f"{db}: the server's transactions don't hold together: {exc}") from None
        if not alhs or len(alhs) != state.txId or alhs[-1] != bytes(state.txHash):
            raise TamperAlarm(f"{db}: the server's state is not the end of its transactions")
        saved = self._states.get(db)
        if saved is not None and (saved.tx_id > state.txId or alhs[saved.tx_id - 1] != saved.tx_hash):
            raise TamperAlarm(f"{db}: the server is behind or beside the state this platform verified")
        if self._public_key_file:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec

            with open(self._public_key_file, "rb") as f:
                key = serialization.load_pem_public_key(f.read())
            try:
                key.verify(state.signature.signature,
                           immudb_proof.state_message(state.db, state.txId, bytes(state.txHash)),
                           ec.ECDSA(hashes.SHA256()))
            except Exception:
                raise TamperAlarm(f"{db}: the server's state is not signed by its key") from None
        lines = [{"tx": tx} for tx in txs]
        seqs = []
        for tx in txs:
            for e in tx["entries"]:
                key = bytes.fromhex(e["key"])
                if not key.startswith(b"\x00e:"):
                    continue
                value = values.get((tx["id"], key[1:]))
                if value is None or immudb_proof.value_hash(value).hex() != e["hValue"]:
                    raise TamperAlarm(f"{db}: entry {key[1:].decode()} doesn't match its transaction")
                entry = json.loads(value)
                seqs.append(entry["seq"])
                lines.append({"entry": entry, "tx": tx["id"]})
        if seqs != list(range(1, len(seqs) + 1)):
            raise TamperAlarm(f"{db}: the entries are not numbered 1..{len(seqs)}")
        head = {"format": "immudb", "log": db, "seq": len(seqs), "at": txs[-1]["ts"],
                "state": {"db": state.db, "txId": state.txId, "txHash": bytes(state.txHash).hex(),
                          "signature": base64.b64encode(state.signature.signature).decode()}}
        return lines + [{"head": head}]

    def server_head(self, db: str) -> dict:
        """immudb's current state, not yet trusted: {tx, hash}, its signature checked when a key is set."""
        from google.protobuf import empty_pb2

        state = self._call(db, lambda client: client._stub.CurrentState(empty_pb2.Empty(), timeout=self._timeout))
        if self._public_key_file:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec

            from platform_service.ledger import immudb_proof

            with open(self._public_key_file, "rb") as f:
                key = serialization.load_pem_public_key(f.read())
            try:
                key.verify(state.signature.signature,
                           immudb_proof.state_message(state.db, state.txId, bytes(state.txHash)),
                           ec.ECDSA(hashes.SHA256()))
            except Exception:
                raise TamperAlarm(f"{db}: the server's state is not signed by its key") from None
        return {"tx": int(state.txId), "hash": bytes(state.txHash).hex()}

    def trusted_head(self, db: str) -> dict:
        saved = self._states.get(db)
        return {"tx": saved.tx_id, "hash": saved.tx_hash.hex()} if saved else {"tx": 0, "hash": None}

    def reanchor(self, db: str, expected: dict) -> tuple[dict, dict]:
        """After a restore: trust the server's current state, if it is the one the admin checked.
        The new state is saved, so reads verify against it from now on (not trust on first use).
        Returns (old, new) heads; HeadChanged if the server moved since."""
        new = self.server_head(db)
        if new != expected:
            raise HeadChanged(f"{db}: the server holds {new}, not {expected}")
        old = self.trusted_head(db)
        current = self._states.get(db)
        self._states.put(db, State(db, new["tx"], bytes.fromhex(new["hash"]), None), expected=current)
        with self._lock:
            self._clients.pop(db, None)
        return old, new


class _Taken(Exception):
    """A precondition failed: the key already exists."""


def _set_new(client, kvs: dict, must_not_exist: tuple) -> None:
    """immudb's Set with KeyMustNotExist preconditions (immudb-py 1.5's setAll has none)."""
    from immudb.grpc import schema_pb2

    request = schema_pb2.SetRequest(
        KVs=[schema_pb2.KeyValue(key=k, value=v) for k, v in kvs.items()],
        preconditions=[schema_pb2.Precondition(
            keyMustNotExist=schema_pb2.Precondition.KeyMustNotExistPrecondition(key=k)) for k in must_not_exist])
    try:
        client._stub.Set(request)
    except Exception as exc:
        details = (getattr(exc, "details", lambda: "")() or "").lower()
        code = getattr(getattr(exc, "code", lambda: None)(), "name", "")
        if code == "FAILED_PRECONDITION" or "precondition" in details:
            raise _Taken() from exc
        raise


def _session_lost(exc: Exception) -> bool:
    details = (getattr(exc, "details", lambda: "")() or str(exc)).lower()
    code = getattr(getattr(exc, "code", lambda: None)(), "name", "")
    return code == "UNAUTHENTICATED" or "not logged in" in details or "please login" in details


def _classify(exc: Exception, db: str, login: bool = False) -> Exception:
    """immudb's errors, sorted by what the caller must do."""
    text = f"{type(exc).__name__}: {exc}"
    details = getattr(exc, "details", lambda: "")() or ""
    code = getattr(getattr(exc, "code", lambda: None)(), "name", "")
    if "illegal state" in details or "CorruptedData" in text or \
            type(exc).__name__ in ("VerificationException", "BadSignatureError"):
        return TamperAlarm(f"{db}: {details or text}")
    if "invalid user name or password" in details.lower():
        return LedgerCredentials(f"{db}: immudb refused the ledger user's password (LEDGER_IMMUDB_PASSWORD)")
    if code in ("UNAVAILABLE", "DEADLINE_EXCEEDED"):
        return LedgerUnavailable(f"{db}: {details or text}")
    if "does not exist" in details or "permission" in details.lower() or code == "PERMISSION_DENIED" \
            or (login and code == "NOT_FOUND"):
        return UnknownDatabase(f"{db}: {details or text}")
    return LedgerError(f"{db}: {details or text}")


def from_environment():
    """The production store: immudb as `aisc_ledger`, state in the platform database."""
    from platform_service.ledger.state import PostgresStateStore

    url, password = os.environ.get("LEDGER_IMMUDB_URL"), os.environ.get("LEDGER_IMMUDB_PASSWORD")
    if not url or not password:
        raise LedgerUnavailable("LEDGER_IMMUDB_URL and LEDGER_IMMUDB_PASSWORD must both be set: the ledger waits")
    return ImmudbLedger(url, user=os.environ.get("LEDGER_IMMUDB_USER", "aisc_ledger"),
                        password=password, state_store=PostgresStateStore(),
                        public_key_file=os.environ.get("LEDGER_IMMUDB_PUBLIC_KEY") or None)
