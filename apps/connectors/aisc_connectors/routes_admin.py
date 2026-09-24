"""Admin routes: /api/v1/connectors. Every route depends on admin_call (spec D7)."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from aisc_connectors import engine as engine_api
from aisc_connectors import store, vault
from aisc_connectors.auth import Admin, admin_call
from aisc_connectors.slug import slugify

router = APIRouter(prefix="/api/v1/connectors")

SETTINGS_DEFAULTS = {"timeout_s": 30, "rate_limit_per_minute": 60, "verify_tls": True, "ollama_facade": False}
SETTINGS_BOUNDS = {"timeout_s": (1, 300), "rate_limit_per_minute": (1, 6000)}


def engine_for(admin: Admin = Depends(admin_call)):
    # Yielded so the httpx client closes at the end of the request (ruling 1).
    with engine_api.EngineClient(admin.token) as engine:
        yield engine


class NewConnector(BaseModel):
    project_pid: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    environment: Literal["sandbox", "production"] = "sandbox"


class ConnectorPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    environment: Literal["sandbox", "production"] | None = None
    settings: dict[str, Any] | None = None


class SecretValue(BaseModel):
    value: str = Field(min_length=1, max_length=65536)


def check_auth(auth: dict) -> dict:
    scheme = auth.get("scheme")
    required = {
        "none": [], "bearer": [], "mtls": [],
        "api_key": ["in", "name"], "basic": ["username"],
        "oauth2_client_credentials": ["token_url", "client_id"],
    }
    if scheme not in required:
        raise HTTPException(422, f"unknown auth scheme {scheme!r}")
    missing = [f for f in required[scheme] if not auth.get(f)]
    if missing:
        raise HTTPException(422, f"auth scheme {scheme} needs {missing}")
    if scheme == "api_key" and auth["in"] not in ("header", "query"):
        raise HTTPException(422, "api_key goes in a header or the query")
    allowed = {"scheme", *required[scheme], "scope"}
    return {k: v for k, v in auth.items() if k in allowed}


def check_settings(current: dict, patch: dict) -> dict:
    merged = {**SETTINGS_DEFAULTS, **current, **patch}
    unknown = set(patch) - set(SETTINGS_DEFAULTS)
    if unknown:
        raise HTTPException(422, f"unknown settings {sorted(unknown)}")
    for key, (low, high) in SETTINGS_BOUNDS.items():
        if not isinstance(merged[key], int) or not low <= merged[key] <= high:
            raise HTTPException(422, f"{key} must be an integer between {low} and {high}")
    for key in ("verify_tls", "ollama_facade"):
        if not isinstance(merged[key], bool):
            raise HTTPException(422, f"{key} must be true or false")
    return merged


def loaded(connector_pid: uuid.UUID) -> dict:
    found = store.get(connector_pid)
    if found is None:
        raise HTTPException(404, "no such connector")
    return found


def orphaned(row: dict, engine: engine_api.EngineClient) -> bool:
    try:
        engine.aisystem(row["project_pid"])
        return False
    except engine_api.NotFound:
        return True
    except engine_api.EngineError as exc:
        # ruling 2: an engine refusal other than 404 is a 502, never a 500.
        raise HTTPException(502, f"the engine refused: {exc.detail}") from exc


def shown(row: dict, engine: engine_api.EngineClient) -> dict:
    return {**{k: row[k] for k in ("pid", "project_pid", "ai_system_pid", "name", "slug", "kind", "environment",
                                   "auth", "chat", "is_target_access", "import_warnings")},
            "settings": {**SETTINGS_DEFAULTS, **(row["settings"] or {})},
            "secrets": vault.describe(row["pid"]),
            "orphaned": orphaned(row, engine)}


@router.post("")
def create(body: NewConnector, admin: Admin = Depends(admin_call),
           engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    try:
        system = engine.aisystem(body.project_pid)
    except engine_api.NotFound:
        raise HTTPException(404, "the engine knows no such project")
    except engine_api.EngineError as exc:
        # ruling 2: an engine refusal other than 404 is a 502, never a 500.
        raise HTTPException(502, f"the engine refused: {exc.detail}") from exc
    row = store.create_connector(body.project_pid, uuid.UUID(system["pid"]), body.name, slugify(body.name),
                                 "manual", body.environment, admin.caller.subject)
    return shown(row, engine)


@router.get("")
def list_connectors(project_pid: uuid.UUID, admin: Admin = Depends(admin_call),
                    engine: engine_api.EngineClient = Depends(engine_for)) -> list[dict]:
    return [shown(row, engine) for row in store.list_for_project(project_pid)]


@router.get("/projects/{project_pid}/readiness")
def readiness(project_pid: uuid.UUID, admin: Admin = Depends(admin_call)) -> dict:
    return {"has_target_access": store.target_access_count(project_pid) > 0}


@router.get("/{connector_pid}")
def read(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call),
         engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    return shown(loaded(connector_pid), engine)


@router.patch("/{connector_pid}")
def patch(connector_pid: uuid.UUID, body: ConnectorPatch, admin: Admin = Depends(admin_call),
          engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    row = loaded(connector_pid)
    fields: dict[str, Any] = {}
    if body.name is not None:
        fields.update(name=body.name, slug=slugify(body.name))
    if body.environment is not None:
        fields["environment"] = body.environment
    if body.settings is not None:
        fields["settings"] = check_settings(row["settings"] or {}, body.settings)
    return shown(store.update(connector_pid, **fields) if fields else row, engine)


@router.delete("/{connector_pid}", status_code=204)
def remove(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call),
           engine: engine_api.EngineClient = Depends(engine_for)) -> Response:
    row = loaded(connector_pid)
    if row["is_target_access"] and not orphaned(row, engine):
        raise HTTPException(409, "this is the project's target-access connector: mark another one first")
    store.delete(connector_pid)
    return Response(status_code=204)


@router.post("/{connector_pid}/target-access")
def target_access(connector_pid: uuid.UUID, admin: Admin = Depends(admin_call),
                  engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    loaded(connector_pid)
    store.make_target_access(connector_pid)
    return shown(loaded(connector_pid), engine)


@router.put("/{connector_pid}/auth")
def set_auth(connector_pid: uuid.UUID, body: dict, admin: Admin = Depends(admin_call),
             engine: engine_api.EngineClient = Depends(engine_for)) -> dict:
    loaded(connector_pid)
    return shown(store.update(connector_pid, auth=check_auth(body)), engine)


@router.put("/{connector_pid}/secrets/{name}")
def put_secret(connector_pid: uuid.UUID, name: str, body: SecretValue, admin: Admin = Depends(admin_call)) -> dict:
    loaded(connector_pid)
    try:
        return vault.put(connector_pid, name, body.value)
    except vault.UnknownSecretName as exc:
        raise HTTPException(422, str(exc))


@router.delete("/{connector_pid}/secrets/{name}", status_code=204)
def delete_secret(connector_pid: uuid.UUID, name: str, admin: Admin = Depends(admin_call)) -> Response:
    loaded(connector_pid)
    vault.delete(connector_pid, name)
    return Response(status_code=204)
