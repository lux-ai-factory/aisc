"""What an assessment is about (targets plan v2, 2026-09-29).

A project's targets are its system and each component its AI card lists (the card's Components
block, keyed by the card's stable component key, so a renamed component stays the same target).
Every evaluation names one: each target is mirrored in the engine as a `resource` component whose
value is `target:<pid>/<key>`, which the evaluation form offers as its required `target` input.
A component the latest card no longer lists stays, flagged "not in card vN": its results keep
their target. Mirrors are found again by their value, so a half-finished pass never makes a second
one.
"""
from __future__ import annotations

import logging
import os

from platform_service import engine_components, target_store

logger = logging.getLogger(__name__)

KIND_LABELS = {
    "model": "model", "rule_engine": "rule engine", "llm": "LLM", "training_data": "training data",
    "validation_data": "validation data", "other_data": "data", "pipeline": "pipeline",
    "interface": "interface", "other": "component",
}


def reference(pid, key: str) -> str:
    return f"target:{pid}/{key}"


def mirror_name(row: dict, latest_card: int | None) -> str:
    """What the evaluation form shows for this target."""
    if row["kind"] == "system":
        return f"Target · System: {row['label']}"
    name = f"Target · Component: {row['label']} ({KIND_LABELS.get(row['component_kind'], 'component')})"
    if latest_card is not None and (row["last_card_number"] or 0) < latest_card:
        name += f" (not in card v{latest_card})"
    return name


def status(row: dict, latest_card: int | None) -> str:
    if row["kind"] == "system" or latest_card is None or (row["last_card_number"] or 0) >= latest_card:
        return "current"
    return "stale"


def ensure_system(pid, label: str) -> None:
    target_store.ensure_system(pid, label)


def ensure_mirrors(pid, token: str, latest_card: int | None = None) -> str | None:
    """Every target mirrored in the engine under its current name. None when done, otherwise why
    not (the targets stay as they are; the next pass tries again)."""
    try:
        engine_pid = engine_components.engine_project(pid, token)
        existing = {engine_components.value_of(c): c for c in engine_components.components(pid, token, engine_pid)}
        for row in target_store.all_targets(pid):
            name = mirror_name(row, latest_card)
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
        return f"the engine did not take the targets: {exc}"
    return None


# ── following the AI card ────────────────────────────────────────────────────

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
    return {"reason": "; ".join(reasons) or None, "latest_card": number}


def view(pid, latest_card: int | None) -> list[dict]:
    rows = target_store.all_targets(pid)
    return [{
        "key": r["key"], "kind": r["kind"], "component_kind": r["component_kind"], "label": r["label"],
        "first_card_number": r["first_card_number"], "last_card_number": r["last_card_number"],
        "status": status(r, latest_card),
        "engine_component": str(r["engine_component"]) if r["engine_component"] else None,
    } for r in rows]
