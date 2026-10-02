"""A5: the offline checker on its own (spec 7.4, R4.9). It trusts only the public key it is given: a
reordered, shortened or re-signed file fails, and its canonical JSON is the platform's byte for byte."""
from __future__ import annotations

import importlib.util
import json
import random
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from platform_service.ledger import export
from platform_service.ledger.canonical import canonical
from platform_service.ledger.store import MemoryLedger, TamperAlarm

ROOT = Path(__file__).resolve().parents[3]
CHECKER = ROOT / "scripts" / "verify-ledger-export.py"


def _checker():
    spec = importlib.util.spec_from_file_location("verify_ledger_export", CHECKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _value(rng, depth=0):
    kind = rng.randrange(7 if depth < 3 else 5)
    if kind == 0:
        return None
    if kind == 1:
        return rng.random() < 0.5
    if kind == 2:
        return rng.randint(-2 ** 53, 2 ** 53)
    if kind == 3:
        return rng.choice([rng.uniform(-1e6, 1e6), rng.random() * 10 ** rng.randint(-30, 30), 0.1, 1e21, 1e-7])
    if kind == 4:
        return "".join(chr(rng.choice([rng.randint(0, 0x7f), rng.randint(0x80, 0xd7ff),
                                       rng.randint(0xe000, 0x10ffff)])) for _ in range(rng.randint(0, 8)))
    if kind == 5:
        return [_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {str(_value(rng, 3)): _value(rng, depth + 1) for _ in range(rng.randint(0, 4))}


def test_the_checkers_canonical_json_is_the_platforms():
    check = _checker()
    rng = random.Random(8785)
    for _ in range(3000):
        value = _value(rng)
        assert check.canonical(value) == canonical(value), value


def _export(n=3):
    store = MemoryLedger()
    log = "ledger" + uuid.uuid4().hex
    store.create(log)
    for i in range(n):
        store.append(log, {"event_id": str(uuid.uuid4()), "action": "risk.rated", "item_id": f"r{i}"})
    lines, chain = [], export.GENESIS
    for e in store.scan(log, after_seq=0, limit=100):
        previous, chain = chain, export.link(chain, e.as_dict())
        lines.append({"entry": e.as_dict(), "proof": {"previous": previous, "chain": chain}})
    return store, log, lines + [{"head": store.export_head(log, n, chain)}]


def _run(tmp_path, lines, pem):
    path, key = tmp_path / "e.jsonl", tmp_path / "k.pub"
    path.write_text("\n".join(json.dumps(line) for line in lines))
    key.write_text(pem)
    return subprocess.run([sys.executable, str(CHECKER), "--public-key", str(key), str(path)],
                          capture_output=True, text=True)


def test_a_true_export_passes(tmp_path):
    store, _, lines = _export()
    r = _run(tmp_path, lines, store.public_key_pem())
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("edit", ["swap", "drop_last", "drop_first"])
def test_a_reordered_or_shortened_export_fails_even_rehashed(tmp_path, edit):
    from platform_service.ledger import testing

    store, _, lines = _export(4)
    body, head = lines[:-1], lines[-1]
    if edit == "swap":
        body[1], body[2] = body[2], body[1]
    elif edit == "drop_last":
        body = body[:-1]
    else:
        body = body[1:]
    forged = testing.rehash_export(body + [head])
    assert _run(tmp_path, forged, store.public_key_pem()).returncode != 0


def test_another_keys_signature_fails(tmp_path):
    store, _, lines = _export()
    assert _run(tmp_path, lines, MemoryLedger().public_key_pem()).returncode != 0


def test_the_store_signs_only_its_own_chain():
    store, log, lines = _export()
    with pytest.raises(TamperAlarm):
        store.export_head(log, 3, "ff" * 32)


def test_an_unreadable_file_is_exit_2(tmp_path):
    r = subprocess.run([sys.executable, str(CHECKER), "--public-key", str(tmp_path / "none"), str(tmp_path / "none")],
                       capture_output=True, text=True)
    assert r.returncode == 2
