#!/usr/bin/env python3
"""Restore the provider's risk measures that the no_risk_measures migrations dropped, from the ledger's copies.

The qualification and control-objectives no_risk_measures migrations dropped four columns of
qualification.qualification_risk (control, control_term, followUpControl, follow_up_control_term) from every
card version, closed ones included, without keeping what they held. Each qualification.created and
qualification.amended event in a project's ledger.outbox carries the card it saved, risks and measures
included. This command reads them back and keeps them in the card's own history (qualification.card_history,
append-only): one row per risk that had a measure, kind `risk_measures_dropped`, subject `risk:<position>`,
`before` holding the four values and the ledger event they came from, changed by `operator`.

Nothing is invented: a value is restored only as an event holds it. A card the project no longer has (its
version was removed by hand) cannot take a history row: it is listed as not restored, with the event it came
from. A risk already restored is not written again.

    scripts/restore-dropped-risk-measures.py [--database project_<hex>]... [--container NAME]        dry run
    scripts/restore-dropped-risk-measures.py --yes [--database project_<hex>]... [--declaration FILE]

Without --yes it writes nothing and prints, per project database, how many measures it found, how many it
would restore, and which cards cannot take them. With --yes it writes them, one transaction per database, and
writes the body of the declaration for POST /api/ledger/corrections (what, why, items, and what could not be
restored) to --declaration (default: printed). Declaring is a separate step, made by an admin.

It reaches the stack's Postgres with `docker exec` as the superuser the container names (POSTGRES_USER), and
never prints a password. Back up first (scripts/backup-databases.sh).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD_EVENTS = ("qualification.created", "qualification.amended")
KIND = "risk_measures_dropped"
WHY = ("The no_risk_measures migrations dropped the provider's risk measures from every card "
       "version, closed ones included, without keeping them; they are restored from the ledger's copies of the "
       "cards into each card's history.")


def _value(risk: dict, *names):
    for name in names:
        if name in risk:
            return risk[name]
    return None


def measures_from_events(events) -> list[dict]:
    """One row per risk that had a measure, from the cards the events saved; the latest event of a card wins."""
    found: dict[tuple[str, int], dict] = {}
    for ev in sorted(events, key=lambda e: str(e.get("occurred_at") or "")):
        if ev.get("action") not in CARD_EVENTS:
            continue
        content = ev.get("content") or {}
        risks = content.get("risks") if isinstance(content, dict) else None
        for risk in risks if isinstance(risks, list) else []:
            if not isinstance(risk, dict) or not isinstance(risk.get("position"), int):
                continue
            row = {"qualification_id": str(ev["item_id"]), "position": risk["position"],
                   "control": _value(risk, "control"),
                   "control_term": _value(risk, "controlTerm", "control_term"),
                   "follow_up_control": _value(risk, "followUpControl", "follow_up_control"),
                   "follow_up_control_term": _value(risk, "followUpControlTerm", "follow_up_control_term"),
                   "source_event_id": str(ev["event_id"])}
            if row["control"] or row["follow_up_control"]:
                found[(row["qualification_id"], row["position"])] = row
            else:
                found.pop((row["qualification_id"], row["position"]), None)
    return list(found.values())


def plan(rows: list[dict], cards: set[str], restored: set[tuple[str, str]]) -> dict:
    """What a database's rows come to: restorable, already restored, and not restorable (no such card)."""
    out = {"restore": [], "already": [], "missing_card": []}
    for row in rows:
        if row["qualification_id"] not in cards:
            out["missing_card"].append(row)
        elif (row["qualification_id"], f"risk:{row['position']}") in restored:
            out["already"].append(row)
        else:
            out["restore"].append(row)
    return out


def insert_sql(rows: list[dict]) -> str:
    """One transaction that adds the rows to qualification.card_history."""
    tag = "m" + uuid.uuid4().hex
    payload = json.dumps([{"qualification_id": r["qualification_id"], "subject": f"risk:{r['position']}",
                           "before": {k: r[k] for k in ("control", "control_term", "follow_up_control",
                                                        "follow_up_control_term", "source_event_id")}}
                          for r in rows])
    assert f"${tag}$" not in payload
    return ("BEGIN;\n"
            "INSERT INTO qualification.card_history (qualification_id, kind, subject, before, changed_by)\n"
            f"SELECT r.qualification_id, '{KIND}', r.subject, r.before, 'operator'\n"
            f"FROM jsonb_to_recordset(${tag}${payload}${tag}$::jsonb)"
            " AS r(qualification_id text, subject text, before jsonb);\n"
            "COMMIT;\n")


def container_name() -> str:
    """The stack's Postgres container, as scripts/lib/stack-name.sh names it."""
    out = subprocess.run(["bash", "-c", f'. "{ROOT}/scripts/lib/stack-name.sh"; aisc_container postgres'],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


class Postgres:
    """psql in the stack's Postgres container, as its superuser (POSTGRES_USER, read inside the container)."""

    def __init__(self, container: str):
        self.container = container

    def run(self, database: str, sql: str) -> str:
        done = subprocess.run(
            ["docker", "exec", "-i", self.container, "sh", "-c",
             'exec psql -X -q -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"', "psql", database],
            input=sql, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"{database}: {done.stderr.strip()}")
        return done.stdout

    def json(self, database: str, sql: str):
        return json.loads(self.run(database, f"SELECT coalesce(json_agg(t), '[]') FROM ({sql}) t;").strip() or "[]")


def project_databases(pg: Postgres) -> list[str]:
    return [r["datname"] for r in pg.json("postgres", "SELECT datname FROM pg_database WHERE datname LIKE 'project\\_%'"
                                                       " ORDER BY datname")]


def has_tables(pg: Postgres, database: str) -> bool:
    [row] = pg.json(database, "SELECT to_regclass('ledger.outbox') IS NOT NULL AS ledger,"
                              " to_regclass('qualification.card_history') IS NOT NULL AS history")
    return bool(row["ledger"] and row["history"])


def read(pg: Postgres, database: str) -> dict:
    events = pg.json(database, "SELECT event_id, action, item_id, occurred_at, content FROM ledger.outbox"
                               " WHERE action IN ('qualification.created', 'qualification.amended')")
    cards = {r["id"] for r in pg.json(database, "SELECT id FROM qualification.qualification")}
    restored = {(r["qualification_id"], r["subject"]) for r in pg.json(
        database, f"SELECT qualification_id, subject FROM qualification.card_history WHERE kind = '{KIND}'")}
    return plan(measures_from_events(events), cards, restored)


def declaration(results: dict) -> dict:
    """The body of POST /api/ledger/corrections for one project database's restore (the admin adds `project`)."""
    done = results["restore"]
    what = (f"restored {len(done)} risk measures of {len({r['qualification_id'] for r in done})} cards into"
            f" qualification.card_history (kind {KIND}) from ledger.outbox content")
    if results["missing_card"]:
        what += (f"; {len(results['missing_card'])} measures of cards no longer in the project could not be"
                 " restored: " + ", ".join(sorted({f"{r['qualification_id']} (event {r['source_event_id']})"
                                                   for r in results["missing_card"]})))
    return {"what": what[:2000], "why": WHY,
            "items": sorted({f"qualification:{r['qualification_id']}" for r in done})[:50]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore the dropped risk measures from the ledger's copies of "
                                                 "the cards. A dry run unless --yes.")
    parser.add_argument("--yes", action="store_true", help="write the restored measures; without it nothing is written")
    parser.add_argument("--database", action="append", default=[], help="a project database (default: every one)")
    parser.add_argument("--container", help="the Postgres container (default: this install's)")
    parser.add_argument("--declaration", help="write the declarations (JSON) here instead of printing them")
    args = parser.parse_args(argv)
    pg = Postgres(args.container or container_name())
    declarations = {}
    for database in args.database or project_databases(pg):
        if not has_tables(pg, database):
            print(f"{database}: no ledger outbox or card history; skipped")
            continue
        results = read(pg, database)
        print(f"{database}: {len(results['restore'])} to restore, {len(results['already'])} already restored,"
              f" {len(results['missing_card'])} not restorable (card gone)")
        for row in results["missing_card"]:
            print(f"  not restorable: card {row['qualification_id']} risk {row['position']}"
                  f" (event {row['source_event_id']})")
        if not args.yes:
            continue
        if results["restore"]:
            pg.run(database, insert_sql(results["restore"]))
            print(f"  restored {len(results['restore'])}")
        if results["restore"] or (results["missing_card"] and not results["already"]):
            declarations[database] = declaration(results)
    if not args.yes:
        print("nothing written: run again with --yes to restore")
        return 0
    text = json.dumps(declarations, indent=2, sort_keys=True)
    if args.declaration:
        Path(args.declaration).write_text(text + "\n")
        print(f"declarations written to {args.declaration}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
