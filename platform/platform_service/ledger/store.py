"""The ledger store (spec 6.1, 6.2; spike M1-M16): one log per project database, append-only, every
read verified.

The contract, kept by both stores and tested on both:
- `append(db, entry) -> seq`: increasing per database; the same event id with the same content is a
  no-op returning the first seq, with other content `DuplicateEvent` (I3); over `MAX_ENTRY_BYTES`
  `EntryTooLarge`; a database the pool never made `UnknownDatabase`.
- `get(db, seq)`, `scan(db, after_seq, limit)`: verified; anything that doesn't verify, a rolled-back
  server included, is `TamperAlarm`, never "unavailable" (M13, M14).
- `head(db)`, `state(db)`, `set_state(db, state)` (the last two are test hooks), `databases()`,
  `server_id`.

`ImmudbLedger` uses immudb's key-value API only (M8): `e:<seq>` holds the canonical entry, `id:<event
id>` its seq and digest, `seq:last` the head, all three written in one transaction. It keeps one
client per database, each behind its own lock, and never switches a shared client between databases:
the spike's shared client put 18% of entries in the wrong database without an error (M9). The
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

#: Every field an entry may have (spec 6.2); a missing one reads as None.
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
    """The same event id with other content (I3)."""


class EntryTooLarge(LedgerError):
    pass


class UnknownDatabase(LedgerError):
    """Not a database of this store's pool (or not a ledger name at all)."""


class LedgerCredentials(LedgerError):
    """immudb refused the platform's user name or password: a configuration error, not a database."""


class LedgerUnavailable(LedgerError):
    """The store can't be reached now: the caller keeps the event pending (I6)."""


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


# ---------------------------------------------------------------------------------------------------
# In memory (tests)
# ---------------------------------------------------------------------------------------------------

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
            if not 0 <= seq < len(d["chain"]) or d["chain"][seq].hex() != chain:
                raise TamperAlarm("the export's chain is not this store's: nothing is signed")
        head = {"log": db, "seq": seq, "chain": chain}
        signature = self._signing_key().sign(canonical(head), ec.ECDSA(hashes.SHA256()))
        return {**head, "signature": base64.b64encode(signature).decode()}

    def reanchor(self, db: str) -> tuple:
        """After a restore: trust what the store holds now (spec T21). Returns (old, new) verified seq."""
        with self._lock:
            d = self._dbs[db]
            old = d["verified"]
            d["verified"] = len(d["rows"])
            return old, d["verified"]

    def public_key_pem(self) -> str:
        from cryptography.hazmat.primitives import serialization

        return self._signing_key().public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def _signing_key(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        if self._key is None:
            self._key = ec.generate_private_key(ec.SECP256R1())
        return self._key


# ---------------------------------------------------------------------------------------------------
# immudb
# ---------------------------------------------------------------------------------------------------

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
        tampering: another worker sharing the state moved it on meanwhile (review M1). A rollback is
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
    """The contract on immudb 1.11, as the `aisc_ledger` user (never the superuser, M1)."""

    #: How long an unreachable server is remembered before it is tried again (re-review minor 3).
    DOWN_FOR = 30.0

    def __init__(self, url: str, *, user: str, password: str, state_store, public_key_file: str | None = None,
                 timeout: float = 10):
        self._url, self._user, self._password, self._states = url, user, password, state_store
        self._public_key_file = public_key_file                      # immudb's --signingKey, public half (S3)
        self._timeout = timeout                                      # every gRPC call: a black hole never hangs
        self._down_until = 0.0
        self._clients: dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._server_id = None

    @property
    def server_id(self) -> str:
        """immudb's own server UUID, sent in every response's metadata (open item S7, settled)."""
        if self._server_id is None:
            import time

            from google.protobuf import empty_pb2
            from immudb import ImmudbClient

            if time.monotonic() < self._down_until:
                raise LedgerUnavailable(f"immudb at {self._url} was unreachable moments ago")
            # Health needs no login, and aisc_ledger has no right on immudb's defaultdb anyway. A short
            # deadline: an unreachable server must never hold up project creation (review M4).
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
        """One client and one lock per database; a new database gets its own login (M7)."""
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

    def _call(self, db: str, fn):
        """Run `fn` with the database's client. A lost session (an immudb restart) is logged in again
        once and retried, so the same store recovers on its own (review B1)."""
        for attempt in (1, 2):
            client, lock = self._client(db)
            with lock:
                try:
                    return fn(client)
                except (LedgerError, KeyError):
                    raise
                except Exception as exc:
                    if attempt == 1 and _session_lost(exc):
                        with self._lock:
                            if self._clients.get(db, (None,))[0] is client:
                                del self._clients[db]
                        continue
                    raise _classify(exc, db) from exc

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
            # or immudb refuses the whole transaction and the loser looks again (review B2).
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

    def export_head(self, db: str, seq: int, chain: str) -> dict:
        """Not yet (open item S9): an immudb export must carry immudb's own inclusion proofs and its
        server-signed state, which the offline checker verifies; the platform holds no signing key."""
        raise NotImplementedError("exports from immudb need its inclusion proofs (open item S9)")

    def reanchor(self, db: str) -> tuple:
        """After a restore: forget the saved state, so the next read anchors on the server (spec T21)."""
        old = self._states.get(db)
        if hasattr(self._states, "forget"):
            self._states.forget(db)
        with self._lock:
            self._clients.pop(db, None)
        return (old.tx_id if old else 0), 0


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
    """immudb's errors, sorted by what the caller must do (spike M1-M15, review minor 1)."""
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
