"""A project's catalogue, public or private, chosen once (docs/superpowers/local-catalogue-2026-10-03/01-specs.md).

Nothing exists until the project chooses (D2): the choice creates schema `catalogue` in the project's
own database, as platform_rw, holding the mode; a private choice also creates the copy's tables and
fills them from the public catalogue, all in one transaction, so a failure leaves nothing (P1.3). The
choice is final (D1).

The copy holds the public catalogue's own JSON (its `GET /tool/?detailed=true`, `/tags/`, `/metric/`,
`/metadata/`), so the catalogue frontend reads it unchanged (P3). Local entries are not stored: they
are the packages the engine offers (`GET /api/v1/plugins`) whose package is in no public entry (P4),
read on every request; only the dimensions an admin gives them are kept. Local controls are stored: the
checklists in LOCAL_CONTROLS_DIR (the repo's local_controls/, in the public catalogue's seed format) are
written into the copy, as origin 'local', each time it is made or updated; a public entry with the same slug
wins.

A public project reads the same shapes from the public catalogue live, kept LIVE_TTL_S seconds, with
no local entries (docs/superpowers/control-install-2026-10-04/01-plan.md D1, D5). Either way a
control is also served as the checklist package the controls app installs (`control_package`).
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request

import httpx
from packaging.version import InvalidVersion, Version

import psycopg
from psycopg import errors
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from platform_service import db, engine_components, evidence, projectdb
from platform_service.local_controls import LOCAL_CONTROLS_DIR, local_controls  # noqa: F401

logger = logging.getLogger(__name__)
MODES = ("public", "private")
TIMEOUT_S = 20
#: REQ1..REQ11, as the control objectives name a dimension
R_IDS = tuple(rid for rid, _, _ in evidence.DIMENSIONS)
#: the keys of a public `GET /tool/?detailed=true` entry; a plain `GET /tool/` entry lacks the last four
_DETAIL_ONLY = ("metadata", "metrics", "questions", "tags")
TOOL_KEYS = ("available_on_devpi", "completion_status", "created_at", "description", "id", "licensing",
             "name", "package_name", "reviewed_at", "reviewed_by", "slug", "status", "storage_path",
             "submitted_by", "version") + _DETAIL_ONLY
#: local entries' ids, out of the public catalogue's range
LOCAL_ID_BASE = 1_000_000
#: local controls' ids, out of the local plugins' range
LOCAL_CONTROL_ID_BASE = 2_000_000
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
    dimension    text NOT NULL CHECK (dimension ~ '^REQ([1-9]|1[01])$'),
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


class NotChosen(NotPrivate):
    """The project has not chosen its catalogue yet, so it has none to read."""


class InvalidDimensions(ValueError):
    """Not REQ1..REQ11."""


class NoEntry(LookupError):
    """No entry with that id or slug in the project's catalogue."""


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


def _public_base() -> str:
    base = (os.environ.get("CATALOGUE_URL") or "").rstrip("/")
    if not base:
        raise PublicUnavailable("CATALOGUE_URL is not set")
    return base


def fetch_public() -> dict:
    """The public catalogue's four reads: {"tools" (detailed), "tags", "metric", "metadata"}."""
    base = _public_base()
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
    # local controls first, so a public entry that took a local one's slug is inserted as public
    conn.execute("DELETE FROM catalogue.entry WHERE origin = 'local'")
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
    # local controls: rewritten from the folder every time; a public entry with the same slug wins
    local = [c for c in local_controls() if c["slug"] not in wanted]
    for n, c in enumerate(local):
        conn.execute("INSERT INTO catalogue.entry (slug, origin, data) VALUES (%s, 'local', %s)",
                     (c["slug"], Jsonb(local_control_entry(c, public["tags"], n))))
    counts["local_controls"] = len(local)
    for table, rows, key in (("tag", public["tags"], "slug"), ("metric", public["metric"], "id"),
                             ("metadata", public["metadata"], "id")):
        conn.execute(f"DELETE FROM catalogue.{table}")
        for row in rows:
            conn.execute(f"INSERT INTO catalogue.{table} ({key}, data) VALUES (%s, %s)", (row[key], Jsonb(row)))
    conn.execute("INSERT INTO catalogue.state (id, updated_at) VALUES (1, now())"
                 " ON CONFLICT (id) DO UPDATE SET updated_at = now()")
    return counts


def local_control_entry(control: dict, tags: list[dict], n: int) -> dict:
    """A local control as a detailed catalogue entry: the copy's own tags for its type, licence, dimension and
    sub-dimensions (one the copy lacks is left out), and Local as its source."""
    by_slug = {t["slug"]: t for t in tags}
    wanted = ["control", "open", control.get("dimension_slug"), *(control.get("controls_subdim_slugs") or [])]
    entry_id = LOCAL_CONTROL_ID_BASE + n
    md = control.get("metadata") or {}
    entry = {k: None for k in TOOL_KEYS}
    entry.update(
        id=entry_id, slug=control["slug"], name=control["name"], description=control.get("description"),
        version="1.0.0", licensing=control.get("licensing") or "Open_Source", status="approved",
        completion_status=control.get("completion_status") or "full", submitted_by="local",
        storage_path=f"local/controls/{control['slug']}", available_on_devpi=False, metrics=[],
        tags=[_local_tag(tags)] + [by_slug[s] for s in dict.fromkeys(wanted) if s in by_slug],
        metadata={**md, "id": entry_id, "description": control.get("description"), "tool_1_id": entry_id},
        questions=[{"order": q.get("order") or 0, "text": q.get("text") or "", "article": q.get("article"),
                    "category": q.get("category")} for q in control["questions"]],
    )
    return entry


def _live_local_controls(public: list[dict], tags: list[dict]) -> list[dict]:
    """A public project's local controls: the folder's, as catalogue entries, less any slug the public
    catalogue has (it wins, as in a private copy)."""
    taken = {t.get("slug") for t in public}
    return [local_control_entry(c, tags, n)
            for n, c in enumerate(c for c in local_controls() if c["slug"] not in taken)]


def _require_private(pid) -> None:
    found = mode(pid)
    if found is None or found["mode"] != "private":
        raise NotPrivate("this project has no private catalogue")


def _chosen(pid) -> str:
    """"public" or "private"; NotChosen when the project has no catalogue yet."""
    found = mode(pid)
    if found is None:
        raise NotChosen("this project has not chosen its catalogue yet: open it from the project page")
    return found["mode"]


#: how long a public project keeps what it read from the public catalogue, in seconds
LIVE_TTL_S = float(os.environ.get("CATALOGUE_LIVE_TTL_S", "60"))
_live_cache: dict[tuple[str, str], tuple[float, object]] = {}
_live_lock = threading.Lock()


def _live(path: str):
    """One of the public catalogue's reads, for a public project: fetched, then kept LIVE_TTL_S."""
    base = _public_base()
    key, now = (base, path), time.monotonic()
    with _live_lock:
        hit = _live_cache.get(key)
        if hit and now - hit[0] < LIVE_TTL_S:
            return copy.deepcopy(hit[1])
    try:
        found = _get(base, path)
    except (OSError, ValueError) as exc:
        raise PublicUnavailable(f"the public catalogue did not answer: {exc}") from None
    if not isinstance(found, list):
        raise PublicUnavailable("the public catalogue answered something that is not a list")
    with _live_lock:
        _live_cache[key] = (now, found)
    return copy.deepcopy(found)


def _read(pid, table: str, order: str, path: str) -> list[dict]:
    """A catalogue read: from the copy for a private project, live for a public one."""
    return _stored(pid, table, order) if _chosen(pid) == "private" else _live(path)


def update(pid, token: str) -> dict:
    """P2.2: refresh the copy from the public catalogue; the public one not answering changes nothing."""
    _require_private(pid)
    public = fetch_public()
    with _connect(pid) as conn, conn.transaction():
        counts = _store(conn, public)
    counts["local_kept"] = len(_local_packages(pid, token, {package_of(t) for t in public["tools"]}))
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


def _local_control_slugs(pid) -> set[str]:
    with _connect(pid) as conn:
        return {r["slug"] for r in conn.execute("SELECT slug FROM catalogue.entry WHERE origin = 'local'").fetchall()}


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
    return {k: sorted(v, key=lambda rid: int(rid[3:])) for k, v in found.items()}


def tools(pid, token: str, detailed: bool) -> list[dict]:
    """P3.1, P3.2, P4.1: the copy's entries then the local ones, each with aisc_local and aisc_installed;
    a public project's entries are the public catalogue's, live, with no local plugins (D5) but with the
    local controls (local_controls/)."""
    private = _chosen(pid) == "private"
    public = _read(pid, "entry", "slug", "/tool/?detailed=true")
    tags = _read(pid, "tag", "slug", "/tags/")
    packages, checklists = _installed(pid)
    held = packages_on_index()
    local_controls_here = _local_control_slugs(pid) if private else set()
    out = []
    for t in public:
        installed = (package_of(t) in packages) or (t.get("slug") in checklists)
        entry = {**t, "aisc_local": t.get("slug") in local_controls_here, "aisc_installed": bool(installed)}
        # completion_status is what colours a test's card and what Plugin available keeps: in a private
        # copy it says whether the test can be installed on this stack (blue) or not (pink).
        if held is not None and not _is_control(t):
            entry["completion_status"] = "full" if _dist(package_of(t)) in held else "stub"
        out.append(entry)
    if not private:
        # a public project gets the local controls too, live from the folder (no copy to store them in)
        for entry in _live_local_controls(public, tags):
            out.append({**entry, "aisc_local": True, "aisc_installed": entry["slug"] in checklists})
        return out if detailed else [{**plain_tool(t)} for t in out]
    by_slug = {t["slug"]: t for t in tags}
    dims = _local_dimensions(pid)
    slug_of = {rid: slug for rid, _, slug in evidence.DIMENSIONS}
    for n, p in enumerate(_local_packages(pid, token, {package_of(t) for t in public})):
        name = p["package_name"]
        entry_tags = [_local_tag(tags)] + ([by_slug["test"]] if "test" in by_slug else [])
        entry_tags += [by_slug[slug_of[rid]] for rid in dims.get(name, []) if slug_of[rid] in by_slug]
        entry = {k: None for k in TOOL_KEYS}
        entry.update(id=LOCAL_ID_BASE + 1 + n, slug=f"local-{name}", name=name, package_name=name,
                     version=p.get("version"), description="A plugin of this stack, not in the public catalogue.",
                     # the engine can install it, so it is ready ("full": blue, kept by "Plugin available")
                     status="approved", completion_status="full", storage_path=f"local/{name}",
                     available_on_devpi=p.get("source") == "registry",
                     metadata=None, metrics=[], questions=[], tags=entry_tags)
        out.append({**entry, "aisc_local": True, "aisc_installed": name in packages})
    if not detailed:
        out = [{**plain_tool(t)} for t in out]
    return out


def tool_tags(pid, tool_id: int, token: str) -> list[dict]:
    """The tags of one entry, public or local, by its id (the public catalogue's `GET /tool/{id}/tags/`)."""
    for t in tools(pid, token, detailed=True):
        if t["id"] == tool_id:
            return t["tags"] or []
    raise NoEntry(f"no entry {tool_id}")


# ── install-info, from this stack's own package index ───────────────────────
# The public catalogue answers `GET /tool/{slug}/install-info` against its own index; a private copy
# answers it against the index the engine installs from (PACKAGE_REGISTRY_URL), so every plugin this
# stack has is installable and none it lacks is offered. The rules are the public catalogue's
# (apps/catalogue/backend/catalogue_bridge.py): the package from the entry, the version from the index.

#: the files an index serves for a release: an sdist or a wheel
_ARTEFACT = r"\.(?:tar\.gz|whl|zip)"


def index_url() -> str:
    base = os.environ.get("PACKAGE_REGISTRY_URL", "http://devpi:3141").rstrip("/")
    return f"{base}/{os.environ.get('PACKAGE_REGISTRY_INDEX', 'root/public').strip('/')}/+simple/"


def _dist(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


#: Public entries that name a package other than the one their lux-ai-factory repo publishes
#: (public catalogue data of 2026-10-04: package_name empty, storage_path /packages/<slug>). Without
#: this the rich entry can't be installed and the published package shows again as a bare Local
#: entry. Drop a line once the public catalogue names the published package itself.
PUBLISHED_AS = {
    "agentdojo": "aisc-plugin-agentdojo",
    "promptfoo": "aisc-plugin-promptfoo",
    "ragas": "aisc-plugin-ragas",
}


def package_of(entry: dict) -> str:
    """The distribution an entry is published as: PUBLISHED_AS, else its package_name, else the last
    part of its storage_path ("/packages/<name>"), else its slug."""
    if entry.get("slug") in PUBLISHED_AS:
        return PUBLISHED_AS[entry["slug"]]
    if entry.get("package_name"):
        return entry["package_name"]
    tail = (entry.get("storage_path") or "").strip().strip("/").rsplit("/", 1)[-1]
    return tail or entry["slug"]


def versions_on_index(package: str) -> list[str]:
    """The versions the index serves for that distribution; none when it can't be reached."""
    try:
        r = httpx.get(f"{index_url()}{package}/", timeout=TIMEOUT_S, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.warning("package index not reachable for %s: %s", package, exc)
        return []
    if r.status_code >= 400:
        return []
    found, wanted = set(), _dist(package)
    for filename in re.findall(rf">\s*([^<>\s]+?{_ARTEFACT})\s*<", r.text):
        parts = re.sub(rf"{_ARTEFACT}$", "", filename).split("-")
        # wheels are name-version-python-abi-platform, sdists name-version
        for at in range(len(parts) - 1, 0, -1):
            if _dist("-".join(parts[:at])) == wanted:
                found.add(parts[at])
                break
    return sorted(found)


def packages_on_index() -> set[str] | None:
    """The (normalised) names of every package the index holds, from its root page; None when it
    can't be reached, so that nothing is decided on no information."""
    try:
        r = httpx.get(index_url(), timeout=TIMEOUT_S, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.warning("package index not reachable: %s", exc)
        return None
    if r.status_code >= 400:
        logger.warning("package index answered %s", r.status_code)
        return None
    return {_dist(name) for name in re.findall(r"<a\b[^>]*>\s*([^<\s]+)\s*</a>", r.text)}


def _is_control(entry: dict) -> bool:
    """As the catalogue frontend decides: a control or framework type tag, or a questionnaire."""
    types = {t.get("slug") for t in entry.get("tags") or [] if t.get("section") == "type"}
    return bool(types & {"control", "framework"}) or bool(entry.get("questions"))


def newest(versions: list[str]) -> str | None:
    """The newest release; a pre-release only when there is nothing else."""
    parsed = []
    for raw in versions:
        try:
            parsed.append((Version(raw), raw))
        except InvalidVersion:
            continue
    if not parsed:
        return None
    finals = [p for p in parsed if not p[0].is_prerelease]
    return max(finals or parsed)[1]


def install_info(pid, slug: str, token: str) -> dict:
    """The public catalogue's InstallInfo for one entry, answered from this stack's index."""
    entry = next((t for t in tools(pid, token, detailed=True) if t["slug"] == slug), None)
    if entry is None:
        raise NoEntry(f"no entry {slug!r}")
    package = package_of(entry)
    version = newest(versions_on_index(package))
    return {"slug": slug, "package_name": package, "version": version, "index_url": index_url(),
            "installable": version is not None,
            "reason": None if version else f"{package} is not on this stack's package index"}


def tags(pid) -> list[dict]:
    if _chosen(pid) == "public":
        return _live("/tags/")                    # no local entries, so no "Local" source
    stored = _stored(pid, "tag", "slug")
    return stored + [_local_tag(stored)]


def metrics(pid) -> list[dict]:
    return _read(pid, "metric", "id", "/metric/")


def metadata(pid) -> list[dict]:
    return _read(pid, "metadata", "id", "/metadata/")


# ── a control as the checklist package the controls app installs ────────────
# The public catalogue's rules (apps/catalogue/backend/controls_export.py), over the detailed JSON a
# copy holds; tests/test_catalogue_controls.py holds them to its exports.

def is_export_control(entry: dict) -> bool:
    """As the public catalogue's export decides: the entry carries the 'control' tag."""
    return any(t.get("slug") == "control" for t in entry.get("tags") or [])


def checklist_package(entry: dict) -> dict:
    """{"meta", "questions"}: the package `GET /control/{slug}/export` gives for this entry."""
    md = entry.get("metadata") or {}
    questions = sorted(entry.get("questions") or [], key=lambda q: q.get("order") or 0)
    regulation_ids = list(md.get("regulation_ids") or [])
    if not regulation_ids and any((q.get("article") or "").strip() for q in questions):
        regulation_ids = ["ai-act"]               # article references imply the EU AI Act
    return {
        "meta": {
            "catalogueId": entry["slug"],
            "title": entry.get("name"),
            "sourceName": (md.get("provider") or "").strip() or "Unknown",
            "sourceUrl": md.get("link") or None,
            "controlTopic": (md.get("control_topic") or "").strip() or entry.get("name"),
            "description": entry.get("description") or None,
            "countryIds": list(md.get("country_ids") or []),
            "regulationIds": regulation_ids,
            # the copy holds the public JSON, where this date is already an ISO string
            "sourceUpdatedAt": md.get("source_updated_at") or None,
        },
        "questions": [{"text": q.get("text"), "article": q.get("article"), "category": q.get("category")}
                      for q in questions],
    }


def control_package(pid, slug: str) -> dict:
    """The checklist package of one control of the project's catalogue: built from the copy for a private
    project, the public catalogue's own export for a public one (a local control: built from the folder). NoEntry when it is not a control there."""
    if _chosen(pid) == "private":
        entry = next((t for t in _stored(pid, "entry", "slug") if t.get("slug") == slug), None)
        if entry is None or not is_export_control(entry):
            raise NoEntry(f"this project's catalogue has no control {slug!r}")
        return checklist_package(entry)
    if any(c["slug"] == slug for c in local_controls()):
        found = next((t for t in _live_local_controls(_live("/tool/?detailed=true"), _live("/tags/"))
                      if t["slug"] == slug), None)
        if found is not None:
            return checklist_package(found)
    request = urllib.request.Request(f"{_public_base()}/control/{urllib.request.quote(slug, safe='')}/export")
    token = os.environ.get("CATALOGUE_TOKEN") or ""
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as res:
            found = json.loads(res.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise NoEntry(f"the public catalogue has no control {slug!r}") from None
        raise PublicUnavailable(f"the public catalogue answered {exc.code} for {slug!r}") from None
    except (OSError, ValueError) as exc:
        raise PublicUnavailable(f"the public catalogue did not answer: {exc}") from None
    if not isinstance(found, dict) or "meta" not in found:
        raise PublicUnavailable("the public catalogue answered something that is not a checklist package")
    return found


def project_dimensions(pid) -> list[str]:
    """P3.3: the catalogue's dimension tag slugs of the project's selected control objectives (the latest
    card version that has a selection), in REQ order."""
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
    """P4.2: an admin gives a local entry its dimensions (REQ1..REQ11), replacing what it had."""
    if not all(d in R_IDS for d in dimensions):
        raise InvalidDimensions("dimensions are REQ1 to REQ11")
    _require_private(pid)
    with _connect(pid) as conn, conn.transaction():
        conn.execute("DELETE FROM catalogue.local_dimension WHERE package_name = %s", (package,))
        for d in sorted(set(dimensions)):
            conn.execute("INSERT INTO catalogue.local_dimension (package_name, dimension) VALUES (%s, %s)",
                         (package, d))
    return sorted(set(dimensions), key=lambda rid: int(rid[3:]))


if __name__ == "__main__":
    # scripts/start.sh: the local controls every project catalogue will get, one slug a line
    # (what cannot be read is logged to stderr)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    for c in local_controls():
        print(c["slug"])
