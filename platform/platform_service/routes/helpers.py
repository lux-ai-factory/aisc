"""Helper models (judge, attacker, grader, embedder, generator), per project: kept by its owners and
platform admins, listed for every member."""
from __future__ import annotations

import re
from typing import Literal

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from platform_service import connection_allowlist, db, helper_store, llm_store
from platform_service.routes.admission import role_or_404, secrets_unavailable
from platform_service.routes.llm import clean_base_url, clean_key, clean_model

router = APIRouter()

# A key is write-only: no route below returns it or its ciphertext; helper_store.resolve is the one
# way back to it, for the internal routes that hand it to the engine and the worker.

NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
NOT_VALID_ENDPOINT = "the endpoint must be http(s)://host[:port][/path], without credentials, query or fragment"


class HelperIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: StrictStr
    endpoint_url: StrictStr
    roles: list[Literal["judge", "attacker", "grader", "embedder", "generator"]] = Field(min_length=1)
    api_key: StrictStr | None = None


class HelperTestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: StrictStr


def helper_view(row: dict) -> dict:
    """What a page sees of a helper: never the key, never the ciphertext."""
    return {"name": row["name"], "label": row["label"], "endpoint_url": row["endpoint_url"],
            "roles": list(row["roles"]), "has_key": bool(row["has_key"]),
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None}


def known_name(name: str) -> None:
    if not NAME.fullmatch(name):
        raise HTTPException(status_code=422, detail="the name is lowercase letters, digits and dashes, up to 63")


def managed_project(slug: str, caller: Caller) -> str:
    """The project's pid for an owner or a platform admin (who counts as owner of every project):
    a stranger gets 404, an editor or a viewer 403."""
    role_or_404(slug, caller, "owner")
    found = db.get_project(slug)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no project {slug!r}")
    return found["pid"]


def reachable(pid, url: str) -> None:
    """422 unless the project's connections may reach `url`: the rule of Manage, Connections (a public
    address, or an internal one the deployment or the project allows)."""
    from aisc_plugin_interface import connections as client

    try:
        client.guard_url(url, **connection_allowlist.rule(pid))
    except client.BlockedAddress as exc:
        raise HTTPException(status_code=422, detail=f"endpoint_url: {exc}") from None


@router.get("/projects/{slug}/helpers")
def list_helpers(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    role = role_or_404(slug, caller)
    pid = db.get_project(slug)["pid"]
    return {"helpers": [helper_view(r) for r in helper_store.list_models(pid)],
            "roles": list(helper_store.ROLES), "can_manage": role == "owner"}


@router.put("/projects/{slug}/helpers/{name}")
def save_helper(slug: str, name: str, body: HelperIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """Create, update or revive a helper. `api_key` absent keeps the stored key, "" clears it.
    Everything is validated before anything is encrypted or written."""
    pid = managed_project(slug, caller)
    known_name(name)
    label = body.label.strip()
    if not 1 <= len(label) <= 120:
        raise HTTPException(status_code=422, detail="label: 1 to 120 characters")
    endpoint = clean_base_url(body.endpoint_url)
    if endpoint is None:
        raise HTTPException(status_code=422, detail=NOT_VALID_ENDPOINT)
    reachable(pid, endpoint)
    ciphertext = llm_store.KEEP
    key = None
    if body.api_key is not None:
        key = clean_key(body.api_key) if body.api_key.strip() else None
        try:
            ciphertext = llm_store.encrypt(key) if key else None
        except llm_store.SecretsKeyError as exc:
            raise secrets_unavailable(exc) from None
    from platform_service.ledger import secrets as ledger_secrets, witness as ledger_witness

    fingerprint = None
    if key is not None and ledger_witness.mode() != "off":
        fingerprint = ledger_secrets.fingerprint(pid, key)            # never the key itself
    row = helper_store.save(pid, name, label=label, endpoint_url=endpoint, roles=list(dict.fromkeys(body.roles)),
                            ciphertext=ciphertext, subject=caller.subject, key_fingerprint=fingerprint)
    return helper_view(row)


@router.delete("/projects/{slug}/helpers/{name}", status_code=204)
def remove_helper(slug: str, name: str, caller: Caller = Depends(caller_dependency)) -> Response:
    pid = managed_project(slug, caller)
    if not helper_store.remove(pid, name):
        raise HTTPException(status_code=404, detail=f"no helper {name!r}")
    return Response(status_code=204)


@router.post("/projects/{slug}/helpers/{name}/test")
def test_helper(slug: str, name: str, body: HelperTestIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """One small chat call to the helper with its stored key. The answer is the status only: whatever
    the endpoint said stays out of it."""
    from aisc_plugin_interface import connections as client

    pid = managed_project(slug, caller)
    model = clean_model(body.model)
    try:
        stored = helper_store.resolve(pid, name)
    except llm_store.SecretsKeyError as exc:
        raise secrets_unavailable(exc) from None
    except llm_store.KeyUnreadable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    if stored is None:
        raise HTTPException(status_code=404, detail=f"no helper {name!r}")
    descriptor = client.Descriptor(name=name, label=stored["label"], kind="openai", base_url=stored["endpoint_url"],
                                   model=model, secret=stored["api_key"], timeout_s=30)
    try:
        answer = client.call(descriptor, "Reply with OK.", params={"max_tokens": 5}, waits=(),
                             **connection_allowlist.rule(pid))
    except client.BlockedAddress as exc:
        return {"ok": False, "detail": str(exc)}
    except client.EndpointError as exc:
        # the status, or that nothing answered: the exception's own text can quote the endpoint's body
        if exc.status is not None:
            return {"ok": False, "detail": f"the endpoint answered {exc.status}"}
        return {"ok": False, "detail": "the endpoint did not answer"}
    return {"ok": True, "detail": f"the endpoint answered {answer.status or 200}"}
