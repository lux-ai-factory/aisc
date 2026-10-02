"""immudb's transaction hashes, recomputed (open item S9; immudb 1.11, tx header version 1).

An export from immudb carries every transaction of the log's database, 1..N. From each one's entries the
checker recomputes the entries root (eH), then the header's accumulated hash (Alh), chained by prevAlh
from sha256(""), and compares the last with the state immudb signed. scripts/verify-ledger-export.py
holds the same rules for auditors (no platform code); the tests keep the two equal.
"""
from __future__ import annotations

import hashlib
import struct

FIRST_PREV_ALH = hashlib.sha256(b"").hexdigest()
_LEAF, _NODE = b"\x00", b"\x01"


def entry_digest(key: bytes, md: bytes, h_value: bytes) -> bytes:
    return hashlib.sha256(len(md).to_bytes(2, "big") + md + len(key).to_bytes(2, "big") + key + h_value).digest()


def entries_root(digests: list[bytes]) -> bytes:
    level = [hashlib.sha256(_LEAF + d).digest() for d in digests]
    while len(level) > 1:
        up = [hashlib.sha256(_NODE + level[i] + level[i + 1]).digest() for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            up.append(level[-1])
        level = up
    return level[0]


def alh(tx: dict) -> bytes:
    """The accumulated hash of one exported transaction header (hex fields as in the export)."""
    if tx["version"] != 1:
        raise ValueError(f"tx {tx['id']}: header version {tx['version']} is not supported")
    md = bytes.fromhex(tx["md"])
    inner = hashlib.sha256(tx["ts"].to_bytes(8, "big") + tx["version"].to_bytes(2, "big") +
                           len(md).to_bytes(2, "big") + md + tx["nentries"].to_bytes(4, "big") +
                           bytes.fromhex(tx["eH"]) + tx["blTxId"].to_bytes(8, "big") +
                           bytes.fromhex(tx["blRoot"])).digest()
    return hashlib.sha256(tx["id"].to_bytes(8, "big") + bytes.fromhex(tx["prevAlh"]) + inner).digest()


def value_hash(value: bytes) -> bytes:
    """immudb stores a plain value behind a one-byte prefix, and hashes it with the prefix."""
    return hashlib.sha256(b"\x00" + value).digest()


def state_message(db: str, tx_id: int, tx_hash: bytes) -> bytes:
    """What immudb signs for a state (immudb-py State.Hash)."""
    return struct.pack(">I", len(db)) + db.encode() + struct.pack(">Q", tx_id) + tx_hash


def check_txs(txs: list[dict]) -> list[bytes]:
    """Every transaction's Alh, after checking ids 1..N, the prevAlh chain and each entries root.
    ValueError names the first problem."""
    alhs = []
    previous = FIRST_PREV_ALH
    for n, tx in enumerate(txs, 1):
        if tx["id"] != n:
            raise ValueError(f"transaction {n} is missing (found {tx['id']})")
        if tx["prevAlh"] != previous:
            raise ValueError(f"transaction {n} doesn't follow the one before it")
        digests = [entry_digest(bytes.fromhex(e["key"]), bytes.fromhex(e["md"]), bytes.fromhex(e["hValue"]))
                   for e in tx["entries"]]
        if len(digests) != tx["nentries"] or entries_root(digests).hex() != tx["eH"]:
            raise ValueError(f"transaction {n}: its entries don't hash to its header")
        alhs.append(alh(tx))
        previous = alhs[-1].hex()
    return alhs
