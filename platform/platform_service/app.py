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

import hmac
import re
import uuid
import logging
import os
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

from platform_service import dashboard_bridge, db, llm_catalogue, llm_store, projectdb
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
    # The dashboard lets go of the project's database before it is dropped.
    dashboard_bridge.unregister(found["pid"])
    projectdb.drop(db.dsn(), found["pid"])
    db.delete_project(found["pid"])


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
    made = db.create_version(project, name, version, body.provider, body.description,
                             caller.subject)
    if made is None:
        raise no_project(project)
    return made


@app.get("/projects/{project}/system-versions")
def system_versions(project: str, caller: Caller = Depends(caller_dependency)) -> list[dict]:
    """Every saved card version, highest number first."""
    role_or_404(project, caller)
    found = db.list_versions(project)
    if found is None:
        raise no_project(project)
    return found


@app.get("/projects/{project}/system-versions/latest")
def latest_system_version(project: str, caller: Caller = Depends(caller_dependency)) -> dict | None:
    """The latest saved card version, or null when the project has none yet."""
    role_or_404(project, caller)
    exists, found = db.latest_version(project)
    if not exists:
        raise no_project(project)
    return found


@app.get("/systems/{pid}")
def system(pid: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """A system by its own id.

    The project is checked here too: an id that skips the project is exactly
    how a stranger would read one.
    """
    found = db.get_system(pid)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no system {pid}")
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
    row = llm_store.save_provider(pid, provider, ciphertext=ciphertext, base_url=base_url,
                                  subject=caller.subject)
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
