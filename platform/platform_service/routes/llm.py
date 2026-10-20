"""LLM keys and model choices, per project (admin only), and the route the two agents resolve them on."""
from __future__ import annotations

import unicodedata
from urllib.parse import urlsplit

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from aisc_identity.service_tokens import HEADER as SERVICE_TOKEN_HEADER, ServiceRefused, identify
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StrictStr

from platform_service import db, llm_catalogue, llm_store
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import _internal, admin_project, secrets_unavailable

router = APIRouter()


# A key is write-only: no route below returns it or its ciphertext; only the internal
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


@router.get("/projects/{slug}/llm")
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


@router.put("/projects/{slug}/llm/providers/{provider}")
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
        fingerprint = ledger_secrets.fingerprint(pid, key)            # never the key itself
    row = llm_store.save_provider(pid, provider, ciphertext=ciphertext, base_url=base_url,
                                  subject=caller.subject, key_fingerprint=fingerprint)
    return provider_view(provider, row)


@router.delete("/projects/{slug}/llm/providers/{provider}", status_code=204)
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


@router.get("/projects/{slug}/llm/providers/{provider}/models")
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


@router.put("/projects/{slug}/llm/systems/{system}")
def save_llm_choice(slug: str, system: str, body: SystemChoiceIn,
                    caller: Caller = Depends(caller_dependency)) -> dict:
    """Choose a usable provider and a model for an agentic system (the model is not
    checked against the live list)."""
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


@router.delete("/projects/{slug}/llm/systems/{system}", status_code=204)
def remove_llm_choice(slug: str, system: str, caller: Caller = Depends(caller_dependency)) -> Response:
    """The system goes back to its own environment configuration."""
    pid = admin_project(slug, caller)["pid"]
    known_system(system)
    if not llm_store.delete_choice(pid, system):
        raise HTTPException(status_code=404, detail=f"{system} has no choice to remove")
    return Response(status_code=204)


# ── the internal resolve route, for the two agents only ─────────────────────


#: The token each agentic system resolves itself with, by the variable that holds it.
SYSTEM_TOKENS = {"card_agent": "PLATFORM_CARD_AGENT_TOKEN", "risk_mapper": "PLATFORM_RISK_MAPPER_TOKEN"}


@router.get("/internal/projects/{pid}/llm/{system}")
def resolve_llm(pid: str, system: str, request: Request) -> JSONResponse:
    """The system's choice for this project, with its decrypted key.

    Reached on the backend network only: a request that came through Caddy (it
    carries X-Forwarded-*) is 404. Each agentic system has a token of its own
    (SYSTEM_TOKENS), sent in X-AISC-Service-Token, and a token opens only its own
    system: the card agent can never be handed the risk mapper's key, nor the other
    way round (403). With no system token set the route is closed (503)."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return _internal(404, {"detail": "not here"})
    try:
        caller_system = identify(request.headers.get(SERVICE_TOKEN_HEADER), SYSTEM_TOKENS)
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
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
