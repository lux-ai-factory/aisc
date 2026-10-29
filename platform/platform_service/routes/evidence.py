"""Step 4: the evidence a project links, and the dashboards it reads them from."""
from __future__ import annotations

import logging

from aisc_identity import Caller
from aisc_identity.access import at_least
from aisc_identity.fastapi import caller_dependency
from aisc_identity.headers import token_from_headers
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, StrictStr

from platform_service import dashboard_bridge, dashboards, db, evidence, reports
from platform_service.routes.admission import no_project, role_or_404

router = APIRouter()

logger = logging.getLogger(__name__)


# Members read; editors and owners change the links. What may be linked is read from steps 2
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


def sync_dashboards(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    """Every plugin's tile in the results dashboard, made or updated from its latest run's default charts.
    Any member: it changes no assessment data."""
    role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    try:
        return dashboards.sync(found["pid"], found["name"], token_from_headers(request.headers) or "")
    except dashboard_bridge.BridgeUnavailable as exc:
        raise HTTPException(status_code=502, detail=f"the results dashboard did not answer: {exc}")


@router.get("/projects/{slug}/declared-charts")
def declared_charts(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    """The charts each plugin configuration's plugin declares, which the report composer puts in a report's
    snapshot. Any member; the engine is asked with the caller's own token."""
    role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return dashboards.declared_charts(found["pid"], token_from_headers(request.headers) or "")


@router.get("/projects/{slug}/reports")
def reports_of_version(slug: str, version: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    """How many reports one AI card version has and the newest: the sandbox page's Report column. Any member."""
    role_or_404(slug, caller)
    if db.get_project(slug) is None:
        raise no_project(slug)
    try:
        return reports.of_version(slug, version, token_from_headers(request.headers) or "")
    except reports.ComposerUnavailable as exc:
        raise HTTPException(status_code=502, detail=f"the report composer {exc}") from None


@router.get("/projects/{slug}/dashboards/open")
def open_dashboards(slug: str, request: Request, plugin: str | None = None, target: str | None = None,
                    version: int | None = None, caller: Caller = Depends(caller_dependency)):
    """Sync, then go to the plugin's tile (with the Target and Version filters set), or to the person's tiles when
    no plugin is named: what the sandbox's Visualisation button and the results page's links open."""
    synced = sync_dashboards(slug, request, caller)
    url = dashboards.open_url(synced["dashboards"], plugin, target, db.get_project(slug)["pid"], version)
    if url is None:
        raise HTTPException(status_code=404, detail=f"no test {plugin!r} in this project")
    return RedirectResponse(url, status_code=303)


@router.get("/projects/{slug}/evidence")
def get_evidence(slug: str, version: str | None = None, caller: Caller = Depends(caller_dependency)) -> dict:
    """Step 4 of one AI card version: `version` is its pid, the latest when left out."""
    role = role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return _evidence_answer(found["pid"], role, version)


@router.put("/projects/{slug}/evidence/links")
def put_evidence_links(slug: str, body: EvidenceLinksIn, caller: Caller = Depends(caller_dependency)) -> dict:
    role = role_or_404(slug, caller, "editor")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    if len(body.links) > 5000:
        raise HTTPException(status_code=422, detail="links: at most 5000")
    try:
        evidence.replace(found["pid"], [(link.objective_id, link.kind, link.key) for link in body.links],
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
