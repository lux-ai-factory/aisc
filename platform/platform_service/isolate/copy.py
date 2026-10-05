"""Comparing, copying and verifying one target: a project database or the library.

A target is a set of maps (source table -> target table) and, per map, the keys of the
source rows that belong there (the copied set). The source connection is the run's one
REPEATABLE READ READ ONLY snapshot and is only ever read (SELECT and COPY TO). The
target connection is a superuser connection in one transaction; it is committed only by
`write()` after every check passed, and rolled back in every other case.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from psycopg import sql

from . import rowtext as R
from .catalog import Table, read_tables
from .preconditions import refusal

log = logging.getLogger("platform_service.isolate")


class Abort(Exception):
    """A refusal found while working on one target: that target is rolled back."""

    def __init__(self, refusals: list[dict]):
        super().__init__(", ".join(sorted({r["reason"] for r in refusals})))
        self.refusals = refusals


@dataclass
class Map:
    source: Table
    target: Table
    keys: set  # copied set: text keys of the source rows that belong in this target

    @property
    def name(self) -> str:
        return self.source.name

    @property
    def cols(self) -> list[str]:
        """Shared columns in target column order (the order the row text is built in)."""
        src = set(self.source.column_names)
        return [c.name for c in self.target.columns if c.name in src]

    @property
    def insert_cols(self) -> list[str]:
        return [c for c in self.cols if not self.target.column(c).generated]


@dataclass
class TableState:
    source_rows: int = 0
    to_copy: int = 0
    already_present: int = 0
    copied: int = 0
    count: int = 0
    source_md5: str = ""
    target_md5: str = ""
    source_count: int = 0
    missing: list = field(default_factory=list)
    bad: list = field(default_factory=list)
    verified_keys: set = field(default_factory=set)

    def report(self, target: str) -> dict:
        return {"target": target, "source_rows": self.source_rows, "to_copy": self.to_copy,
                "already_present": self.already_present, "copied": self.copied, "count": self.count,
                "source_md5": self.source_md5, "target_md5": self.target_md5}


class SourceCache:
    """Per-key md5s of the source, computed once per (table, columns) in the snapshot."""

    def __init__(self, conn):
        self.conn = conn
        self._md5: dict = {}

    def md5s(self, table: Table, cols: list[str]) -> dict:
        k = (table.name, tuple(cols))
        if k not in self._md5:
            self._md5[k] = R.key_md5s(self.conn, table.name, cols, table.pk)
        return self._md5[k]


def target_tables(conn) -> dict[str, Table]:
    schemas = [r[0] for r in conn.execute(
        "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema'"
    ).fetchall()]
    return read_tables(conn, schemas)


def begin_target(conn) -> None:
    conn.execute("SET LOCAL session_replication_role = replica")
    R.apply_settings(conn, local=True)


def compare(src: SourceCache, tgt, m: Map) -> TableState:
    """The target rows against the copied set: present and equal, missing, or bad
    (a copied key that differs, or an extra row that is not an equal copy of a source row)."""
    cols, pk = m.cols, m.source.pk
    s = src.md5s(m.source, cols)
    t = R.key_md5s(tgt, m.target.name, cols, pk)
    st = TableState(source_rows=len(s), to_copy=len(m.keys))
    for k in sorted(m.keys):
        if k not in t:
            st.missing.append(k)
        elif t[k] != s.get(k):
            st.bad.append(k)
        else:
            st.already_present += 1
            st.verified_keys.add(k)
    for k in sorted(set(t) - m.keys):
        if s.get(k) != t[k]:
            st.bad.append(k)
    return st


def sums(src_conn, tgt, m: Map, st: TableState) -> None:
    pk = m.source.pk
    st.count, st.target_md5 = R.checksum(tgt, m.target.name, m.cols, pk, m.keys)
    n, st.source_md5 = R.checksum(src_conn, m.source.name, m.cols, pk, m.keys)
    st.source_count = n


def keydicts(m: Map, keys) -> list[dict]:
    return [m.source.key_json(k) for k in keys]


def insert_missing(src_conn, tgt, m: Map, keys) -> int:
    """COPY TO from the source snapshot piped into COPY FROM on the target (text format under
    SETTINGS keeps every value exact)."""
    if not keys:
        return 0
    cols = m.insert_cols
    out = sql.SQL("COPY (SELECT {c} FROM {t} WHERE {w}) TO STDOUT").format(
        c=R.cols_sql(cols), t=R.ident(m.source.name), w=R.key_filter(m.source.pk, keys))
    into = sql.SQL("COPY {t} ({c}) FROM STDIN").format(t=R.ident(m.target.name), c=R.cols_sql(cols))
    with src_conn.cursor().copy(out) as reader, tgt.cursor().copy(into) as writer:
        for block in reader:
            writer.write(block)
    return len(keys)


def fk_orphans(conn, tables: dict[str, Table]) -> list[str]:
    """Every foreign key of the target checked by an anti-join (the insert ran with
    session_replication_role = replica, so the database did not check them)."""
    out = []
    for t in tables.values():
        for fk in t.fks:
            cond = sql.SQL(" AND ").join(
                sql.SQL("p.{} = c.{}").format(sql.Identifier(pc), sql.Identifier(cc))
                for cc, pc in zip(fk.columns, fk.ref_columns))
            notnull = sql.SQL(" AND ").join(sql.SQL("c.{} IS NOT NULL").format(sql.Identifier(cc)) for cc in fk.columns)
            q = sql.SQL("SELECT count(*) FROM {} c WHERE {} AND NOT EXISTS (SELECT 1 FROM {} p WHERE {})").format(
                R.ident(t.name), notnull, R.ident(fk.ref_table), cond)
            n = conn.execute(q).fetchone()[0]
            if n:
                out.append(f"{t.name}.{fk.name} ({n})")
    return out


def _seq_value(conn, seq: str) -> tuple[int, bool]:
    last, called = conn.execute(sql.SQL("SELECT last_value, is_called FROM {}").format(sql.SQL(seq))).fetchone()
    return int(last), bool(called)


def _max(conn, table: str, col: str, pk=None, keys=None):
    q = sql.SQL("SELECT max({c}) FROM {t}").format(c=sql.Identifier(col), t=R.ident(table))
    if keys is not None:
        q = q + sql.SQL(" WHERE ") + R.key_filter(pk, keys)
    v = conn.execute(q).fetchone()[0]
    return None if v is None else int(v)


def plan_sequences(src_conn, tgt, maps: list[Map], *, after_insert: bool) -> dict[str, tuple[str, int, bool]]:
    """Each target sequence takes the source's value, or the target's maximum when that
    is at or past the source's next value (then is_called = true). Returns
    {report name: (sequence, last_value, is_called)}."""
    out = {}
    for m in maps:
        for col, tseq in sorted(m.target.sequences.items()):
            sseq = m.source.sequences.get(col)
            tmax = _max(tgt, m.target.name, col)
            if not after_insert and m.keys and m.source.column(col) is not None:
                smax = _max(src_conn, m.source.name, col, m.source.pk, m.keys)
                if smax is not None and (tmax is None or smax > tmax):
                    tmax = smax
            if sseq:
                last, called = _seq_value(src_conn, sseq)
                nxt = last + 1 if called else last
                value = (tmax, True) if tmax is not None and tmax >= nxt else (last, called)
            elif tmax is not None:
                value = (tmax, True)
            else:
                continue
            out[tseq.replace('"', "")] = (tseq, value[0], value[1])
    return out


def set_sequences(tgt, seqs: dict[str, tuple[str, int, bool]]) -> None:
    for _name, (seq, last, called) in seqs.items():
        tgt.execute("SELECT setval(%s::regclass, %s, %s)", (seq, last, called))


@dataclass
class Outcome:
    status: str
    tables: dict[str, TableState]
    sequences: dict[str, tuple[str, int, bool]] = field(default_factory=dict)
    refusals: list[dict] = field(default_factory=list)
    error: str | None = None


def check(src: SourceCache, tgt, maps: list[Map], label: dict) -> tuple[dict[str, TableState], list[dict]]:
    """Compare every map; a bad row is the refusal `target not empty and not equal`."""
    states, refusals = {}, []
    for m in maps:
        st = compare(src, tgt, m)
        states[m.name] = st
        if st.bad:
            refusals.append(refusal("target not empty and not equal", table=m.name,
                                    keys=keydicts(m, st.bad[:50]), **label))
    return states, refusals


def plan(src: SourceCache, tgt, maps: list[Map], label: dict) -> Outcome:
    """Read-only: what a copy would do. The caller rolls the target back."""
    R.apply_settings(tgt, local=True)
    states, refusals = check(src, tgt, maps, label)
    for m in maps:
        sums(src.conn, tgt, m, states[m.name])
    seqs = plan_sequences(src.conn, tgt, maps, after_insert=False)
    done = not refusals and all(not st.missing for st in states.values())
    return Outcome("already done" if done else "planned", states, seqs, refusals)


def write(src: SourceCache, tgt, maps: list[Map], label: dict) -> Outcome:
    """Copy into one target inside the caller's transaction; returns `copied` only after the
    foreign-key, count and checksum checks passed (the caller then commits), `already done`
    when nothing is missing (the caller rolls back). Raises Abort on a refusal."""
    begin_target(tgt)
    states, refusals = check(src, tgt, maps, label)
    if refusals:
        raise Abort(refusals)
    if all(not st.missing for st in states.values()):
        for m in maps:
            sums(src.conn, tgt, m, states[m.name])
        return Outcome("already done", states)
    for m in maps:
        st = states[m.name]
        st.copied = insert_missing(src.conn, tgt, m, st.missing)
        log.info("%s: %s rows into %s", label.get("project") or "library", st.copied, m.target.name)
    orphans = fk_orphans(tgt, target_tables(tgt))
    if orphans:
        raise Abort([refusal("count mismatch", detail="foreign-key orphans: " + "; ".join(orphans), **label)])
    bad = []
    for m in maps:
        st = states[m.name]
        sums(src.conn, tgt, m, st)
        if st.count != st.source_count or st.count != len(m.keys):
            bad.append(refusal("count mismatch", table=m.name, **label))
        elif st.target_md5 != st.source_md5:
            bad.append(refusal("checksum mismatch", table=m.name, **label))
    if bad:
        raise Abort(bad)
    seqs = plan_sequences(src.conn, tgt, maps, after_insert=True)
    set_sequences(tgt, seqs)
    return Outcome("copied", states, seqs)


def verify(src: SourceCache, tgt, maps: list[Map], label: dict) -> Outcome:
    """Verify from scratch: count and checksum of every map, plus extra rows that are not equal copies."""
    R.apply_settings(tgt, local=True)
    states, refusals = check(src, tgt, maps, label)
    for m in maps:
        st = states[m.name]
        sums(src.conn, tgt, m, st)
        if st.count != st.source_count:
            refusals.append(refusal("count mismatch", table=m.name, **label))
        elif st.target_md5 != st.source_md5:
            refusals.append(refusal("checksum mismatch", table=m.name, **label))
    return Outcome("verified" if not refusals else "failed", states, {}, refusals)
