"""What an assessment is about.

A project's targets are its system and each component its AI card lists (the card's Components
block, keyed by the card's stable component key, so a renamed component stays the same target).
Every evaluation names one: each target is mirrored in the engine as a `resource` component whose
value is `target:<pid>/<key>`, which the evaluation form offers as its required `target` input.
A component the latest card no longer lists stays, flagged "not in card vN": its results keep
their target. Mirrors are found again by their value, so a half-finished pass never makes a second
one, and passes on one project run one at a time (an advisory lock), so two at once never do either.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager

from platform_service import engine_components, target_store

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "model": "model", "rule_engine": "rule engine", "llm": "LLM", "training_data": "training data",
    "validation_data": "validation data", "other_data": "data", "pipeline": "pipeline",
    "interface": "interface", "other": "component",
}


def reference(pid, key: str) -> str:
    return f"target:{pid}/{key}"


PROTOCOL_NAMES = {"openai": "OpenAI-compatible", "rest": "REST API", "a2a": "A2A agent",
                  "oip": "Open Inference Protocol"}


def mirror_name(row: dict, connection: dict | None = None, latest_card: int | None = None) -> str:
    """What the evaluation form shows for this target: that it comes from the AI card and how it is
    reached. The form lists every target, so the name says whether it is connected: a plugin that
    calls its target can only use one that is."""
    if row["kind"] == "system":
        name = f"AI card · System: {row['label']}"
    else:
        name = f"AI card · Component: {row['label']} ({KIND_LABELS.get(row['component_kind'], 'component')})"
    if connection:
        protocol = PROTOCOL_NAMES.get(connection.get("kind"), connection.get("kind") or "unknown protocol")
        name += f" · reached through {protocol}"
    else:
        name += " · not connected"
    if row["kind"] != "system" and latest_card is not None and (row["last_card_number"] or 0) < latest_card:
        name += f" · not in AI card v{latest_card}"
    return name


def status(row: dict, latest_card: int | None) -> str:
    if row["kind"] == "system" or latest_card is None or (row["last_card_number"] or 0) >= latest_card:
        return "current"
    return "stale"


def ensure_system(pid, label: str) -> None:
    target_store.ensure_system(pid, label)


@contextmanager
def _mirrors_lock(pid):
    """One mirroring pass per project at a time (a card save's sync, a connection save's rename): each
    reads the engine's components before it creates, so two at once would both create a mirror. An
    advisory lock on its own platform-database connection, never one of the pool's (like the ledger
    relay's _log_lock); it waits."""
    import psycopg

    from platform_service import db

    key = f"targets:{pid}"
    with psycopg.connect(db.dsn(), autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (key,))
        try:
            yield
        finally:
            conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))


def ensure_mirrors(pid, token: str, latest_card: int | None = None) -> str | None:
    """Every target mirrored in the engine under its current name. None when done, otherwise why
    not (the targets stay as they are; the next pass tries again)."""
    with _mirrors_lock(pid):
        return _ensure_mirrors(pid, token, latest_card)


def _has_card(pid) -> bool:
    from platform_service import db

    _exists, latest = db.latest_version(str(pid))
    return latest is not None


def _ensure_mirrors(pid, token: str, latest_card: int | None) -> str | None:
    # a project used only for the engine has no AI card targets: its system row stays here, but the
    # engine offers it only once the project has a card version
    has_card = _has_card(pid)
    offered = [row for row in target_store.all_targets(pid) if row["kind"] != "system" or has_card]
    if not offered:
        return None
    try:
        engine_pid = engine_components.engine_project(pid, token)
        existing = {engine_components.value_of(c): c for c in engine_components.components(pid, token, engine_pid)}
        from platform_service import connection_store
        endpoints = connection_store.endpoints_by_target(pid)
        for row in offered:
            name = mirror_name(row, endpoints.get(row["key"]), latest_card)
            found = existing.get(reference(pid, row["key"]))
            if found is None:
                component = engine_components.create(pid, token, name, reference(pid, row["key"]), engine_pid)
            else:
                component = str(found["pid"])
                if found.get("name") != name:
                    engine_components.rename(pid, token, component, name)
            if str(row["engine_component"] or "") != component:
                target_store.set_mirror(pid, row["key"], component)
    except engine_components.EngineUnavailable as exc:
        logger.warning("targets of project %s not mirrored in the engine: %s", pid, exc)
        # the person refreshing sees this; the cause is in the log above
        return "the components could not be passed on to the tests: try Refresh again later"
    return None


# following the AI card
QUAL = "https://lux-ai-factory.github.io/qualification/ns#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
GATEWAY_TOKEN_HEADER = "X-Auth-Request-Access-Token"


class CardUnreadable(RuntimeError):
    """Qualification did not give the latest card's graph."""


def _first(node: dict, predicate: str) -> str | None:
    values = node.get(predicate) or []
    for v in values:
        if isinstance(v, dict) and isinstance(v.get("@value"), str):
            return v["@value"]
    return None


def card_components(graph) -> list[tuple[str, str, str]]:
    """(key, label, kind) of every Components-block row in a card graph (JSON-LD, flat or with
    @graph). Nodes without a key (an older card's extraction guesses) are not components here."""
    nodes = graph.get("@graph", []) if isinstance(graph, dict) else graph
    out, seen = [], set()
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        key, label = _first(node, QUAL + "componentKey"), _first(node, RDFS_LABEL)
        if key and label and key not in seen:
            seen.add(key)
            out.append((key, label, _first(node, QUAL + "kind") or "other"))
    return out


def _fetch_card(pid, version_pid: str, token: str):
    """The card graph of one version, or None when that version has no card."""
    import httpx

    base = (os.environ.get("QUALIFICATION_URL") or "http://qualification-web:3000/qualification").rstrip("/")
    url = f"{base}/p/{pid}/api/system-versions/{version_pid}/ontology.jsonld"
    try:
        r = httpx.get(url, timeout=20, headers={"Authorization": f"Bearer {token}", GATEWAY_TOKEN_HEADER: token})
    except httpx.HTTPError as exc:
        raise CardUnreadable(f"qualification could not be reached ({type(exc).__name__})") from None
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise CardUnreadable(f"qualification answered {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise CardUnreadable("qualification's answer is not JSON-LD") from None


def sync(pid, token: str) -> dict:
    """Bring the project's targets up to date with its latest card and mirror them in the engine.
    Never raises for a module that does not answer: what could not be done is the `reason`, and
    the targets stay as they were."""
    from platform_service import db

    reasons: list[str] = []
    before = {t["key"]: t["label"] for t in target_store.all_targets(pid)}
    ensure_system(pid, "the system")
    _exists, latest = db.latest_version(str(pid))
    number = latest["number"] if latest else None
    if latest:
        target_store.set_system_label(pid, latest["name"])
        try:
            graph = _fetch_card(pid, str(latest["pid"]), token)
        except CardUnreadable as exc:
            reasons.append(str(exc))
            graph = None
        for key, label, kind in card_components(graph) if graph is not None else []:
            target_store.upsert_component(pid, f"component:{key}", label, kind, number)
    mirrored = ensure_mirrors(pid, token, number)
    if mirrored:
        reasons.append(mirrored)
    _record_sync(pid, before)
    return {"reason": "; ".join(reasons) or None, "latest_card": number}


def _record_sync(pid, before: dict) -> None:
    """targets.synced: how many targets were added or renamed. A sync spans several writes and calls to
    the engine, so its event has a transaction of its own, after them."""
    from platform_service import connection_store
    from platform_service.ledger import outbox

    after = {t["key"]: t["label"] for t in target_store.all_targets(pid)}
    with connection_store.connect(pid) as conn, conn.transaction():
        outbox.emit_project(conn, "targets.synced", item_type="project", item_id=str(pid),
                            details={"added": len(set(after) - set(before)),
                                     "renamed": sum(1 for k in set(after) & set(before) if after[k] != before[k])})


def view(pid, latest_card: int | None) -> list[dict]:
    from platform_service import connection_store

    rows = target_store.all_targets(pid)
    endpoints = connection_store.endpoints_by_target(pid)
    return [{
        "key": r["key"], "kind": r["kind"], "component_kind": r["component_kind"], "label": r["label"],
        "first_card_number": r["first_card_number"], "last_card_number": r["last_card_number"],
        "status": status(r, latest_card),
        "engine_component": str(r["engine_component"]) if r["engine_component"] else None,
        "endpoint": endpoints.get(r["key"]),
    } for r in rows]


def assessable_by(target_rows: list[dict], plugins: list[dict]) -> dict[str, list[str]]:
    """Per target key, the installed tests that can assess it: those whose kinds include an AI card
    target, and of those that call their target only a target that has a connection. Its protocol
    does not narrow it: the facade gives a text tool any connection's answer."""
    card = [p for p in plugins if "card" in (p.get("target_kinds") or [])]
    return {t["key"]: [p.get("display_name") or p["name"] for p in card
                       if t.get("endpoint") or not p.get("card_needs_connection")]
            for t in target_rows}


def is_key(key: str) -> bool:
    import re

    return key == "system" or re.fullmatch(r"component:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", key) is not None
