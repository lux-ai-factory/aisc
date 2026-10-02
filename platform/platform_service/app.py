"""The platform API: the projects every module comes to reference.

Authentication is the gateway's job and is checked again here, because the
gateway's word is one hop away from a mistake. Authorisation is this service's
job, and it is the whole of it: a project belongs to the people in it, and
every endpoint that returns a project, or anything inside one, goes through the
same two questions. Is this person in it, and are they enough for this.

A stranger is answered 404 rather than 403. The slug of a project is its name,
often the name of a customer, and 403 would confirm it exists.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import uuid
import logging
import os
import secrets
import unicodedata
from urllib.parse import parse_qs, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from psycopg import errors
from pydantic import BaseModel, ConfigDict, StrictStr

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency, requires_role
from aisc_identity.headers import token_from_headers

from platform_service import (connection_allowlist, connection_facade, connection_store, target_store, targets, dashboard_bridge, db, evidence, llm_catalogue, llm_store,
                              projectdb)
from platform_service.membership import (
    InvalidMembership,
    at_least,
    may_manage_members,
    may_write,
    validate_role,
)
from platform_service.projects import InvalidProject, looks_like_pid, normalise_name, slug_for, validate_slug
from platform_service.systems import InvalidSystem, system_key

logger = logging.getLogger(__name__)

app = FastAPI(title="AISC platform", docs_url="/docs")

#: What the ledger's defence in depth checks (spec 5.3): every write, but not the internal and authz routes,
#: which carry service tokens or are Caddy's own.
_LEDGER_WRITES = {"POST", "PUT", "PATCH", "DELETE"}
_LEDGER_EXEMPT = ("/internal/", "/authz/", "/docs", "/openapi.json")


def _ledger_presented(request: Request, request_id: str | None) -> str | None:
    """Why this write may not go on in `enforce`, or None. The request id must be one the witness gave,
    for a verified person who is this caller; through the gateway directly, for this method and path."""
    from aisc_identity.service import NotAuthenticated, caller_from_headers

    from platform_service.ledger import actors, witness as ledger_witness

    if not request_id:
        return "a write needs the request the gateway witnessed (X-AISC-Request-Id)"
    rec = ledger_witness.record(request_id)
    if rec is None or not rec.verified:
        return "unknown or unverified request id"
    try:
        caller = caller_from_headers(request.headers)
    except NotAuthenticated:
        return None                                                   # the route answers 401 itself
    try:
        who = actors.resolve(rec.project_pid, rec.actor_ref)
    except actors.MappingAlarm:
        return "the request's person can't be checked"
    if who is None or who[0] != caller.subject:
        return "this request id was witnessed for someone else"
    if rec.app == "platform" and (rec.method != request.method or rec.route_path != "/api" + request.url.path):
        return "this request id was witnessed for another request"
    return None


@app.middleware("http")
async def ledger_request(request: Request, call_next):
    """The witnessed request this one is (X-AISC-Request-Id), for the platform's own events; in `enforce`,
    a write without a matching one is refused (spec 5.3, R1.5)."""
    from starlette.concurrency import run_in_threadpool

    from platform_service.ledger import outbox, witness as ledger_witness

    request_id = request.headers.get("x-aisc-request-id") or None
    token = outbox.current_request.set(request_id)
    try:
        if (request.method in _LEDGER_WRITES and not request.url.path.startswith(_LEDGER_EXEMPT)
                and ledger_witness.mode() == "enforce"):
            problem = await run_in_threadpool(_ledger_presented, request, request_id)
            if problem:
                return JSONResponse({"detail": problem}, status_code=401)
        return await call_next(request)
    finally:
        outbox.current_request.reset(token)

#: The realm role that administers the platform. It is not a membership: an
#: admin is not in the project, it may act on any of them, which is what makes
#: an orphaned project recoverable.
ADMIN_ROLE = "admin"


def no_project(identifier: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"no project {identifier!r}")


def effective_role(project: str, caller: Caller) -> str | None:
    """What this caller is to this project, counting the admin role."""
    if caller.has_role(ADMIN_ROLE):
        return "owner"
    return db.role_in_project(project, caller.subject)


def role_or_404(project: str, caller: Caller, needed: str = "viewer") -> str:
    """The caller's role, or the answer a stranger gets.

    404 for "not yours" and 403 for "not enough": a member is told they lack
    the rank, a non-member is told nothing at all.
    """
    role = effective_role(project, caller)
    if not at_least(role, "viewer"):
        raise no_project(project)
    if not at_least(role, needed):
        raise HTTPException(status_code=403, detail=f"this takes {needed} on this project")
    return role


def owner_or_403(project: str, caller: Caller) -> None:
    """Only an owner decides who is in a project."""
    if not may_manage_members(role_or_404(project, caller)):
        raise HTTPException(status_code=403, detail="only an owner decides who is in a project")


def refuse_losing_last_owner(project: str, subject: str) -> None:
    """A project with nobody in it is a project nobody can open, and the last
    owner leaving is the only way to make one."""
    if db.role_in_project(project, subject) == "owner" and db.owner_count(project) <= 1:
        raise HTTPException(status_code=409, detail="a project keeps at least one owner")


class ProjectIn(BaseModel):
    name: str
    slug: str | None = None
    description: str | None = None


class DeleteProjectIn(BaseModel):
    confirm_name: str


class MemberIn(BaseModel):
    subject: str
    email: str | None = None
    role: str = "viewer"


class MemberRoleIn(BaseModel):
    role: str


class SystemIn(BaseModel):
    name: str
    version: str | None = None
    provider: str | None = None
    description: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/projects")
def projects(caller: Caller = Depends(caller_dependency)) -> list[dict]:
    if caller.has_role(ADMIN_ROLE):
        return db.list_projects()
    return db.projects_for(caller.subject)


@app.get("/projects/{slug}")
def project(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found


@app.post("/projects", status_code=201)
def add_project(body: ProjectIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """Anybody signed in may start an assessment, and owns the one they start."""
    name = normalise_name(body.name)
    slug = validate_slug(body.slug) if body.slug else slug_for(name)
    try:
        created = db.create_project(name, slug, body.description, caller.subject, caller.email)
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"a project {slug!r} already exists")
    provision_or_undo(created["pid"])
    # every evaluation names a target: the system's exists from the start (targets plan v2);
    # its engine mirror follows on the first pass that has a caller's token and an engine project
    try:
        targets.ensure_system(created["pid"], created["name"])
    except Exception:
        # never a reason to refuse the project: the targets list, every sync and the engine's
        # evaluation form ensure it again
        logger.exception("the system target of project %s was not made at creation", created["pid"])
    if not dashboard_bridge.register(created["pid"], created["slug"], created["name"]):
        db.remember_unregistered(created["pid"])
    return created


def provision_or_undo(pid) -> None:
    """Make the project's database, or remove the project again.

    A project without its database is one every module fails on. CREATE
    DATABASE may have succeeded before the template step failed, so the
    database is dropped too; a failing drop is logged and does not mask the 503.
    """
    try:
        projectdb.provision(db.dsn(), pid)
    except Exception:
        db.delete_project(pid)
        try:
            projectdb.drop(db.dsn(), pid)
        except Exception:
            logger.exception("could not drop the half-made database of project %s; drop it by hand", pid)
        raise HTTPException(status_code=503, detail="the project's database could not be made; nothing was created")


@app.delete("/projects/{slug}", status_code=204)
def remove_project(slug: str, body: DeleteProjectIn, caller: Caller = Depends(caller_dependency)) -> None:
    """Delete a project and everything every module holds for it.

    Only an admin, and only by typing the project's name exactly: this drops the
    project's database, and there is no undo. The database goes first, so a
    failure halfway leaves a project with no data rather than data with no
    project.
    """
    if not caller.has_role(ADMIN_ROLE):
        role_or_404(slug, caller)  # a stranger is told nothing
        raise HTTPException(status_code=403, detail="only an admin deletes a project")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    if body.confirm_name != found["name"]:
        raise HTTPException(status_code=422, detail="type the project's name exactly to delete it")
    _ledger_drain_or_refuse(found["pid"])
    # The dashboard lets go of the project's database before it is dropped.
    dashboard_bridge.unregister(found["pid"])
    projectdb.drop(db.dsn(), found["pid"])
    db.delete_project(found["pid"])


def _ledger_drain_or_refuse(pid) -> None:
    """Before a project database is dropped, its outbox must be in the log: the drop would destroy what
    hasn't been delivered (spec 6.4, R2.4). Platform-database rows (members, this delete's own event)
    don't block: they outlive the drop."""
    from platform_service.ledger import relay, witness as ledger_witness
    from platform_service.ledger.store import LedgerError

    if ledger_witness.mode() == "off":
        return
    try:
        relay.relay_once(str(pid))
    except LedgerError:
        pass                                                          # counted below
    try:
        with projectdb_connection(pid) as conn:
            left = conn.execute("SELECT count(*) AS n FROM ledger.outbox o LEFT JOIN ledger.delivered d"
                                " ON d.event_id = o.event_id WHERE d.event_id IS NULL").fetchone()["n"]
    except Exception:
        left = 0                                                      # no project database: nothing to lose
    if left:
        raise HTTPException(status_code=409, detail=f"the log still has {left} undelivered events: try again soon")


def projectdb_connection(pid):
    import psycopg
    from psycopg.conninfo import make_conninfo
    from psycopg.rows import dict_row

    return psycopg.connect(make_conninfo(db.dsn(), dbname=projectdb.database_name(pid)), row_factory=dict_row)


# ── who is in a project ──────────────────────────────────────────────────────


@app.get("/authz/projects/{slug}")
def authorisation(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """What this caller may do here.

    The one endpoint that answers for strangers too, because it is what the
    other modules ask before deciding what to show, and "nothing" is an answer
    they need rather than an error they have to interpret.
    """
    role = effective_role(slug, caller)
    return {
        "role": role,
        "admin": caller.has_role(ADMIN_ROLE),
        "may_write": may_write(role),
    }


@app.get("/authz/witness")
def ledger_witness(request: Request) -> Response:
    """The ledger's witness, for Caddy's forward_auth (docs/superpowers/ledger-2026-10-02/02-spec.md 3).
    Never served to a browser: the launcher answers 404 to /api/authz/*, and a call without the
    gateway secret gets 401. Off unless LEDGER_MODE says otherwise."""
    from platform_service.ledger.witness import witness

    answer = witness(request.headers)
    return Response(status_code=answer.status, headers=answer.headers)


@app.get("/authz/admin", status_code=204)
def admin_gate(caller: Caller = Depends(requires_role(ADMIN_ROLE))) -> Response:
    """Whether this caller is an admin, for Caddy to ask with forward_auth.

    The database tools on the launcher see every project's database, so they
    are behind this rather than behind a membership: 204 lets the request
    through, 403 does not.
    """
    return Response(status_code=204)


#: What /inspect/schema serves: the landing page, the shared database and project databases.
SCHEMA_DATABASE = re.compile(r"^(platform|project_([0-9a-f]{32}))$")


@app.get("/authz/schema", status_code=204)
def schema_gate(request: Request, caller: Caller = Depends(caller_dependency)) -> Response:
    """Whether this caller may see the database diagrams Caddy was asked for.

    The diagrams show structure, never rows, so they are for project members, not only
    admins: the landing page and the shared platform's diagrams to anyone signed in, a
    project's own database to its members. Only an admin may force a new SchemaSpy run
    (?refresh=1). Caddy passes the path in X-Forwarded-Uri, with or without the
    /inspect/schema prefix it strips."""
    parts = urlsplit(request.headers.get("x-forwarded-uri", "/"))
    path = parts.path.removeprefix("/inspect/schema")
    admin = caller.has_role(ADMIN_ROLE)
    refused = HTTPException(status_code=403, detail="these diagrams are not yours to see")
    if "refresh" in parse_qs(parts.query) and not admin:
        raise refused
    segments = [s for s in path.split("/") if s]
    if not segments:
        return Response(status_code=204)
    if ".." in segments:
        raise refused
    found = SCHEMA_DATABASE.fullmatch(segments[0])
    if found is None:
        raise refused
    if found.group(2) is None:
        return Response(status_code=204)
    pid = str(uuid.UUID(found.group(2)))
    if db.get_project(pid) is None:
        raise refused
    if not admin and effective_role(pid, caller) is None:
        raise refused
    return Response(status_code=204)


@app.get("/projects/{slug}/members")
def project_members(slug: str, caller: Caller = Depends(caller_dependency)) -> list[dict]:
    role_or_404(slug, caller)
    return db.members(slug)


@app.post("/projects/{slug}/members", status_code=201)
def add_project_member(
    slug: str, body: MemberIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    owner_or_403(slug, caller)
    added = db.add_member(slug, body.subject, body.email, validate_role(body.role))
    if added is None:
        raise no_project(slug)
    return added


@app.put("/projects/{slug}/members/{subject}")
def set_project_member_role(
    slug: str, subject: str, body: MemberRoleIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    owner_or_403(slug, caller)
    wanted = validate_role(body.role)
    if wanted != "owner":
        refuse_losing_last_owner(slug, subject)
    changed = db.add_member(slug, subject, None, wanted)
    if changed is None:
        raise no_project(slug)
    return changed


@app.delete("/projects/{slug}/members/{subject}", status_code=204)
def remove_project_member(
    slug: str, subject: str, caller: Caller = Depends(caller_dependency)
) -> None:
    owner_or_403(slug, caller)
    refuse_losing_last_owner(slug, subject)
    if not db.remove_member(slug, subject):
        raise HTTPException(status_code=404, detail=f"{subject!r} is not in {slug!r}")


@app.post("/projects/{project}/system-versions", status_code=201)
def create_system_version(
    project: str, body: SystemIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    """Save the AI card's next version: numbered 1, 2, ... per project, even
    when name and version repeat. Saving is changing the work: an editor."""
    role_or_404(project, caller, needed="editor")
    name, version = system_key(body.name, body.version)
    try:
        made = db.create_version(project, name, version, body.provider, body.description,
                                 caller.subject)
    except db.ProjectDatabaseGone:
        raise no_project(project) from None
    if made is None:
        raise no_project(project)
    return made


@app.get("/projects/{project}/system-versions")
def system_versions(project: str, caller: Caller = Depends(caller_dependency)) -> list[dict]:
    """Every saved card version, highest number first."""
    role_or_404(project, caller)
    try:
        found = db.list_versions(project)
    except db.ProjectDatabaseGone:
        raise no_project(project) from None
    if found is None:
        raise no_project(project)
    return found


@app.get("/projects/{project}/system-versions/latest")
def latest_system_version(project: str, caller: Caller = Depends(caller_dependency)) -> dict | None:
    """The latest saved card version, or null when the project has none yet."""
    role_or_404(project, caller)
    try:
        exists, found = db.latest_version(project)
    except db.ProjectDatabaseGone:
        raise no_project(project) from None
    if not exists:
        raise no_project(project)
    return found


@app.get("/systems/{pid}")
def system(pid: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """A card version by its own id.

    It is looked for only in the databases of the caller's projects (every
    project for an admin): the id alone names no database, and one the caller
    is not in is never opened (I2.3). The project is checked again on the one
    found: an id that skips the project is exactly how a stranger would read one.
    """
    missing = HTTPException(status_code=404, detail=f"no system {pid}")
    if not looks_like_pid(pid):
        raise missing
    if caller.has_role(ADMIN_ROLE):
        project_pids = [str(p["pid"]) for p in db.list_projects()]
    else:
        project_pids = [str(p["pid"]) for p in db.projects_for(caller.subject)]
    found = db.get_system(pid, project_pids)
    if found is None:
        raise missing
    role_or_404(str(found["project_id"]), caller)
    return found


# ── LLM keys and model choices, per project (admin only) ────────────────────
#
# docs/superpowers/pipeline-2026-09-24-llm-keys/01-specs.md section 2. A key is
# write-only: no route below returns it or its ciphertext; only the internal
# resolve route further down hands a decrypted key to the two agents.

NOT_VALID_KEY = "the key is not a valid API key string"
NOT_VALID_BASE_URL = ("the base URL must be http(s)://host[:port][/path], without credentials,"
                      " query or fragment")
NOT_VALID_MODEL = "the model must be 1 to 200 characters, without control characters"


class ProviderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: StrictStr | None = None
    base_url: StrictStr | None = None


class SystemChoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: StrictStr
    model: StrictStr


def admin_project(slug: str, caller: Caller) -> dict:
    """The project, for a platform admin only: a stranger gets 404, a member 403."""
    role_or_404(slug, caller)
    if not caller.has_role(ADMIN_ROLE):
        raise HTTPException(status_code=403, detail="only a platform admin manages models and keys")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found


def catalogue_entry(provider: str):
    entry = llm_catalogue.PROVIDERS.get(provider)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"no provider {provider!r}")
    return entry


def known_system(system: str) -> None:
    if system not in llm_store.SYSTEMS:
        raise HTTPException(status_code=404, detail=f"no system {system!r}")


def _has_control_character(value: str) -> bool:
    return any(unicodedata.category(c).startswith("C") for c in value)


def clean_key(value: str) -> str:
    """The key without surrounding whitespace; the message never contains it."""
    key = value.strip()
    if not 1 <= len(key) <= 4096 or any(c.isspace() for c in key) or _has_control_character(key):
        raise HTTPException(status_code=422, detail=NOT_VALID_KEY)
    return key


def clean_base_url(value: str) -> str | None:
    """http(s)://host[:port][/path]; an empty string clears the stored one (None)."""
    url = value.strip()
    if not url:
        return None
    refused = HTTPException(status_code=422, detail=NOT_VALID_BASE_URL)
    if len(url) > 500 or any(c.isspace() for c in url) or _has_control_character(url):
        raise refused
    if "?" in url or "#" in url:
        raise refused
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc:
        raise refused
    try:
        parts.port
    except ValueError:
        raise refused from None
    return url


def clean_model(value: str) -> str:
    model = value.strip()
    if not 1 <= len(model) <= 200 or _has_control_character(model):
        raise HTTPException(status_code=422, detail=NOT_VALID_MODEL)
    return model


def is_usable(provider: str, row: dict | None) -> bool:
    """A key-required provider needs a key, compatible needs a base URL, ollama always works."""
    entry = llm_catalogue.PROVIDERS[provider]
    if entry.key_required:
        return bool(row and row["has_key"])
    if provider == "ollama":
        return True
    return bool(row and row["base_url"])


def provider_view(provider: str, row: dict | None) -> dict:
    """What the page sees of a provider: never the key, never the ciphertext."""
    entry = llm_catalogue.PROVIDERS[provider]
    base_url = row["base_url"] if row else None
    if base_url is None and provider == "ollama":
        base_url = llm_store.ollama_default()
    return {
        "id": provider,
        "label": entry.label,
        "key_required": entry.key_required,
        "has_key": bool(row and row["has_key"]),
        "base_url": base_url,
        "base_url_editable": entry.base_url_editable,
        "usable": is_usable(provider, row),
        "updated_at": row["updated_at"].isoformat() if row else None,
    }


def secrets_unavailable(exc: llm_store.SecretsKeyError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


@app.get("/projects/{slug}/llm")
def llm_settings(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """Every provider with its state, and each agentic system's choice (null: its environment)."""
    pid = admin_project(slug, caller)["pid"]
    rows = llm_store.providers(pid)
    chosen = llm_store.choices(pid)
    return {
        "providers": [provider_view(p, rows.get(p)) for p in llm_catalogue.PROVIDERS],
        "systems": [{"id": s, "label": label, "choice": chosen.get(s)}
                    for s, label in llm_store.SYSTEMS.items()],
    }


@app.put("/projects/{slug}/llm/providers/{provider}")
def save_llm_provider(slug: str, provider: str, body: ProviderIn,
                      caller: Caller = Depends(caller_dependency)) -> dict:
    """Store (or replace) a provider's key and, for ollama and compatible, its base URL.

    An absent field keeps what is stored. Everything is validated before anything is
    encrypted or written."""
    pid = admin_project(slug, caller)["pid"]
    entry = catalogue_entry(provider)
    sent = {name for name in body.model_fields_set if getattr(body, name) is not None}
    if not sent:
        raise HTTPException(status_code=422, detail="send api_key, base_url or both")
    if "base_url" in sent and not entry.base_url_editable:
        raise HTTPException(status_code=422, detail=f"{entry.label} is called at its own address; it takes no base URL")
    if "api_key" in sent and provider == "ollama":
        raise HTTPException(status_code=422, detail="ollama takes no key")
    key = clean_key(body.api_key) if "api_key" in sent else None
    base_url = clean_base_url(body.base_url) if "base_url" in sent else llm_store.KEEP
    ciphertext = llm_store.KEEP
    if key is not None:
        try:
            ciphertext = llm_store.encrypt(key)
        except llm_store.SecretsKeyError as exc:
            raise secrets_unavailable(exc) from None
    from platform_service.ledger import secrets as ledger_secrets, witness as ledger_witness

    fingerprint = None
    if key is not None and ledger_witness.mode() != "off":
        fingerprint = ledger_secrets.fingerprint(pid, key)            # never the key itself (I8)
    row = llm_store.save_provider(pid, provider, ciphertext=ciphertext, base_url=base_url,
                                  subject=caller.subject, key_fingerprint=fingerprint)
    return provider_view(provider, row)


@app.delete("/projects/{slug}/llm/providers/{provider}", status_code=204)
def remove_llm_provider(slug: str, provider: str, caller: Caller = Depends(caller_dependency)) -> Response:
    """Remove a provider's key and base URL, unless a system still uses it."""
    pid = admin_project(slug, caller)["pid"]
    catalogue_entry(provider)
    outcome = llm_store.delete_provider(pid, provider)
    if isinstance(outcome, list):
        raise HTTPException(status_code=409, detail=(
            f"{provider} is used by {', '.join(outcome)}; choose another provider for it first"))
    if outcome is False:
        raise HTTPException(status_code=404, detail=f"nothing is stored for {provider}")
    return Response(status_code=204)


@app.get("/projects/{slug}/llm/providers/{provider}/models")
def llm_provider_models(slug: str, provider: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """The provider's models, asked live with this project's key: 200 with `error` on failure."""
    pid = admin_project(slug, caller)["pid"]
    entry = catalogue_entry(provider)
    row = llm_store.providers(pid).get(provider)
    if not is_usable(provider, row):
        missing = "key" if entry.key_required else "base URL"
        raise HTTPException(status_code=409, detail=f"{entry.label} has no {missing} in this project")
    key = None
    if row and row["has_key"]:
        try:
            key = llm_store.decrypt(provider, llm_store.ciphertext_of(pid, provider))
        except llm_store.KeyUnreadable as exc:
            return {"models": [], "error": str(exc)}
        except llm_store.SecretsKeyError as exc:
            raise secrets_unavailable(exc) from None
    base_url = None
    if entry.base_url_editable:
        base_url = row["base_url"] if row and row["base_url"] else None
        if base_url is None and provider == "ollama":
            base_url = llm_store.ollama_default()
    return llm_catalogue.list_models(provider, api_key=key, base_url=base_url)


@app.put("/projects/{slug}/llm/systems/{system}")
def save_llm_choice(slug: str, system: str, body: SystemChoiceIn,
                    caller: Caller = Depends(caller_dependency)) -> dict:
    """Choose a usable provider and a model for an agentic system (the model is not
    checked against the live list: decision D6)."""
    pid = admin_project(slug, caller)["pid"]
    known_system(system)
    if body.provider not in llm_catalogue.PROVIDERS:
        raise HTTPException(status_code=422, detail=f"no provider {body.provider!r}")
    if not is_usable(body.provider, llm_store.providers(pid).get(body.provider)):
        raise HTTPException(status_code=422, detail=f"{body.provider} cannot be used in this project yet")
    model = clean_model(body.model)
    llm_store.save_choice(pid, system, body.provider, model, subject=caller.subject,
                          keyless_row=(body.provider == "ollama"))
    return {"system": system, "provider": body.provider, "model": model}


@app.delete("/projects/{slug}/llm/systems/{system}", status_code=204)
def remove_llm_choice(slug: str, system: str, caller: Caller = Depends(caller_dependency)) -> Response:
    """The system goes back to its own environment configuration."""
    pid = admin_project(slug, caller)["pid"]
    known_system(system)
    if not llm_store.delete_choice(pid, system):
        raise HTTPException(status_code=404, detail=f"{system} has no choice to remove")
    return Response(status_code=204)


# ── the internal resolve route, for the two agents only ─────────────────────


def _internal(status: int, body: dict) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})


#: The token each agentic system resolves itself with, by the variable that holds it.
SYSTEM_TOKENS = {"card_agent": "PLATFORM_CARD_AGENT_TOKEN", "risk_mapper": "PLATFORM_RISK_MAPPER_TOKEN"}


def system_tokens() -> dict[str, str]:
    """system -> its token, for the systems whose variable is set (read on every call)."""
    return {system: os.environ[name] for system, name in SYSTEM_TOKENS.items() if os.environ.get(name)}


def system_of_token(given: str, tokens: dict[str, str]) -> str | None:
    """The system this token belongs to, or None. Every token is compared, in constant time."""
    found = None
    for system, expected in tokens.items():
        if hmac.compare_digest(given.encode(), expected.encode()):
            found = system
    return found


@app.get("/internal/projects/{pid}/llm/{system}")
def resolve_llm(pid: str, system: str, request: Request) -> JSONResponse:
    """The system's choice for this project, with its decrypted key.

    Reached on the backend network only: a request that came through Caddy (it
    carries X-Forwarded-*) is 404. Each agentic system has a token of its own
    (SYSTEM_TOKENS), sent in X-AISC-Service-Token, and a token opens only its own
    system: the card agent can never be handed the risk mapper's key, nor the other
    way round (403). With no system token set the route is closed (503)."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return _internal(404, {"detail": "not here"})
    tokens = system_tokens()
    if not tokens:
        return _internal(503, {"detail": "the internal route is closed: no system token is set"})
    if len(set(tokens.values())) < len(tokens):
        # one value for both would be the shared token again, under two names
        return _internal(503, {"detail": "the internal route is closed: the system tokens must differ"})
    caller_system = system_of_token(request.headers.get("x-aisc-service-token", ""), tokens)
    if caller_system is None:
        return _internal(401, {"detail": "a service token is needed"})
    if not looks_like_pid(pid):
        return _internal(422, {"detail": "not a project id"})
    if system not in llm_store.SYSTEMS:
        return _internal(404, {"detail": f"no system {system!r}"})
    if system != caller_system:
        return _internal(403, {"detail": f"this token is {caller_system}'s, not {system}'s"})
    if db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    choice = llm_store.resolve_choice(pid, system)
    if choice is None:
        return _internal(200, {"configured": False})
    provider = choice["provider"]
    entry = llm_catalogue.PROVIDERS.get(provider)
    base_url = choice["base_url"]
    if base_url is None and provider == "ollama":
        base_url = llm_store.ollama_default()
    if provider == "compatible" and not base_url:
        return _internal(409, {"detail": "no base URL is stored for compatible"})
    api_key = None
    if provider != "ollama":
        if choice["ciphertext"] is None:
            if entry is None or entry.key_required:
                return _internal(409, {"detail": f"no key is stored for {provider} in this project"})
        else:
            try:
                api_key = llm_store.decrypt(provider, choice["ciphertext"])
            except llm_store.SecretsKeyError as exc:
                return _internal(503, {"detail": str(exc)})
            except llm_store.KeyUnreadable as exc:
                return _internal(409, {"detail": str(exc)})
    return _internal(200, {"configured": True, "provider": provider, "model": choice["model"],
                           "base_url": base_url, "api_key": api_key})


# ── Manage → Connections (connections plan 2026-09-29) ─────────────────────────
# The systems a project assesses over the network. An admin registers, tests and deletes them;
# the engine sees each as a `resource` component `connection:<pid>/<name>`; the plugin-side
# client (aisc_plugin_interface.connections) resolves one on the internal route below.

CONNECTION_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key"}


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: StrictStr
    kind: StrictStr
    base_url: StrictStr
    method: StrictStr = "POST"
    path: StrictStr = ""
    headers: dict[str, StrictStr] = {}
    secret_header: StrictStr | None = None
    body_template: object | None = None
    response_path: StrictStr | None = None
    refusal: dict | None = None
    model: StrictStr | None = None
    timeout_s: int = 60
    protocol_version: StrictStr | None = None
    secret: StrictStr | None = None
    #: the assessment target this is the endpoint of ('system' or 'component:<key>'); set once
    target: StrictStr | None = None


class ProbeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: StrictStr = "ping"


def _invalid_connection(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def connection_fields(body: ConnectionIn) -> dict:
    """The columns to store, after every check; nothing is written when one fails."""
    label = body.label.strip()
    if not 1 <= len(label) <= 120:
        raise _invalid_connection("label: 1 to 120 characters")
    if body.kind not in ("openai", "rest", "a2a", "oip"):
        raise _invalid_connection("kind: openai, rest, a2a or oip")
    parts = urlsplit(body.base_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _invalid_connection("base_url: an http(s) URL with a host")
    method = body.method.upper()
    if method not in ("GET", "POST", "PUT"):
        raise _invalid_connection("method: GET, POST or PUT")
    for name in body.headers:
        if not _HEADER_NAME.match(name):
            raise _invalid_connection(f"headers: {name!r} is not a header name")
        if name.lower() in _SECRET_HEADERS:
            raise _invalid_connection(f"headers: {name} carries a credential; put it in secret_header")
    if body.secret_header is not None:
        name, sep, value = body.secret_header.partition(":")
        if not sep or not _HEADER_NAME.match(name.strip()) or "{{secret}}" not in value:
            raise _invalid_connection("secret_header: 'Name: ...{{secret}}...'")
    if not 1 <= body.timeout_s <= 600:
        raise _invalid_connection("timeout_s: 1 to 600")
    if body.refusal is not None:
        status = body.refusal.get("status")
        if (not isinstance(status, list) or not status
                or not all(isinstance(x, int) and 100 <= x <= 599 for x in status)
                or not isinstance(body.refusal.get("path", ""), str)
                or not isinstance(body.refusal.get("match", {}), dict)
                or set(body.refusal) - {"status", "path", "match"}):
            raise _invalid_connection("refusal: {status: [codes], path?: str, match?: {path: value}}")
    if body.kind == "rest":
        if not (body.response_path or "").strip():
            raise _invalid_connection("response_path: where the answer is in the response")
        if body.body_template is None and method != "GET":
            raise _invalid_connection("body_template: the request body, with {{input}}")
    if body.kind in ("openai", "oip") and not (body.model or "").strip():
        raise _invalid_connection("model: the model the endpoint serves")
    if body.protocol_version is not None and (body.kind != "a2a" or body.protocol_version not in ("1.0", "0.3")):
        raise _invalid_connection("protocol_version: 1.0 or 0.3, for an a2a connection")
    return {"label": label, "kind": body.kind, "base_url": body.base_url.strip().rstrip("/"), "method": method,
            "path": body.path.strip(), "headers": dict(body.headers), "secret_header": body.secret_header,
            "body_template": body.body_template, "response_path": body.response_path,
            "refusal": body.refusal, "model": body.model, "timeout_s": body.timeout_s,
            "protocol_version": body.protocol_version}


def connection_view(row: dict) -> dict:
    out = {k: row.get(k) for k in connection_store.PUBLIC}
    for k in ("updated_at", "last_test_at"):
        out[k] = row[k].isoformat() if row.get(k) else None
    out["engine_component"] = str(row["engine_component"]) if row.get("engine_component") else None
    out["has_secret"] = bool(row.get("has_secret"))
    target = target_store.get(row["pid"], row["target_key"]) if row.get("target_key") and row.get("pid") else None
    out["target"] = {"key": target["key"], "kind": target["kind"], "label": target["label"]} if target else None
    out.pop("target_key", None)
    return out


def admin_connection(slug: str, caller: Caller, name: str) -> str:
    pid = admin_project(slug, caller)["pid"]
    if not CONNECTION_NAME.match(name):
        raise HTTPException(status_code=422, detail="name: lower-case letters, digits and hyphens, up to 63")
    return pid


LEGACY_MIRROR = "Legacy connection: {label}, pick its target instead"


def retire_engine_component(pid: str, row: dict, request: Request) -> None:
    """A connection made before targets had an engine component of its own; evaluations now pick
    the target's instead (O1). The old one is kept, for the evaluations that used it, and renamed
    so the evaluation form says what to pick instead."""
    if row.get("engine_component") is None:
        return
    from platform_service import engine_components
    try:
        engine_components.rename(pid, token_from_headers(request.headers) or "", str(row["engine_component"]),
                                 LEGACY_MIRROR.format(label=row["label"]))
    except engine_components.EngineUnavailable as exc:
        logger.warning("legacy engine component of connection %s (project %s) not renamed: %s",
                       row["name"], pid, exc)


def _with_pid(pid: str, row: dict | None) -> dict | None:
    return {**row, "pid": pid} if row else row


@app.get("/projects/{slug}/connections")
def list_connections(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    pid = admin_project(slug, caller)["pid"]
    return {"connections": [connection_view(_with_pid(pid, r)) for r in connection_store.list_connections(pid)]}


@app.put("/projects/{slug}/connections/{name}")
def save_connection(slug: str, name: str, body: ConnectionIn, request: Request,
                    caller: Caller = Depends(caller_dependency)) -> JSONResponse:
    """Create, update or revive a connection. `secret` absent keeps the stored key, "" removes it."""
    pid = admin_connection(slug, caller, name)
    fields = connection_fields(body)
    ciphertext = connection_store.KEEP
    if "secret" in body.model_fields_set:
        try:
            ciphertext = llm_store.encrypt(body.secret) if body.secret else None
        except llm_store.SecretsKeyError as exc:
            raise secrets_unavailable(exc) from None
    before = connection_store.get(pid, name, with_deleted=True)
    if "target" in body.model_fields_set and body.target is not None:
        if not targets.is_key(body.target) or target_store.get(pid, body.target) is None:
            raise HTTPException(status_code=422, detail=f"target: {body.target!r} is not a target of this project")
        if before and before.get("target_key") and before["target_key"] != body.target:
            raise HTTPException(status_code=422, detail="target: an endpoint's target is set once; make a new "
                                                        "connection for another target")
        holder = connection_store.holder_of(pid, body.target)
        if holder is not None and holder != name:
            raise HTTPException(status_code=409, detail=f"target: {body.target} already has an endpoint, {holder}")
        fields["target_key"] = body.target
    try:
        row = connection_store.save(pid, name, fields, ciphertext=ciphertext, subject=caller.username or caller.subject)
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"target: {body.target} already has an endpoint") from None
    retire_engine_component(pid, row, request)
    return JSONResponse(status_code=200, content=connection_view(_with_pid(pid, row)))


@app.post("/projects/{slug}/connections/{name}/link")
def link_connection(slug: str, name: str, request: Request, caller: Caller = Depends(caller_dependency)) -> JSONResponse:
    """Connections are no engine components any more (targets plan v2, O1): an older one's is
    renamed legacy, kept for the evaluations that used it; evaluations pick the target."""
    pid = admin_connection(slug, caller, name)
    row = connection_store.get(pid, name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    retire_engine_component(pid, row, request)
    return JSONResponse(status_code=200, content=connection_view(_with_pid(pid, row)))


@app.delete("/projects/{slug}/connections/{name}", status_code=204)
def delete_connection(slug: str, name: str, caller: Caller = Depends(caller_dependency)) -> Response:
    """Mark it deleted. The engine's component stays, so past evaluations keep what they used."""
    pid = admin_connection(slug, caller, name)
    if not connection_store.delete(pid, name):
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    return Response(status_code=204)


def descriptor_of(row: dict, pid: str | None = None) -> dict:
    """What the plugin-side client needs, the key decrypted, and the target it is the endpoint of
    (part of what the connection is, so of its fingerprint)."""
    out = {k: row.get(k) for k in connection_store.PUBLIC if k not in ("engine_component", "last_test_at",
                                                                       "last_test_ok", "last_test_detail",
                                                                       "target_key")}
    out["updated_at"] = row["updated_at"].isoformat() if row.get("updated_at") else None
    out["secret"] = llm_store.decrypt(row["name"], row["secret_ciphertext"]) if row.get("secret_ciphertext") else None
    out["target"] = _target_of(pid, row) if pid else None
    return out


_PROBE_ERRORS = (("BlockedAddress", "blocked"), ("EndpointAuthError", "auth"), ("EndpointNotFound", "not_found"),
                 ("EndpointTimeout", "timeout"), ("EndpointBadResponse", "bad_response"))


@app.post("/projects/{slug}/connections/{name}/test")
def test_connection(slug: str, name: str, body: ProbeIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """One probe, without retries, through the same client the plugins use; the result is stored."""
    from aisc_plugin_interface import connections as client

    pid = admin_connection(slug, caller, name)
    row = connection_store.descriptor(pid, name)
    if row is None or row["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    try:
        descriptor = client.Descriptor.from_dict(descriptor_of(row, pid))
    except llm_store.SecretsKeyError as exc:
        raise secrets_unavailable(exc) from None
    except llm_store.KeyUnreadable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    try:
        answer = client.call(descriptor, body.input, waits=(), **connection_allowlist.rule(pid))
    except client.EndpointError as exc:
        error = next((code for cls, code in _PROBE_ERRORS if type(exc).__name__ == cls), "error")
        message = str(exc).replace(descriptor.secret, "***") if descriptor.secret else str(exc)
        connection_store.record_test(pid, name, False, message)
        return {"ok": False, "error": error, "detail": message}
    if answer.refused:
        connection_store.record_test(pid, name, True, f"refused: {answer.refusal_reason}")
        return {"ok": True, "refused": True, "refusal_reason": answer.refusal_reason, "status": answer.status,
                "latency_ms": answer.latency_ms}
    text = str(answer.text)
    connection_store.record_test(pid, name, True, text)
    return {"ok": True, "refused": False, "answer": text[:500], "status": answer.status,
            "latency_ms": answer.latency_ms}


def _internal_gate(pid: str, request: Request) -> JSONResponse | None:
    """The internal routes' guards: not through the gateway, closed without the token, the token
    compared in constant time, a known project."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return _internal(404, {"detail": "not here"})
    expected = os.environ.get("PLATFORM_CONNECTIONS_TOKEN") or ""
    if not expected:
        return _internal(503, {"detail": "the internal route is closed: PLATFORM_CONNECTIONS_TOKEN is not set"})
    if not hmac.compare_digest(request.headers.get("x-aisc-service-token", "").encode(), expected.encode()):
        return _internal(401, {"detail": "a service token is needed"})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    return None


def _endpoint_of_target(pid: str, key: str) -> tuple[str | None, JSONResponse | None]:
    """The name of the connection that is this target's endpoint, or the answer why there is none."""
    target = target_store.get(pid, key) if targets.is_key(key) else None
    if target is None:
        return None, _internal(404, {"detail": f"no target {key!r}"})
    name = connection_store.holder_of(pid, key)
    if name is None:
        return None, _internal(404, {"detail": f"{target['label']} has no endpoint: set one under Manage,"
                                               " Targets and endpoints"})
    return name, None


def _target_of(pid: str, row: dict) -> dict | None:
    target = target_store.get(pid, row["target_key"]) if row.get("target_key") else None
    if target is None:
        return None
    return {"key": target["key"], "kind": target["kind"], "component_kind": target["component_kind"],
            "label": target["label"], "last_card_number": target["last_card_number"]}


@app.get("/internal/projects/{pid}/targets/{key}/connection")
def resolve_target_connection(pid: str, key: str, request: Request) -> JSONResponse:
    """The endpoint of an assessment target, as resolve_connection gives a connection by name."""
    refused = _internal_gate(pid, request)
    if refused:
        return refused
    name, missing = _endpoint_of_target(pid, key)
    return missing or resolve_connection(pid, name, request)


@app.post("/internal/projects/{pid}/targets/{key}/run-keys")
def issue_target_run_key(pid: str, key: str, request: Request) -> JSONResponse:
    """A run key for the endpoint of an assessment target."""
    refused = _internal_gate(pid, request)
    if refused:
        return refused
    name, missing = _endpoint_of_target(pid, key)
    return missing or issue_run_key(pid, name, request)


@app.get("/internal/projects/{pid}/connections/{name}")
def resolve_connection(pid: str, name: str, request: Request) -> JSONResponse:
    """A connection with its decrypted key, for the plugin-side client of an evaluation run.

    Same guards as the LLM resolve route: not through the gateway (404), closed without
    PLATFORM_CONNECTIONS_TOKEN (503), the token in X-AISC-Service-Token compared in constant time
    (401). A deleted connection is 410. The key is never logged."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return _internal(404, {"detail": "not here"})
    expected = os.environ.get("PLATFORM_CONNECTIONS_TOKEN") or ""
    if not expected:
        return _internal(503, {"detail": "the internal route is closed: PLATFORM_CONNECTIONS_TOKEN is not set"})
    given = request.headers.get("x-aisc-service-token", "")
    if not hmac.compare_digest(given.encode(), expected.encode()):
        return _internal(401, {"detail": "a service token is needed"})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    if not CONNECTION_NAME.match(name):
        return _internal(404, {"detail": f"no connection {name!r}"})
    row = connection_store.descriptor(pid, name)
    if row is None:
        return _internal(404, {"detail": f"no connection {name!r}"})
    if row["deleted_at"] is not None:
        return _internal(410, {"detail": f"connection {name!r} was deleted"})
    try:
        out = descriptor_of(row, pid)
    except llm_store.SecretsKeyError as exc:
        return _internal(503, {"detail": str(exc)})
    except llm_store.KeyUnreadable as exc:
        return _internal(409, {"detail": str(exc)})
    # the network rule of the project, now: the run's own environment opens nothing
    out.update(connection_allowlist.rule(pid))
    logger.info("connection %s of project %s resolved for a run", name, pid)
    return _internal(200, out)


# ── Assessment targets (targets plan v2, 2026-09-29) ──────────────────────────
# What each evaluation is about: the system, or one component of its AI card. Any member reads
# them; an editor refreshes them from the card (the card's own editors add components); the
# qualification app calls the refresh after every card save. Every call to another module is made
# with the caller's own token.

def _targets_answer(pid: str, synced: dict | None = None) -> dict:
    from platform_service import db as _db

    _exists, latest = _db.latest_version(str(pid))
    number = latest["number"] if latest else None
    return {"targets": targets.view(pid, number), "latest_card": number,
            "reason": (synced or {}).get("reason")}


@app.get("/projects/{slug}/targets")
def list_targets(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    targets.ensure_system(found["pid"], found["name"])
    return _targets_answer(found["pid"])


@app.post("/projects/{slug}/targets/sync")
def sync_targets(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    role_or_404(slug, caller, "editor")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    targets.ensure_system(found["pid"], found["name"])
    synced = targets.sync(found["pid"], token_from_headers(request.headers) or "")
    return _targets_answer(found["pid"], synced)


# ── Collect evidence (evidence links plan 2026-09-30) ──────────────────────────
# Members read; editors and owners change the links (D6). What may be linked is read from steps 2
# and 3 as report_ro (evidence.py).

class EvidenceLinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective_id: StrictStr
    kind: StrictStr
    key: StrictStr


class EvidenceLinksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    links: list[EvidenceLinkIn]
    #: The AI card version the links are for; none is the latest, the only one that changes.
    version: str | None = None


def _evidence_answer(pid, role: str, version: str | None = None) -> dict:
    try:
        answer = evidence.view(pid, version)
    except evidence.NotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except evidence.UnknownVersion as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    answer["can_edit"] = at_least(role, "editor") and not answer["read_only"]
    return answer


@app.get("/projects/{slug}/evidence")
def get_evidence(slug: str, version: str | None = None, caller: Caller = Depends(caller_dependency)) -> dict:
    """Step 4 of one AI card version: `version` is its pid, the latest when left out."""
    role = role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return _evidence_answer(found["pid"], role, version)


@app.put("/projects/{slug}/evidence/links")
def put_evidence_links(slug: str, body: EvidenceLinksIn, caller: Caller = Depends(caller_dependency)) -> dict:
    role = role_or_404(slug, caller, "editor")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    if len(body.links) > 5000:
        raise HTTPException(status_code=422, detail="links: at most 5000")
    try:
        evidence.replace(found["pid"], [(l.objective_id, l.kind, l.key) for l in body.links],
                         caller.subject, body.version)
    except evidence.Refused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except evidence.OlderVersion as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except evidence.UnknownVersion as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except evidence.NotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    logger.info("project %s: %d evidence links saved", found["pid"], len(body.links))
    return _evidence_answer(found["pid"], role, body.version)


# ── Allowed internal hosts (allowlist task 2026-09-29) ─────────────────────────
# Per project; its owners and platform admins edit it. The deployment's CONNECTIONS_ALLOWED_HOSTS
# is a floor shown read-only; the stack's own services, loopback and metadata are never allowed
# here (connection_allowlist).

class AllowedHostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: StrictStr | None = None


def owner_project(slug: str, caller: Caller) -> str:
    """The project's pid, for an owner or a platform admin; a stranger gets 404, a lesser member 403."""
    role_or_404(slug, caller, "owner")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found["pid"]


def _allowed_view(row: dict) -> dict:
    return {"host": row["host"], "note": row["note"], "updated_by": row["updated_by"],
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
            "denied": connection_allowlist.why_denied(row["host"])}


def _entry_or_422(entry: str) -> str:
    try:
        return connection_allowlist.normalise(entry)
    except connection_allowlist.InvalidEntry as exc:
        raise HTTPException(status_code=422, detail=f"{entry!r}: {exc}") from None


def _not_the_floor(host: str) -> None:
    if host in {connection_allowlist.normalise(h) for h in connection_allowlist.floor()
                if connection_allowlist._valid(h)}:
        raise HTTPException(status_code=409, detail=f"{host} is allowed by the deployment (CONNECTIONS_ALLOWED_HOSTS)"
                                                    " and is changed there, not here")


@app.get("/projects/{slug}/allowed-hosts")
def list_allowed_hosts(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    pid = owner_project(slug, caller)
    return {"floor": connection_allowlist.floor(),
            "entries": [_allowed_view(r) for r in connection_allowlist.entries(pid)]}


@app.put("/projects/{slug}/allowed-hosts/{entry}")
def put_allowed_host(slug: str, entry: str, body: AllowedHostIn,
                     caller: Caller = Depends(caller_dependency)) -> dict:
    pid = owner_project(slug, caller)
    host = _entry_or_422(entry)
    _not_the_floor(host)
    note = (body.note or "").strip() or None
    if note is not None and len(note) > 200:
        raise HTTPException(status_code=422, detail="note: up to 200 characters")
    try:
        row = connection_allowlist.put(pid, host, note, caller.username or caller.subject)
    except connection_allowlist.DeniedEntry as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    logger.info("project %s allows %s for its connections", pid, host)
    return _allowed_view(row)


@app.delete("/projects/{slug}/allowed-hosts/{entry}", status_code=204)
def delete_allowed_host(slug: str, entry: str, caller: Caller = Depends(caller_dependency)) -> Response:
    pid = owner_project(slug, caller)
    host = _entry_or_422(entry)
    _not_the_floor(host)
    if not connection_allowlist.remove(pid, host):
        raise HTTPException(status_code=404, detail=f"{host} is not allowed in this project")
    logger.info("project %s no longer allows %s", pid, host)
    return Response(status_code=204)


# ── Protocol endpoints in front of a connection (connections plan, revision 3) ──────
# A run gets a key for one connection and the URLs of four doors to it: AISC's own (input and
# history in, answer or refusal out), OpenAI Chat Completions, A2A and the Open Inference Protocol.
# The doors translate (connection_facade) and call the connection with the same client the plugins
# use; inside the network only, like the resolve route.

RUN_KEY_PREFIX = "aisc-run-"


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@app.post("/internal/projects/{pid}/connections/{name}/run-keys")
def issue_run_key(pid: str, name: str, request: Request) -> JSONResponse:
    """A key for one evaluation run to reach one connection through the protocol endpoints; only its
    hash is stored. Guarded like the resolve route. Valid CONNECTIONS_RUN_KEY_TTL_S (12 h)."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return _internal(404, {"detail": "not here"})
    expected = os.environ.get("PLATFORM_CONNECTIONS_TOKEN") or ""
    if not expected:
        return _internal(503, {"detail": "the internal route is closed: PLATFORM_CONNECTIONS_TOKEN is not set"})
    if not hmac.compare_digest(request.headers.get("x-aisc-service-token", "").encode(), expected.encode()):
        return _internal(401, {"detail": "a service token is needed"})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    row = connection_store.descriptor(pid, name) if CONNECTION_NAME.match(name) else None
    if row is None or row["deleted_at"] is not None:
        return _internal(404, {"detail": f"no connection {name!r}"})
    from aisc_plugin_interface import connections as client
    try:
        fingerprint = client.Descriptor.from_dict(descriptor_of(row, pid)).fingerprint()
    except llm_store.SecretsKeyError as exc:
        return _internal(503, {"detail": str(exc)})
    except llm_store.KeyUnreadable as exc:
        return _internal(409, {"detail": str(exc)})
    key = RUN_KEY_PREFIX + secrets.token_hex(32)
    ttl = int(os.environ.get("CONNECTIONS_RUN_KEY_TTL_S") or 12 * 3600)
    expires = connection_store.issue_run_key(pid, name, _key_hash(key), fingerprint, ttl)
    root = f"{os.environ.get('PLATFORM_INTERNAL_URL', 'http://platform:8000').rstrip('/')}/internal/facade/{pid}/{name}"
    logger.info("run key issued for connection %s of project %s", name, pid)
    return _internal(201, {"key": key, "expires_at": expires.isoformat(), "connection": name,
                           "target": _target_of(pid, row), "endpoints": {
        "aisc": {"ask_url": f"{root}/aisc/ask"},
        "openai": {"base_url": f"{root}/openai/v1", "model": name},
        "a2a": {"agent_card_url": f"{root}/a2a/.well-known/agent-card.json", "rpc_url": f"{root}/a2a"},
        "oip": {"base_url": f"{root}/oip", "model": name}}})


def _facade_open(pid: str, name: str, request: Request):
    """(descriptor, None) for a live key of this connection, or (None, (status, message))."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return None, (404, "not here")
    if not looks_like_pid(pid) or not CONNECTION_NAME.match(name):
        return None, (404, "no such connection")
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not key.startswith(RUN_KEY_PREFIX) or db.get_project(pid) is None:
        return None, (401, "a run key is needed")
    if not connection_store.use_run_key(pid, name, _key_hash(key.strip())):
        return None, (401, "a run key is needed")
    row = connection_store.descriptor(pid, name)
    if row is None or row["deleted_at"] is not None:
        return None, (410, f"connection {name!r} was deleted")
    from aisc_plugin_interface import connections as client
    try:
        return client.Descriptor.from_dict(descriptor_of(row, pid)), None
    except (llm_store.SecretsKeyError, llm_store.KeyUnreadable) as exc:
        return None, (503, str(exc))


def _facade_call(pid, descriptor, input, history=None):
    """(answer, None), or (None, error code) when the connection failed. The key is never in it."""
    from aisc_plugin_interface import connections as client
    try:
        return client.call(descriptor, input, history, **connection_allowlist.rule(pid)), None
    except client.EndpointError as exc:
        code = next((c for cls, c in _PROBE_ERRORS if type(exc).__name__ == cls), "error")
        logger.info("connection %s failed behind a protocol endpoint: %s", descriptor.name, code)
        return None, code


async def _json_body(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


@app.post("/internal/facade/{pid}/{name}/aisc/ask")
async def facade_aisc_ask(pid: str, name: str, request: Request) -> JSONResponse:
    descriptor, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    body = await _json_body(request)
    if body is None or "input" not in body or not isinstance(body.get("history", []), list):
        return _internal(400, {"detail": "{input, history?: [{role, content}]}"})
    answer, failed = _facade_call(pid, descriptor, body["input"], body.get("history") or None)
    if failed:
        return _internal(502, {"error": failed})
    return _internal(200, {"output": answer.text, "refused": answer.refused, "refusal_reason": answer.refusal_reason,
                           "status": answer.status, "latency_ms": answer.latency_ms})


@app.post("/internal/facade/{pid}/{name}/openai/v1/chat/completions")
async def facade_openai_chat(pid: str, name: str, request: Request) -> JSONResponse:
    descriptor, err = _facade_open(pid, name, request)
    if err:
        kind = "authentication_error" if err[0] == 401 else "invalid_request_error"
        return _internal(err[0], connection_facade.openai_error(err[1], kind))
    body = await _json_body(request)
    try:
        input, history = connection_facade.openai_to_core(body or {})
    except connection_facade.BadRequest as exc:
        return _internal(400, connection_facade.openai_error(str(exc)))
    answer, failed = _facade_call(pid, descriptor, input, history or None)
    if failed:
        return _internal(502, connection_facade.openai_error(f"the system under test failed: {failed}", "api_error", failed))
    return _internal(200, connection_facade.core_to_openai(name, answer))


@app.get("/internal/facade/{pid}/{name}/openai/v1/models")
def facade_openai_models(pid: str, name: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], connection_facade.openai_error(err[1], "authentication_error"))
    return _internal(200, connection_facade.openai_models(name))


@app.get("/internal/facade/{pid}/{name}/a2a/.well-known/agent-card.json")
def facade_a2a_card(pid: str, name: str, request: Request) -> JSONResponse:
    descriptor, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    root = os.environ.get("PLATFORM_INTERNAL_URL", "http://platform:8000").rstrip("/")
    return _internal(200, connection_facade.a2a_card(descriptor.label or name, f"{root}/internal/facade/{pid}/{name}/a2a"))


@app.post("/internal/facade/{pid}/{name}/a2a")
async def facade_a2a_rpc(pid: str, name: str, request: Request) -> JSONResponse:
    descriptor, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    body = await _json_body(request)
    if body is None:
        return _internal(200, connection_facade.jsonrpc_error(None, -32700, "parse error"))
    rid = body.get("id")
    try:
        dialect, input = connection_facade.a2a_to_core(body)
    except KeyError:
        return _internal(200, connection_facade.jsonrpc_error(rid, -32601, f"method not found: {body.get('method')}"))
    except connection_facade.BadRequest as exc:
        return _internal(200, connection_facade.jsonrpc_error(rid, -32602, str(exc)))
    answer, failed = _facade_call(pid, descriptor, input)
    if failed:
        return _internal(200, connection_facade.jsonrpc_error(rid, -32603, f"the system under test failed: {failed}"))
    return _internal(200, connection_facade.jsonrpc_result(rid, connection_facade.core_to_a2a(dialect, answer)))


@app.get("/internal/facade/{pid}/{name}/oip/v2")
def facade_oip_server(pid: str, name: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    return _internal(err[0], {"error": err[1]}) if err else _internal(200, connection_facade.oip_server())


@app.get("/internal/facade/{pid}/{name}/oip/v2/health/{which}")
def facade_oip_health(pid: str, name: str, which: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    return _internal(200, {}) if which in ("live", "ready") else _internal(404, {"error": "not found"})


@app.get("/internal/facade/{pid}/{name}/oip/v2/models/{model}")
def facade_oip_model(pid: str, name: str, model: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    if model != name:
        return _internal(404, {"error": f"no model {model!r}; this endpoint serves {name!r}"})
    return _internal(200, connection_facade.oip_model(name))


@app.get("/internal/facade/{pid}/{name}/oip/v2/models/{model}/ready")
def facade_oip_model_ready(pid: str, name: str, model: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    return _internal(200, {}) if model == name else _internal(404, {"error": f"no model {model!r}"})


@app.post("/internal/facade/{pid}/{name}/oip/v2/models/{model}/infer")
async def facade_oip_infer(pid: str, name: str, model: str, request: Request) -> JSONResponse:
    descriptor, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    if model != name:
        return _internal(404, {"error": f"no model {model!r}; this endpoint serves {name!r}"})
    body = await _json_body(request)
    try:
        inputs = connection_facade.oip_to_core(body or {})
    except connection_facade.BadRequest as exc:
        return _internal(400, {"error": str(exc)})
    answers = []
    for item in inputs:
        answer, failed = _facade_call(pid, descriptor, item)
        if failed:
            return _internal(502, {"error": f"the system under test failed: {failed}"})
        answers.append(answer)
    return _internal(200, connection_facade.core_to_oip(name, (body or {}).get("id"), answers))


# ── the ledger: reading, export, admin, internal events, beacon (spec 6.3, 3.5, 4.4) ─────────────────

#: The index columns that must say what the verified entry says (an edited index row is an alarm, I4).
_INDEXED = ("event_id", "action", "actor_ref", "step", "source_app", "item_type", "item_id", "card_version",
            "outcome", "request_id", "run_id", "before_sha256", "after_sha256")
_EVENT_FILTERS = {"step": "step", "app": "source_app", "action": "action", "item_type": "item_type",
                  "item_id": "item_id", "card_version": "card_version", "outcome": "outcome"}
_PAGE = 100


def _ledger_project(slug: str, caller: Caller) -> tuple[dict, str, str]:
    """(project, role, its log) for a member; a stranger gets 404, and so does a project with no log."""
    from platform_service.ledger import provision

    role = role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    log = provision.database_for(str(found["pid"]))
    if log is None:
        raise HTTPException(status_code=404, detail="this project has no ledger yet")
    return found, role, log


def _ledger_unavailable(exc) -> HTTPException:
    return HTTPException(status_code=503, detail=f"the ledger can't be read now: {exc.__class__.__name__}")


def _person(pid: str, ref: str | None) -> dict | None:
    from platform_service.ledger import actors

    if not ref:
        return None
    try:
        who = actors.resolve(pid, ref)
    except actors.MappingAlarm:
        return {"ref": ref, "sub": None, "name": None, "alarm": "mapping"}
    if who is None:
        return {"ref": ref, "sub": None, "name": None, "erased": True}
    return {"ref": ref, "sub": who[0], "name": who[1]}


def _shown(pid: str, entry) -> dict:
    data = entry.as_dict()
    data["actor"] = {"kind": entry.actor_kind, **(_person(pid, entry.actor_ref) or {"ref": None})}
    if data.get("on_behalf_of_ref"):
        data["on_behalf_of"] = _person(pid, data["on_behalf_of_ref"])
    data["verified"] = True
    return data


def _verified_entry(log: str, seq: int):
    from platform_service import ledger
    from platform_service.ledger.store import LedgerUnavailable, TamperAlarm

    try:
        return ledger.current().get(log, seq)
    except TamperAlarm as exc:
        logger.error("ledger %s: entry %s failed verification: %s", log, seq, exc)
        raise HTTPException(status_code=409, detail=f"tamper alarm: entry {seq} doesn't verify") from None
    except LedgerUnavailable as exc:
        raise _ledger_unavailable(exc) from None
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no entry {seq}") from None


def _same(indexed, logged) -> bool:
    if indexed is None or logged is None:
        return indexed is None and logged is None
    return str(indexed) == str(logged)


@app.get("/projects/{slug}/ledger/events")
def ledger_events(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    """The project's entries, newest first, filtered on the read index, each verified against the store
    before it is shown. `actor` is a subject; `ai=true` keeps AI actions; `from`/`to` bound occurred_at;
    `cursor` is the last seq of the previous page."""
    from platform_service.ledger import actors

    found, _, log = _ledger_project(slug, caller)
    pid = str(found["pid"])
    q = request.query_params
    where, args = ["log = %s"], [log]
    for name, column in _EVENT_FILTERS.items():
        if q.get(name):
            where.append(f"{column} = %s")
            args.append(int(q[name]) if name == "step" and q[name].isdigit() else q[name])
    if q.get("actor"):
        ref = actors.ref_of(pid, q["actor"])
        if ref is None:
            return {"events": [], "next": None}
        where.append("actor_ref = %s")
        args.append(ref)
    if q.get("ai") in ("1", "true"):
        where.append("actor_kind = 'ai'")
    for name, op in (("from", ">="), ("to", "<=")):
        if q.get(name):
            where.append(f"occurred_at {op} %s")
            args.append(q[name])
    if q.get("cursor", "").isdigit():
        where.append("seq < %s")
        args.append(int(q["cursor"]))
    with db.pool().connection() as conn:
        rows = conn.execute(f"SELECT * FROM ledger.event_index WHERE {' AND '.join(where)}"
                            f" ORDER BY seq DESC LIMIT {_PAGE}", args).fetchall()
    events = []
    for row in rows:
        entry = _verified_entry(log, row["seq"])
        logged = entry.as_dict()
        if any(not _same(row[c], logged.get(c)) for c in _INDEXED):
            logger.error("ledger %s: index row %s disagrees with the log", log, row["seq"])
            raise HTTPException(status_code=409, detail=f"index alarm: row {row['seq']} disagrees with the log")
        events.append(_shown(pid, entry))
    return {"events": events, "next": rows[-1]["seq"] if len(rows) == _PAGE else None}


@app.get("/projects/{slug}/ledger/events/{seq}")
def ledger_event(slug: str, seq: int, caller: Caller = Depends(caller_dependency)) -> dict:
    found, _, log = _ledger_project(slug, caller)
    return _shown(str(found["pid"]), _verified_entry(log, seq))


@app.get("/projects/{slug}/ledger/export")
def ledger_export(slug: str, caller: Caller = Depends(caller_dependency)) -> Response:
    """The whole log as JSON lines, for scripts/verify-ledger-export.py (EXPORT_ROLES only)."""
    import json as _json

    from platform_service.ledger import export, settings as ledger_settings
    from platform_service.ledger.store import LedgerUnavailable, TamperAlarm

    found, role, _ = _ledger_project(slug, caller)
    if role not in ledger_settings.EXPORT_ROLES:
        raise HTTPException(status_code=403, detail="the export is for the project's owners")
    try:
        lines = export.lines(str(found["pid"]))
    except TamperAlarm as exc:
        raise HTTPException(status_code=409, detail=f"tamper alarm: {exc}") from None
    except LedgerUnavailable as exc:
        raise _ledger_unavailable(exc) from None
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from None
    logger.info("project %s: ledger exported by %s (%d entries)", found["pid"], caller.subject, len(lines) - 1)
    body = "\n".join(_json.dumps(line, separators=(",", ":"), ensure_ascii=False) for line in lines) + "\n"
    return Response(body, media_type="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="ledger-{found["slug"]}.jsonl"',
                             "Cache-Control": "no-store"})


@app.get("/ledger/projects")
def ledger_projects(caller: Caller = Depends(requires_role(ADMIN_ROLE))) -> dict:
    """Every project's log and head, for a platform admin."""
    from platform_service import ledger
    from platform_service.ledger import provision
    from platform_service.ledger.store import LedgerError

    store = ledger.current()
    out = []
    for p in db.list_projects():
        pid = str(p["pid"])
        log = provision.database_for(pid)
        row = {"pid": pid, "slug": p["slug"], "log": log, "head": None}
        if log is not None:
            try:
                head = store.head(log)
                row["head"] = {"seq": head.seq, "state_hash": head.state_hash}
            except LedgerError as exc:
                row["error"] = exc.__class__.__name__
        out.append(row)
    return {"projects": out}


class ReanchorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pid: StrictStr


@app.post("/ledger/reanchor")
def ledger_reanchor(body: ReanchorIn, caller: Caller = Depends(requires_role(ADMIN_ROLE))) -> dict:
    """After an immudb restore (runbook ledger-restore.md): trust the store's current state for this log.
    Recorded in the platform log directly, whatever LEDGER_MODE says: it changes what the ledger trusts."""
    from datetime import datetime, timezone

    from platform_service import ledger
    from platform_service.ledger import actors, outbox, provision, registry, relay
    from platform_service.ledger.naming import PLATFORM_DB
    from platform_service.ledger.store import LedgerError

    if not looks_like_pid(body.pid) or db.get_project(body.pid) is None:
        raise no_project(body.pid)
    log = provision.database_for(body.pid)
    if log is None:
        raise HTTPException(status_code=404, detail="this project has no ledger")
    store = ledger.current()
    try:
        old, new = store.reanchor(log)
        head = store.head(log)
    except LedgerError as exc:
        raise _ledger_unavailable(exc) from None
    entry = {"event_id": str(uuid.uuid4()), "occurred_at": relay._iso(datetime.now(timezone.utc)), "project_pid": None, "step": 0, "source_app": "platform",
             "action": "ledger.reanchored", "actor_kind": "user",
             "actor_ref": actors.ref_for(None, caller.subject, caller.username or caller.subject),
             "request_id": outbox.current_request.get(), "item_type": "ledger", "item_id": log, "outcome": "ok",
             "details": {"old_head": old, "new_head": new, "project": body.pid}, "verified": True,
             "registry_version": registry.VERSION}
    with relay._log_lock(PLATFORM_DB):
        seq = store.append(PLATFORM_DB, entry)
        relay._index(PLATFORM_DB, seq, entry, None)
    logger.warning("ledger %s re-anchored by %s: %s -> %s", log, caller.subject, old, new)
    return {"log": log, "old_head": old, "new_head": new, "head": head.seq, "recorded": seq}


# The internal route: callers without an outbox (spec 4.4, I2, T17). Each caller has its own token and
# is the event's emitter; the relay checks it may emit that action and that the run is real.
LEDGER_CALLERS = {"qualification_agents": "PLATFORM_LEDGER_AGENTS_TOKEN", "engine": "PLATFORM_LEDGER_ENGINE_TOKEN",
                  "dashboard": "PLATFORM_LEDGER_DASHBOARD_TOKEN"}
_INTERNAL_COLUMNS = ("event_id", "request_id", "run_id", "action", "item_type", "item_id", "item_version",
                     "card_version", "content", "before", "after", "details", "outcome", "model")


def _ledger_caller(request: Request) -> tuple[str | None, JSONResponse | None]:
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return None, _internal(404, {"detail": "not here"})
    given = request.headers.get("x-aisc-service-token", "")
    tokens = {caller: os.environ[name] for caller, name in LEDGER_CALLERS.items() if os.environ.get(name)}
    found = system_of_token(given, tokens) if given else None
    if found:
        return found, None
    if not given:
        return None, _internal(401, {"detail": "a service token is needed"})
    if len(tokens) < len(LEDGER_CALLERS):                             # maybe a caller this platform wasn't given
        return None, _internal(503, {"detail": "the ledger's internal route isn't configured for every caller"})
    return None, _internal(401, {"detail": "a service token is needed"})


def _malformed(event) -> str | None:
    from platform_service.ledger import registry

    if not isinstance(event, dict):
        return "the body must be one event object"
    for field in ("event_id", "request_id"):
        try:
            uuid.UUID(str(event.get(field)))
        except ValueError:
            return f"{field}: a UUID is needed"
    if not isinstance(event.get("action"), str) or not event["action"]:
        return "action: needed"
    if not isinstance(event.get("details", {}), dict):
        return "details: an object"
    action = registry.REGISTRY.get(event["action"])
    if action is not None and {"ai", "worker"} & set(action.actor_kinds) and "user" not in action.actor_kinds:
        try:
            uuid.UUID(str(event.get("run_id")))
        except ValueError:
            return "run_id: an AI or worker event belongs to a run"
        if "ai" in action.actor_kinds and not (isinstance(event.get("model"), str) and event["model"]):
            return "model: an AI event names its model"
    return None


@app.post("/internal/projects/{pid}/ledger/events", status_code=202)
async def ledger_internal_event(pid: str, request: Request) -> JSONResponse:
    """Queue one event in core.outbox, its emitter the caller; accepted or rejected by the relay (202)."""
    from starlette.concurrency import run_in_threadpool

    caller, refused = _ledger_caller(request)
    if refused:
        return refused
    if not looks_like_pid(pid):
        return _internal(404, {"detail": f"no project {pid!r}"})
    try:
        event = await request.json()
    except ValueError:
        return _internal(422, {"detail": "the body must be JSON"})
    problem = _malformed(event)
    if problem:
        return _internal(422, {"detail": problem})
    return await run_in_threadpool(_queue_internal, pid, caller, event)


def _queue_internal(pid: str, caller: str, event: dict) -> JSONResponse:
    from platform_service.ledger import outbox

    if db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    extra = {k: v for k, v in event.items() if k not in _INTERNAL_COLUMNS}
    with db.pool().connection() as conn:
        exists = conn.execute("SELECT 1 FROM core.outbox WHERE event_id = %s", (event["event_id"],)).fetchone()
        if not exists:
            outbox.emit(conn, event["action"], project_pid=pid, item_type=event.get("item_type"),
                        item_id=event.get("item_id"), details=event.get("details") or {}, content=event.get("content"),
                        before=event.get("before"), after=event.get("after"), item_version=event.get("item_version"),
                        card_version=event.get("card_version"), request_id=event["request_id"], emitter=caller,
                        run_id=event.get("run_id"), model=event.get("model"), event_id=event["event_id"],
                        outcome=event.get("outcome") or "ok", extra=extra)
    return _internal(202, {"queued": event["event_id"]})


# The beacon (spec 3.5, D10): what only the browser knows. Witnessed, small, best effort, kept outside
# immudb for PAGE_VIEW_RETENTION, every row marked as the browser's word.
BEACON_MAX_BYTES = 2048


@app.post("/ledger/beacon", status_code=204)
async def ledger_beacon(request: Request, caller: Caller = Depends(caller_dependency)) -> Response:
    import json as _json

    from starlette.concurrency import run_in_threadpool

    from platform_service.ledger import witness as ledger_witness

    raw = await request.body()
    if len(raw) > BEACON_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"a beacon is at most {BEACON_MAX_BYTES} bytes")
    if ledger_witness.mode() == "off":
        return Response(status_code=204)
    request_id = request.headers.get("x-aisc-request-id")
    problem = await run_in_threadpool(_ledger_presented, request, request_id)
    if problem:                                                       # in record mode too: the beacon is only
        raise HTTPException(status_code=401, detail=problem)          # worth what its witness is worth
    try:
        body = _json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="the beacon is one JSON object") from None
    if not isinstance(body, dict) or not isinstance(body.get("project"), str):
        raise HTTPException(status_code=422, detail="project: needed")
    action, details = body.get("action"), body.get("details") or {}
    if not isinstance(action, str) or not action.startswith("page.") or not isinstance(details, dict):
        raise HTTPException(status_code=422, detail="only page.* moments come through the beacon")
    await run_in_threadpool(_keep_beacon, body["project"], caller, action, details, request_id)
    return Response(status_code=204)


def _keep_beacon(project: str, caller: Caller, action: str, details: dict, request_id: str) -> None:
    from datetime import timedelta

    from platform_service.ledger import actors, pageviews, registry, settings as ledger_settings

    if action not in registry.REGISTRY or registry.REGISTRY[action].origin != "browser":
        raise HTTPException(status_code=422, detail=f"{action} isn't a beacon moment")
    role_or_404(project, caller)
    found = db.get_project(project)
    pid = str(found["pid"])
    ref = actors.ref_of(pid, caller.subject) or actors.ref_for(pid, caller.subject, caller.username or caller.subject)
    if pageviews.count_recent(ref, timedelta(minutes=1)) >= ledger_settings.BEACON_PER_MINUTE:
        raise HTTPException(status_code=429, detail="too many beacons")
    pageviews.record(pid, ref, action, details, request_id)


@app.exception_handler(RequestValidationError)
def validation_without_values(_request, exc: RequestValidationError) -> JSONResponse:
    """422 for a malformed request, without pydantic's `input` and `ctx`: the value
    sent (a key, say) is never echoed back."""
    detail = [{k: v for k, v in error.items() if k not in ("input", "ctx")} for error in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})


def invalid_input(_, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


for _invalid in (InvalidProject, InvalidSystem, InvalidMembership):
    app.add_exception_handler(_invalid, invalid_input)
