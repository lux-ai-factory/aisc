"""The shape of the source and target databases, read from the catalog at run time.

Nothing here names a module table: the tables, their columns, keys, foreign keys and
sequences come from pg_class, pg_attribute and pg_constraint (01-specs.md I12.1). The
only hand-written knowledge is the handful of constant sets below (I12.1, S-D2).
"""
from __future__ import annotations

from dataclasses import dataclass, field

MOVING_SCHEMAS = ("qualification", "control_objectives", "engine", "report_composer")
#: core moves only this table; it becomes project.system in each project database (D1).
CORE_SYSTEM = "core.system"
CORE_PROJECT = "core.project"
STAYS_SHARED = {"core.project", "core.project_member", "core.schema_migration"}
SHARED_SCHEMAS = ("catalogue",)
BOOKKEEPING = {
    "qualification._prisma_migrations",
    "control_objectives.alembic_version",
    "engine.django_migrations",
    "engine.django_content_type",
    "report_composer.schema_migration",
}
#: Install-wide libraries in `platform` (D3, D4, I12.9): source table -> library table.
LIBRARY = {
    "qualification.form": "form_library.form",
    "qualification.form_version": "form_library.form_version",
    "qualification.form_question": "form_library.form_question",
    "qualification.form_version_question": "form_library.form_version_question",
    "report_composer.preset": "report_library.preset",
}
#: Library tables that are never copied into a project and are never a root (S-D2).
LIBRARY_ONLY = {"report_composer.preset"}
#: I1.5, I1.7: the only source columns a target may lack.
DROPPED_COLUMNS = {
    "core.system": {"project_id"},
    "qualification.qualification": {"project_id"},
    "control_objectives.project": {"project_id"},
    "report_composer.layout": {"project_id"},
    "report_composer.template": {"project_id"},
    "report_composer.generated_report": {"project_id"},
}


def target_of(table: str) -> str:
    """I12.2: where a source table's rows go inside a project database."""
    return "project.system" if table == CORE_SYSTEM else table


_INTEGER = {"integer", "bigint", "smallint"}


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    not_null: bool
    has_default: bool
    generated: bool = False


@dataclass(frozen=True)
class Fk:
    name: str
    columns: tuple[str, ...]
    ref_table: str
    ref_columns: tuple[str, ...]


@dataclass
class Table:
    name: str
    columns: list[Column]
    pk: tuple[str, ...]
    fks: list[Fk] = field(default_factory=list)
    sequences: dict[str, str] = field(default_factory=dict)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def key_json(self, key: tuple) -> dict:
        """A text key as the report shows it: integers as numbers, everything else as text."""
        out = {}
        for c, v in zip(self.pk, key):
            col = self.column(c)
            out[c] = int(v) if v is not None and col is not None and col.type in _INTEGER else v
        return out

    def column(self, name: str) -> Column | None:
        for c in self.columns:
            if c.name == name:
                return c
        return None


_TABLES = """
SELECT c.oid, n.nspname || '.' || c.relname
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(%s)
 ORDER BY 2
"""
_COLUMNS = """
SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
       a.atthasdef OR a.attidentity <> '', a.attgenerated <> '',
       pg_get_serial_sequence(quote_ident(n.nspname) || '.' || quote_ident(c.relname), a.attname)
  FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE a.attrelid = ANY(%s) AND a.attnum > 0 AND NOT a.attisdropped
 ORDER BY a.attrelid, a.attnum
"""
_CONSTRAINTS = """
SELECT con.conrelid, con.contype, con.conname,
       (SELECT array_agg(a.attname ORDER BY k.ord) FROM unnest(con.conkey) WITH ORDINALITY k(n, ord)
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.n),
       fn.nspname || '.' || fc.relname,
       (SELECT array_agg(a.attname ORDER BY k.ord) FROM unnest(con.confkey) WITH ORDINALITY k(n, ord)
          JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.n)
  FROM pg_constraint con
  LEFT JOIN pg_class fc ON fc.oid = con.confrelid
  LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace
 WHERE con.conrelid = ANY(%s) AND con.contype IN ('p', 'f')
 ORDER BY con.conrelid, con.conname
"""


def read_tables(conn, schemas) -> dict[str, Table]:
    """Every ordinary table of `schemas`, with columns in attnum order."""
    rows = conn.execute(_TABLES, (list(schemas),)).fetchall()
    by_oid = {oid: name for oid, name in rows}
    tables = {name: Table(name=name, columns=[], pk=()) for name in by_oid.values()}
    if not by_oid:
        return tables
    oids = list(by_oid)
    for oid, col, typ, notnull, hasdef, generated, seq in conn.execute(_COLUMNS, (oids,)).fetchall():
        t = tables[by_oid[oid]]
        t.columns.append(Column(col, typ, bool(notnull), bool(hasdef), bool(generated)))
        if seq:
            t.sequences[col] = seq
    for oid, kind, name, cols, ref, refcols in conn.execute(_CONSTRAINTS, (oids,)).fetchall():
        t = tables[by_oid[oid]]
        if kind == "p":
            t.pk = tuple(cols)
        else:
            t.fks.append(Fk(name, tuple(cols), ref, tuple(refcols)))
    return tables


def source_tables(conn) -> dict[str, Table]:
    """The moving tables of the source (I12.1) plus the shared core tables they reference."""
    tables = read_tables(conn, MOVING_SCHEMAS + ("core",))
    return {n: t for n, t in tables.items()
            if n.split(".")[0] in MOVING_SCHEMAS or n == CORE_SYSTEM or n in STAYS_SHARED}


def moving(tables: dict[str, Table]) -> list[str]:
    return sorted(n for n in tables if n.split(".")[0] in MOVING_SCHEMAS or n == CORE_SYSTEM)


def is_link(t: Table) -> bool:
    """Rule L: a many-to-many link row (its columns are only a one-column primary key and
    the columns of two or more foreign keys)."""
    if len(t.pk) != 1 or len(t.fks) < 2:
        return False
    fk_cols = {c for fk in t.fks for c in fk.columns}
    return set(t.column_names) == set(t.pk) | fk_cols and t.pk[0] not in fk_cols


def is_identifying(t: Table, fk: Fk) -> bool:
    return bool(t.pk) and set(fk.columns) <= set(t.pk)


def _is_shared(table: str) -> bool:
    return table in STAYS_SHARED or table.split(".")[0] in SHARED_SCHEMAS


@dataclass
class Classification:
    labels: dict[str, str]                 # schema.table -> label of the report
    root: set[str]
    owned: set[str]
    needed: set[str]
    unclassified: dict[str, str]           # schema.table -> detail


def classify(tables: dict[str, Table]) -> Classification:
    """I12.1/I12.3 at table level: which rule places each moving table's rows."""
    labels: dict[str, str] = {}
    rest: set[str] = set()
    for n in moving(tables):
        if n in BOOKKEEPING:
            labels[n] = "bookkeeping"
        elif n in LIBRARY_ONLY:
            labels[n] = "library"
        else:
            rest.add(n)
    for n in tables:
        if n in STAYS_SHARED:
            labels[n] = "stays shared"
    root = {n for n in rest if any(fk.ref_table == CORE_PROJECT for fk in tables[n].fks)}
    owned: set[str] = set()
    changed = True
    while changed:
        changed = False
        for n in rest - root - owned:
            if any(fk.ref_table in root | owned for fk in tables[n].fks):
                owned.add(n)
                changed = True
    needed: set[str] = set()
    changed = True
    while changed:
        changed = False
        placed = root | owned | needed
        for n in sorted(rest - placed):
            t = tables[n]
            referenced = any(fk.ref_table == n for p in placed for fk in tables[p].fks)
            identifying = any(is_identifying(t, fk) and fk.ref_table in placed for fk in t.fks)
            link = is_link(t) and any(fk.ref_table in placed for fk in t.fks)
            if referenced or identifying or link:
                needed.add(n)
                changed = True
    unclassified: dict[str, str] = {}
    for n in sorted(rest):
        if not tables[n].pk:
            unclassified[n] = "no primary key"
        elif n not in root | owned | needed:
            unclassified[n] = "no rule places it"
    for n in rest:
        if n in unclassified:
            labels[n] = "unclassified"
        elif n in root:
            labels[n] = "root"
        elif n in owned:
            labels[n] = "owned"
        else:
            labels[n] = "needed"
    return Classification(labels, root, owned, needed, unclassified)
