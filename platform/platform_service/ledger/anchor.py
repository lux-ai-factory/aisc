"""The ledger's heads, verified and signed, for a copy kept outside the stack.

`heads(store)` gives, for the platform log and the log of each project, the head the store holds now: each
log is read whole and checked as an export is (a log that does not verify raises TamperAlarm, so a tampered
log is never anchored as if it were whole), and the head carries the store's signature. A project whose log
the store does not have is listed with that error instead of a head.

`python -m platform_service.ledger.anchor` prints `{"anchored_at", "heads"}` as one JSON document; the host's
scripts/ledger-anchor.sh writes it outside the stack once a day. With the copies kept elsewhere, a log rewritten
later (with the key that signs it, or by replacing the store) no longer matches a head written before.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


def _head(store, log: str, project_pid: str | None) -> dict:
    exported = store.export(log)[-1]["head"]                          # the whole log, checked, then its head
    if exported.get("format") == "immudb":
        state = exported["state"]
        tx, digest, signature = state["txId"], state["txHash"], state["signature"]
    else:
        tx, digest, signature = exported["seq"], exported["chain"], exported["signature"]
    return {"log": log, "project_pid": project_pid, "tx": int(tx), "hash": digest, "signature_b64": signature,
            "verified_at": datetime.now(timezone.utc).isoformat()}


def heads(store) -> list[dict]:
    """The verified, signed head of the platform log, then of each project's log."""
    from platform_service import db
    from platform_service.ledger import provision
    from platform_service.ledger.naming import PLATFORM_DB

    known = store.databases()
    out = [_head(store, PLATFORM_DB, None)]
    for project in db.list_projects():
        pid = str(project["pid"])
        log = provision.database_for(pid)
        if log is None:
            continue                                                  # no ledger yet: nothing to anchor
        if log not in known:
            out.append({"log": log, "project_pid": pid, "error": "the store has no such log"})
            continue
        out.append(_head(store, log, pid))
    return out


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(prog="python -m platform_service.ledger.anchor",
                            description="Print the ledger's verified, signed heads as one JSON document.").parse_args(argv)
    from platform_service import ledger

    document = {"anchored_at": datetime.now(timezone.utc).isoformat(), "heads": heads(ledger.current())}
    print(json.dumps(document, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
