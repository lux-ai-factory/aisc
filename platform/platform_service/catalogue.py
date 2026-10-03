"""A project's catalogue, public or private, chosen once (docs/superpowers/local-catalogue-2026-10-03/01-specs.md).

Nothing exists until the project chooses (D2): the choice creates schema `catalogue` in the project's
own database, as platform_rw, holding the mode; a private choice also creates the copy's tables and
fills them from the public catalogue, all in one transaction, so a failure leaves nothing (P1.3). The
choice is final (D1).

The copy holds the public catalogue's own JSON (its `GET /tool/?detailed=true`, `/tags/`, `/metric/`,
`/metadata/`), so the catalogue frontend reads it unchanged (P3). Local entries are not stored: they
are the packages the engine offers (`GET /api/v1/plugins`) whose package is in no public entry (P4),
read on every request; only the dimensions an admin gives them are kept.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import urllib.request

import psycopg
from psycopg import errors
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from platform_service import db, engine_components, evidence, projectdb

logger = logging.getLogger(__name__)
MODES = ("public", "private")
TIMEOUT_S = 20
#: R1..R11, as the control objectives name a dimension
R_IDS = tuple(rid for rid, _, _ in evidence.DIMENSIONS)
#: the keys of a public `GET /tool/?detailed=true` entry; a plain `GET /tool/` entry lacks the last four
_DETAIL_ONLY = ("metadata", "metrics", "questions", "tags")
TOOL_KEYS = ("available_on_devpi", "completion_status", "created_at", "description", "id", "licensing",
             "name", "package_name", "reviewed_at", "reviewed_by", "slug", "status", "storage_path",
             "submitted_by", "version") + _DETAIL_ONLY
#: local entries' ids, out of the public catalogue's range
LOCAL_ID_BASE = 1_000_000
LOCAL_SOURCE = "source-local"

_SCHEMA = """
CREATE SCHEMA catalogue;
CREATE TABLE catalogue.mode (
    mode      text PRIMARY KEY CHECK (mode IN ('public', 'private')),
    chosen_by text NOT NULL,
    chosen_at timestamptz NOT NULL DEFAULT now()
);
"""
_COPY = """
CREATE TABLE catalogue.entry (
    slug      text PRIMARY KEY,
    origin    text NOT NULL CHECK (origin IN ('public', 'local')),
    data      jsonb NOT NULL,
    synced_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE catalogue.tag (slug text PRIMARY KEY, data jsonb NOT NULL);
CREATE TABLE catalogue.metric (id bigint PRIMARY KEY, data jsonb NOT NULL);
CREATE TABLE catalogue.metadata (id bigint PRIMARY KEY, data jsonb NOT NULL);
CREATE TABLE catalogue.local_dimension (
    package_name text NOT NULL,
    dimension    text NOT NULL CHECK (dimension ~ '^R([1-9]|1[01])$'),
    PRIMARY KEY (package_name, dimension)
);
CREATE TABLE catalogue.state (id int PRIMARY KEY CHECK (id = 1), updated_at timestamptz NOT NULL);
"""


class AlreadyChosen(RuntimeError):
    """The project chose already (D1)."""


class PublicUnavailable(RuntimeError):
    """The public catalogue did not answer, or not with lists."""


class NotPrivate(RuntimeError):
    """The project has no private copy."""


class InvalidDimensions(ValueError):
    """Not R1..R11."""


def _connect(pid) -> psycopg.Connection:
    return psycopg.connect(make_conninfo(db.dsn(), dbname=projectdb.database_name(pid)), row_factory=dict_row)


# ── P1 the choice ───────────────────────────────────────────────────────────

def mode(pid) -> dict | None:
    """{"mode", "chosen_by", "chosen_at", "updated_at"}, or None when the project has not chosen."""
    with _connect(pid) as conn:
        try:
            row = conn.execute("SELECT mode, chosen_by, chosen_at FROM catalogue.mode").fetchone()
        except (errors.UndefinedTable, errors.InvalidSchemaName):
            return None
        if row is None:
            return None
        updated = None
        if row["mode"] == "private":
            state = conn.execute("SELECT updated_at FROM catalogue.state").fetchone()
            updated = state["updated_at"] if state else None
    return {**row, "updated_at": updated}


def choose(pid, chosen: str, who: str) -> dict:
    """Record the project's choice, once; a private one makes and fills the copy in the same transaction."""
    if chosen not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode(pid) is not None:
        raise AlreadyChosen("this project chose its catalogue already")
    public = fetch_public() if chosen == "private" else None   # before anything is made
    try:
        with _connect(pid) as conn, conn.transaction():
            conn.execute(_SCHEMA)
            conn.execute("INSERT INTO catalogue.mode (mode, chosen_by) VALUES (%s, %s)", (chosen, who))
            if public is not None:
                conn.execute(_COPY)
                _store(conn, public)
    except errors.DuplicateSchema:
        raise AlreadyChosen("this project chose its catalogue already") from None
    return mode(pid)


# ── P2 the copy and its update ──────────────────────────────────────────────

def _get(base: str, path: str):
    with urllib.request.urlopen(f"{base}{path}", timeout=TIMEOUT_S) as res:
        return json.loads(res.read())


def fetch_public() -> dict:
    """The public catalogue's four reads: {"tools" (detailed), "tags", "metric", "metadata"}."""
    base = (os.environ.get("CATALOGUE_URL") or "").rstrip("/")
    if not base:
        raise PublicUnavailable("CATALOGUE_URL is not set")
    try:
        out = {"tools": _get(base, "/tool/?detailed=true"), "tags": _get(base, "/tags/"),
               "metric": _get(base, "/metric/"), "metadata": _get(base, "/metadata/")}
    except (OSError, ValueError) as exc:
        raise PublicUnavailable(f"the public catalogue did not answer: {exc}") from None
    if not all(isinstance(v, list) for v in out.values()):
        raise PublicUnavailable("the public catalogue answered something that is not a list")
    return out


def _store(conn, public: dict) -> dict:
    """Make the copy match `public` (D3): public entries replaced, added or removed; local ones kept;
    tags, metrics and metadata replaced. Returns the counts."""
    current = {r["slug"]: r["data"] for r in conn.execute(
        "SELECT slug, data FROM catalogue.entry WHERE origin = 'public'").fetchall()}
    counts = {"added": 0, "updated": 0, "unchanged": 0, "removed": 0}
    wanted = {t["slug"]: t for t in public["tools"]}
    for slug, data in wanted.items():
        if slug not in current:
            counts["added"] += 1
        elif current[slug] != data:
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
            continue
        conn.execute("INSERT INTO catalogue.entry (slug, origin, data) VALUES (%s, 'public', %s)"
                     " ON CONFLICT (slug) DO UPDATE SET data = EXCLUDED.data, synced_at = now()",
                     (slug, Jsonb(data)))
    for slug in set(current) - set(wanted):
        conn.execute("DELETE FROM catalogue.entry WHERE slug = %s AND origin = 'public'", (slug,))
        counts["removed"] += 1
    for table, rows, key in (("tag", public["tags"], "slug"), ("metric", public["metric"], "id"),
                             ("metadata", public["metadata"], "id")):
        conn.execute(f"DELETE FROM catalogue.{table}")
        for row in rows:
            conn.execute(f"INSERT INTO catalogue.{table} ({key}, data) VALUES (%s, %s)", (row[key], Jsonb(row)))
    conn.execute("INSERT INTO catalogue.state (id, updated_at) VALUES (1, now())"
                 " ON CONFLICT (id) DO UPDATE SET updated_at = now()")
    return counts


def _require_private(pid) -> None:
    found = mode(pid)
    if found is None or found["mode"] != "private":
        raise NotPrivate("this project has no private catalogue")


def update(pid, token: str) -> dict:
    """P2.2: refresh the copy from the public catalogue; the public one not answering changes nothing."""
    _require_private(pid)
    public = fetch_public()
    with _connect(pid) as conn, conn.transaction():
        counts = _store(conn, public)
    counts["local_kept"] = len(_local_packages(pid, token, {t.get("package_name") for t in public["tools"]}))
    return counts


# ── P3 the catalogue-shaped reads ───────────────────────────────────────────

def plain_tool(entry: dict) -> dict:
    """A detailed tool entry as the plain `GET /tool/` gives it."""
    return {k: v for k, v in entry.items() if k not in _DETAIL_ONLY}


def _installed(pid) -> tuple[set, set]:
    """(package names installed in the engine, catalogue slugs of the installed checklists)."""
    with evidence._reader(pid) as conn:
        packages = evidence._rows(conn, "SELECT package_name FROM engine.aisc_backend_plugin")
        checklists = evidence._rows(conn, 'SELECT "catalogueId" AS slug FROM controls.checklist')
    return {r["package_name"] for r in packages}, {r["slug"] for r in checklists if r["slug"]}


def _stored(pid, table: str, order: str) -> list[dict]:
    with _connect(pid) as conn:
        return [r["data"] for r in conn.execute(f"SELECT data FROM catalogue.{table} ORDER BY {order}").fetchall()]


def _local_tag(tags: list[dict]) -> dict:
    """"Local" in the catalogue's Source filter, in a source tag's own shape."""
    like = next((t for t in tags if t.get("section") == "source"), None) or {
        "_color_text": None, "color_bg": None, "parent_dimension_slug": None}
    return {**like, "id": LOCAL_ID_BASE, "slug": LOCAL_SOURCE, "label": "Local", "section": "source",
            "parent_dimension_slug": None, "sort_order": 999}


def _local_packages(pid, token: str, public_packages: set) -> list[dict]:
    """The engine's available packages in no public entry, one per package (its latest listed version)."""
    try:
        listed = engine_components.available_plugins(pid, token)
    except engine_components.EngineUnavailable as exc:
        logger.warning("local plugins of project %s not listed: %s", pid, exc)
        return []
    out: dict[str, dict] = {}
    for p in listed:
        name = p.get("package_name")
        if name and name not in public_packages:
            out[name] = p
    return [out[k] for k in sorted(out)]


def _local_dimensions(pid) -> dict[str, list[str]]:
    with _connect(pid) as conn:
        rows = conn.execute("SELECT package_name, dimension FROM catalogue.local_dimension").fetchall()
    found: dict[str, list[str]] = {}
    for r in rows:
        found.setdefault(r["package_name"], []).append(r["dimension"])
    return {k: sorted(v, key=lambda rid: int(rid[1:])) for k, v in found.items()}


def tools(pid, token: str, detailed: bool) -> list[dict]:
    """P3.1, P3.2, P4.1: the copy's entries then the local ones, each with aisc_local and aisc_installed."""
    _require_private(pid)
    public = _stored(pid, "entry", "slug")
    tags = _stored(pid, "tag", "slug")
    packages, checklists = _installed(pid)
    out = []
    for t in public:
        installed = (t.get("package_name") in packages) or (t.get("slug") in checklists)
        out.append({**t, "aisc_local": False, "aisc_installed": bool(installed)})
    by_slug = {t["slug"]: t for t in tags}
    dims = _local_dimensions(pid)
    slug_of = {rid: slug for rid, _, slug in evidence.DIMENSIONS}
    for n, p in enumerate(_local_packages(pid, token, {t.get("package_name") for t in public})):
        name = p["package_name"]
        entry_tags = [_local_tag(tags)] + ([by_slug["test"]] if "test" in by_slug else [])
        entry_tags += [by_slug[slug_of[rid]] for rid in dims.get(name, []) if slug_of[rid] in by_slug]
        entry = {k: None for k in TOOL_KEYS}
        entry.update(id=LOCAL_ID_BASE + 1 + n, slug=f"local-{name}", name=name, package_name=name,
                     version=p.get("version"), description="A plugin of this stack, not in the public catalogue.",
                     status="approved", storage_path=f"local/{name}", available_on_devpi=p.get("source") == "registry",
                     metadata=None, metrics=[], questions=[], tags=entry_tags)
        out.append({**entry, "aisc_local": True, "aisc_installed": name in packages})
    if not detailed:
        out = [{**plain_tool(t)} for t in out]
    return out


def tags(pid) -> list[dict]:
    _require_private(pid)
    stored = _stored(pid, "tag", "slug")
    return stored + [_local_tag(stored)]


def metrics(pid) -> list[dict]:
    _require_private(pid)
    return _stored(pid, "metric", "id")


def metadata(pid) -> list[dict]:
    _require_private(pid)
    return _stored(pid, "metadata", "id")


def project_dimensions(pid) -> list[str]:
    """P3.3: the catalogue's dimension tag slugs of the project's selected control objectives (the latest
    card version that has a selection), in R order."""
    versions = evidence.versions(pid)
    selected, own = [], {}
    for v in versions:
        found = evidence.choices(pid, v["pid"])
        if found.selected:
            selected, own = found.selected, {oid: dim for oid, (_, dim) in found.own.items()}
            break
    dims = {**evidence.objective_dimensions(), **own}
    rids = {dims.get(o) for o in selected} - {None}
    slug_of = {rid: slug for rid, _, slug in evidence.DIMENSIONS}
    return [slug_of[rid] for rid in R_IDS if rid in rids]


# ── P4 local plugins ────────────────────────────────────────────────────────

def set_local_dimensions(pid, package: str, dimensions: list[str]) -> list[str]:
    """P4.2: an admin gives a local entry its dimensions (R1..R11), replacing what it had."""
    if not all(d in R_IDS for d in dimensions):
        raise InvalidDimensions("dimensions are R1 to R11")
    _require_private(pid)
    with _connect(pid) as conn, conn.transaction():
        conn.execute("DELETE FROM catalogue.local_dimension WHERE package_name = %s", (package,))
        for d in sorted(set(dimensions)):
            conn.execute("INSERT INTO catalogue.local_dimension (package_name, dimension) VALUES (%s, %s)",
                         (package, d))
    return sorted(set(dimensions), key=lambda rid: int(rid[1:]))
