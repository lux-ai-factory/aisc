"""The report (JSON, mode 600) and the human summary (01-specs.md I12.15, I12.16).

Both hold pids, table names, keys, counts, statuses, md5s and refusal reasons: never a
row value and never a credential.
"""
from __future__ import annotations

import json
import os
import re

import psycopg
from psycopg.conninfo import conninfo_to_dict


def new(subcommand: str, dry_run: bool) -> dict:
    return {"subcommand": subcommand, "dry_run": dry_run, "snapshot_time": None,
            "classification": {}, "refusals": [], "projects": {}, "library": {},
            "unowned": [], "coverage": {}}


def write(path: str, rep: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(rep, f, indent=1, sort_keys=True, default=str)
        f.write("\n")


def redact(text: str, dsn: str | None) -> str:
    """Remove the DSN's password (and any password= or user:password@ in the text)."""
    if dsn:
        try:
            pw = str(conninfo_to_dict(dsn).get("password") or "")
        except Exception:
            pw = ""
        if pw:
            text = text.replace(pw, "***")
    text = re.sub(r"(password\s*=\s*)\S+", r"\1***", text, flags=re.I)
    return re.sub(r"(postgres(?:ql)?://[^:/@\s]+:)[^@\s]+@", r"\1***@", text)


def describe(exc: BaseException, dsn: str | None) -> str:
    """An exception without row data: for a database error, its class, sqlstate, constraint
    and table only (the message and detail can quote key or row values)."""
    if isinstance(exc, psycopg.Error):
        d = exc.diag
        parts = [type(exc).__name__, f"sqlstate={exc.sqlstate}"]
        if d.constraint_name:
            parts.append(f"constraint={d.constraint_name}")
        if d.schema_name and d.table_name:
            parts.append(f"table={d.schema_name}.{d.table_name}")
        return " ".join(parts)
    return redact(f"{type(exc).__name__}: {exc}", dsn)


def summary(rep: dict) -> str:
    lines = [f"isolate {rep['subcommand']}{' --dry-run' if rep.get('dry_run') else ''}"
             f" (snapshot {rep.get('snapshot_time')})"]
    for pid, p in sorted(rep.get("projects", {}).items()):
        lines.append(f"project {pid} ({p.get('database')}): {p.get('status')}"
                     + (f" [{p['error']}]" if p.get("error") else ""))
        for t, e in sorted((p.get("tables") or {}).items()):
            lines.append(f"  {t} -> {e['target']}: source {e['source_rows']}, to copy {e['to_copy']},"
                         f" present {e['already_present']}, copied {e['copied']}, count {e['count']}")
    lib = rep.get("library") or {}
    if lib:
        lines.append(f"library: {lib.get('status')}")
        for t, e in sorted((lib.get("tables") or {}).items()):
            lines.append(f"  {t} -> {e['target']}: source {e['source_rows']}, to copy {e['to_copy']},"
                         f" present {e['already_present']}, copied {e['copied']}, count {e['count']}")
    unowned = rep.get("unowned") or []
    if unowned:
        by: dict[tuple[str, str], int] = {}
        for u in unowned:
            by[(u["table"], u["reason"])] = by.get((u["table"], u["reason"]), 0) + 1
        lines.append(f"unowned rows: {len(unowned)}")
        for (t, reason), n in sorted(by.items()):
            lines.append(f"  {t}: {n} ({reason})")
    cov = rep.get("coverage") or {}
    if cov:
        missing = {t: c["missing"] for t, c in cov.items() if c["missing"]}
        lines.append(f"coverage: {len(cov)} tables, {sum(missing.values())} rows missing")
    refusals = rep.get("refusals") or []
    if refusals:
        lines.append(f"REFUSED ({len(refusals)}):")
        for r in refusals:
            who = ", ".join(r.get("projects") or ([r["project"]] if r.get("project") else []))
            lines.append(f"  {r['reason']}: table {r.get('table') or '-'}; projects {who or '-'};"
                         f" keys {len(r.get('keys') or [])}" + (f"; {r['detail']}" if r.get("detail") else ""))
    else:
        lines.append("no refusals")
    return "\n".join(lines)
