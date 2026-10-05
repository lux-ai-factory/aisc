"""Which project each source row belongs to.

The rows' keys and foreign-key values are read once, in the run's snapshot, and the
placement is a fixpoint over the foreign-key graph child -> parent:

- root rows: rows with a foreign key to core.project; the owner is that value;
- owned(P): root rows of P, then every row with a foreign key to an owned(P) row;
- needed(P): a row (not shared) referenced by a foreign key of a copied(P) row, an
  identifying child (its primary key holds the foreign key's columns) of a copied(P)
  row, and a link row (see catalog.is_link) that references a copied(P) row;
- copied(P) = owned(P) + needed(P).

Conflicts are collected, never resolved: a row owned by two projects, a copied row
whose foreign key names a row owned by another project, a root row of a project that
is not in core.project. Row values are never kept: keys and foreign-key columns only,
as text.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from psycopg import sql

from .catalog import (CORE_PROJECT, LIBRARY, Classification, Table, is_identifying, is_link)

Key = tuple  # the primary-key values of a row, as text, in pk column order
Node = tuple  # (table, Key)


@dataclass
class RowGraph:
    keys: dict[str, list[Key]]                      # table -> every row's key
    parent: dict[tuple[Node, str], Node]            # (child node, fk name) -> parent node
    children: dict[Node, list[tuple[Node, str]]]    # parent node -> [(child node, fk name)]
    root_values: dict[Node, list[str | None]]       # root node -> its core.project values
    projects: list[str]                             # core.project pids, sorted


def _needed_columns(name: str, tables: dict[str, Table], placed: set[str]) -> list[str]:
    t = tables[name]
    cols = list(t.pk)
    for fk in t.fks:
        cols += fk.columns
    for other in placed:
        for fk in tables[other].fks:
            if fk.ref_table == name:
                cols += fk.ref_columns
    seen, out = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def load_keys(conn, tables: dict[str, Table], placed: set[str]) -> RowGraph:
    """One read per table of the keys and foreign-key columns (text), in the caller's snapshot."""
    projects = sorted(r[0] for r in conn.execute("SELECT pid::text FROM core.project").fetchall())
    values: dict[str, list[dict[str, str | None]]] = {}
    keys: dict[str, list[Key]] = {}
    for name in sorted(placed):
        cols = _needed_columns(name, tables, placed)
        q = sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(sql.SQL("{}::text").format(sql.Identifier(c)) for c in cols),
            sql.Identifier(*name.split(".")))
        rows = [dict(zip(cols, r)) for r in conn.execute(q).fetchall()]
        values[name] = rows
        pk = tables[name].pk
        keys[name] = [tuple(r[c] for c in pk) for r in rows]
    index: dict[tuple[str, tuple[str, ...]], dict[tuple, Key]] = {}

    def lookup(table: str, cols: tuple[str, ...], vals: tuple) -> Key | None:
        ix = index.get((table, cols))
        if ix is None:
            pk = tables[table].pk
            ix = {tuple(r[c] for c in cols): tuple(r[c] for c in pk) for r in values[table]}
            index[(table, cols)] = ix
        return ix.get(vals)

    parent: dict[tuple[Node, str], Node] = {}
    children: dict[Node, list[tuple[Node, str]]] = defaultdict(list)
    root_values: dict[Node, list[str | None]] = {}
    for name in sorted(placed):
        t = tables[name]
        for r, k in zip(values[name], keys[name]):
            node = (name, k)
            for fk in t.fks:
                vals = tuple(r[c] for c in fk.columns)
                if fk.ref_table == CORE_PROJECT:
                    ref = dict(zip(fk.ref_columns, vals))
                    root_values.setdefault(node, []).append(ref.get("pid") if None not in vals else None)
                    continue
                if fk.ref_table not in placed or None in vals:
                    continue
                pk = lookup(fk.ref_table, fk.ref_columns, vals)
                if pk is None:
                    continue  # a source orphan: the target's foreign-key check refuses it
                pnode = (fk.ref_table, pk)
                parent[(node, fk.name)] = pnode
                children[pnode].append((node, fk.name))
    return RowGraph(keys, parent, dict(children), root_values, projects)


@dataclass
class Placement:
    owners: dict[Node, set[str]]
    copied: dict[str, dict[str, set[Key]]]          # pid -> table -> keys
    conflicts: list[dict] = field(default_factory=list)
    unowned: list[dict] = field(default_factory=list)


def _key_dict(tables: dict[str, Table], table: str, key: Key) -> dict:
    return tables[table].key_json(key)


def place(graph: RowGraph, tables: dict[str, Table], cls: Classification) -> Placement:
    projects = set(graph.projects)
    owners: dict[Node, set[str]] = defaultdict(set)
    conflicts: dict[tuple, dict] = {}

    def conflict(reason: str, table: str, key: Key, pids) -> None:
        pids = sorted(set(pids))
        c = conflicts.setdefault((reason, table, tuple(pids)), {
            "reason": reason, "table": table, "project": pids[0] if len(pids) == 1 else None,
            "projects": pids, "keys": []})
        kd = _key_dict(tables, table, key)
        if kd not in c["keys"]:
            c["keys"].append(kd)

    # roots, then owned(P) down the child edges
    queue: deque[tuple[Node, str]] = deque()
    for node, vals in graph.root_values.items():
        if node[0] not in cls.root:
            continue
        for v in vals:
            if v is None:
                continue
            if v not in projects:
                conflict("unknown project", node[0], node[1], [v])
                continue
            if v not in owners[node]:
                owners[node].add(v)
                queue.append((node, v))
    while queue:
        node, pid = queue.popleft()
        for child, _fk in graph.children.get(node, ()):
            if child[0] in cls.root | cls.owned and pid not in owners[child]:
                owners[child].add(pid)
                queue.append((child, pid))
    for node, pids in owners.items():
        if len(pids) > 1:
            conflict("owned by two projects", node[0], node[1], pids)

    copied: dict[str, dict[str, set[Key]]] = {}
    placeable = cls.root | cls.owned | cls.needed
    for pid in sorted(projects):
        mine: set[Node] = {n for n, o in owners.items() if pid in o}
        todo = deque(sorted(mine))
        while todo:
            node = todo.popleft()
            t = tables[node[0]]
            for fk in t.fks:
                pnode = graph.parent.get((node, fk.name))
                if pnode is None or pnode[0] not in placeable:
                    continue
                own = owners.get(pnode)
                if own:
                    if pid not in own:
                        conflict("cross-project reference", node[0], node[1], {pid} | own)
                    continue
                if pnode not in mine:
                    mine.add(pnode)
                    todo.append(pnode)
            for child, fkname in graph.children.get(node, ()):
                if child in mine or owners.get(child) or child[0] not in placeable:
                    continue
                ct = tables[child[0]]
                fk = next(f for f in ct.fks if f.name == fkname)
                if is_identifying(ct, fk) or is_link(ct):
                    mine.add(child)
                    todo.append(child)
        by_table: dict[str, set[Key]] = {n: set() for n in sorted(placeable)}
        for table, key in mine:
            by_table[table].add(key)
        copied[pid] = by_table

    unowned: list[dict] = []
    in_some = {(t, k) for p in copied.values() for t, ks in p.items() for k in ks}
    for table in sorted(placeable):
        if table in LIBRARY:
            continue  # every row of a library table has the library as its target
        for key in graph.keys.get(table, []):
            node = (table, key)
            if node in in_some or owners.get(node):
                continue
            vals = graph.root_values.get(node)
            if table in cls.root and vals and any(v is not None and v not in projects for v in vals):
                continue  # refused as unknown project
            if table == "engine.aisc_backend_project":
                reason = "engine project without platform project"
            elif table in cls.root or table in cls.owned:
                reason = "no project"
            else:
                reason = "not used by any project"
            unowned.append({"table": table, "key": _key_dict(tables, table, key), "reason": reason})
    return Placement(dict(owners), copied, list(conflicts.values()), unowned)
