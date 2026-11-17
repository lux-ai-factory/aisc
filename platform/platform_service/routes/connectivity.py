"""Manage > Connectivity: what each connection is used for besides reaching the assessed system.

A connection is set up once (routes/connections.py; a provider connection for a model provider's key or a
self-hosted model server). Here it is put to use:

* an admin runs a Configurator agent (card agent, risk mapper) on a provider connection, with a model;
* an owner makes a provider connection a test tool in some roles (judge, attacker, ...), under the connection's
  name; any other connection without a target only an admin (its secret reaches the run's plugin);
* the page reads the whole picture in one call, never a secret, and a connection's settings only for an admin.

The database keeps a connection that reaches the assessed system apart from these uses
(project-template/0030_connectivity.sql); a refused use is 409.
"""
from __future__ import annotations

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, StrictStr

from platform_service import connection_allowlist, connection_store, helper_store, llm_catalogue, llm_store, target_store, targets
from platform_service.routes.admission import allowed_actions, project_for
from platform_service.connections import connection_view
from platform_service.routes.llm import clean_model, known_system

router = APIRouter()


class AgentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: StrictStr
    model: StrictStr


class ToolIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[StrictStr]


def _live(pid: str, name: str) -> dict:
    row = connection_store.get(pid, name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    return row


def _assessed(name: str) -> HTTPException:
    return HTTPException(status_code=409, detail=f"{name} reaches the assessed system: it cannot be used as a "
                                                 "test tool or by a Configurator agent")


# ---- Configurator agents -------------------------------------------------------------------------

@router.put("/projects/{slug}/agents/{system}")
def run_agent_on(slug: str, system: str, body: AgentIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """Run a Configurator agent on a provider connection with a model (the model is not checked against the
    provider's live list)."""
    pid = project_for(slug, caller, "use.agent")["pid"]
    known_system(system)
    row = _live(pid, body.connection)
    if row["kind"] != "provider":
        raise HTTPException(status_code=422, detail="connection: an agent runs on a provider connection "
                                                    "(a model provider's key or a self-hosted model server)")
    entry = llm_catalogue.PROVIDERS[row["provider"]]
    if entry.key_required and not row.get("has_secret"):
        raise HTTPException(status_code=422, detail=f"connection: {body.connection} has no key yet")
    model = clean_model(body.model)
    llm_store.save_agent(pid, system, body.connection, model, subject=caller.subject)
    return {"system": system, "connection": body.connection, "model": model}


@router.get("/projects/{slug}/connections/{name}/models")
def connection_models(slug: str, name: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """The models a provider connection offers, asked live with its own address and key, chat models first: what an
    agent's model is picked from. Admins, as choosing an agent's model is. {"models", "error"}; the key is decrypted
    here only, never answered, and sent only to an address the project's network rule allows now."""
    pid = project_for(slug, caller, "use.agent")["pid"]
    found = llm_store.provider_listing(pid, name)
    if found is None or found["provider"] not in llm_catalogue.PROVIDERS:
        raise HTTPException(status_code=404, detail=f"no provider connection {name!r}")
    try:
        key = llm_store.decrypt(name, found["ciphertext"]) if found["ciphertext"] else None
    except (llm_store.KeyUnreadable, llm_store.SecretsKeyError) as exc:
        return {"models": [], "error": str(exc)}
    base_url = found["base_url"]
    if base_url is None and found["provider"] == "ollama":
        base_url = llm_store.ollama_default()
    rule = connection_allowlist.rule(pid, operator_hosts=llm_store.operator_hosts(base_url))
    listed = llm_catalogue.list_models(found["provider"], api_key=key, base_url=base_url, rule=rule)
    return {"models": llm_catalogue.chat_first(listed["models"]), "error": listed["error"]}


@router.delete("/projects/{slug}/agents/{system}", status_code=204)
def stop_agent_choice(slug: str, system: str, caller: Caller = Depends(caller_dependency)) -> Response:
    """The agent goes back to the stack's own setting."""
    pid = project_for(slug, caller, "use.agent")["pid"]
    known_system(system)
    if not llm_store.remove_agent(pid, system):
        raise HTTPException(status_code=404, detail=f"{system} has no choice to remove")
    return Response(status_code=204)


# ---- test tools ----------------------------------------------------------------------------------

@router.put("/projects/{slug}/connections/{name}/tool")
def use_as_tool(slug: str, name: str, body: ToolIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """Let tests use connection `name` in `roles`; the run's form offers it for each of them. An owner may do it for a
    provider connection; any other kind takes an admin."""
    pid = project_for(slug, caller, "use.tool.provider")["pid"]
    roles = list(dict.fromkeys(body.roles))
    if not roles or any(r not in helper_store.ROLES for r in roles):
        raise HTTPException(status_code=422, detail=f"roles: one or more of {', '.join(helper_store.ROLES)}")
    row = _live(pid, name)
    if row["kind"] != "provider":                     # its secret would reach the run's plugin: an admin's call
        project_for(slug, caller, "use.tool")
    if row.get("target_key"):
        raise _assessed(name)
    try:
        tool = helper_store.use_as_tool(pid, name, roles=roles, subject=caller.subject)
    except connection_store.ConnectionAssessed:
        raise _assessed(name) from None
    if tool is None:
        raise HTTPException(status_code=409, detail=f"a test tool named {name} already uses another connection")
    return {"connection": name, "roles": list(tool["roles"])}


@router.delete("/projects/{slug}/connections/{name}/tool", status_code=204)
def stop_tool(slug: str, name: str, caller: Caller = Depends(caller_dependency)) -> Response:
    """Tests stop using connection `name`; the connection and its key stay."""
    pid = project_for(slug, caller, "use.tool.provider")["pid"]
    if not helper_store.stop_tool(pid, name):
        raise HTTPException(status_code=404, detail=f"{name} is not a test tool")
    return Response(status_code=204)


# ---- the page's one read -------------------------------------------------------------------------

def _used_for(uses: list[dict]) -> dict[str, list[dict]]:
    by_connection: dict[str, list[dict]] = {}
    for u in uses:
        entry = ({"use": "agent", "agent": u["agent"], "model": u["model"]} if u["use"] == "agent"
                 else {"use": "tool", "roles": list(u["roles"])})
        by_connection.setdefault(u["connection"], []).append(entry)
    return by_connection


@router.get("/projects/{slug}/connectivity")
def connectivity(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """Everything Manage > Connectivity shows: the assessed system's components and the connection that reaches
    each, the agents' choices, the connections each test tool role offers, and every connection with what it
    is used for. Never a key, a secret header or a ciphertext; a connection's settings for a platform admin only, an
    owner sees each connection's name, label, kind and uses."""
    pid = project_for(slug, caller, "connectivity.read")["pid"]
    allowed = allowed_actions(slug, caller)
    uses = _used_for(connection_store.uses(pid))
    connections = [{**connection_view({**r, "pid": pid}), "used_for": uses.get(r["name"], []),
                    "protocol": targets.protocol_name(r["kind"])}
                   for r in connection_store.list_connections(pid)]
    reaching = {c["target"]["key"]: c for c in connections if c.get("target")}
    if "connectivity.settings" not in allowed:      # as GET /connections keeps them: settings are for admins
        connections = [{k: c[k] for k in ("name", "label", "kind", "used_for")} for c in connections]
    components = [{"key": t["key"], "kind": t["kind"], "label": t["label"],
                   "component_kind": t.get("component_kind"),
                   "file": ({"name": t["file_name"], "size": t["file_size"], "sha256": t["file_sha256"]}
                            if t.get("file_name") else None),
                   "connection": ({"name": reaching[t["key"]]["name"],
                                   "protocol": targets.protocol_name(reaching[t["key"]]["kind"]),
                                   "last_test_ok": reaching[t["key"]]["last_test_ok"]}
                                  if t["key"] in reaching else None)}
                  for t in target_store.all_targets(pid)]
    chosen = llm_store.choice_connections(pid)
    agents = [{"id": system, "label": label, "choice": chosen.get(system)}
              for system, label in llm_store.SYSTEMS.items()]
    tools = [{"role": role, "connections": [{"name": h["name"], "label": h["label"]}
                                            for h in helper_store.list_models(pid, role)]}
             for role in helper_store.ROLES]
    providers = [{"id": key, "label": entry.label, "key_required": entry.key_required,
                  "base_url_editable": entry.base_url_editable}
                 for key, entry in sorted(llm_catalogue.PROVIDERS.items(), key=lambda kv: kv[1].label)]
    return {"components": components, "agents": agents, "tools": tools, "connections": connections,
            "roles": list(helper_store.ROLES), "providers": providers, "can_manage": "connection.write" in allowed}
