"""A project's catalogue of tests and controls, and the reads and installs through it."""
from __future__ import annotations

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from aisc_identity.headers import token_from_headers
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, StrictStr

from platform_service import catalogue, db, publisher
from platform_service.routes.admission import ADMIN_ROLE, no_project, role_or_404

router = APIRouter()


class CatalogueChoiceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: StrictStr


class LocalDimensionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimensions: list[StrictStr]


def _catalogue_project(slug: str, caller: Caller, needed: str = "viewer") -> dict:
    role_or_404(slug, caller, needed)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found


def _catalogue_answer(pid, caller: Caller) -> dict:
    found = catalogue.mode(pid)
    return {"mode": found["mode"] if found else None,
            "chosen_at": found["chosen_at"].isoformat() if found else None,
            "updated_at": found["updated_at"].isoformat() if found and found["updated_at"] else None,
            "can_update": caller.has_role(ADMIN_ROLE)}


def _private_reads(pid, read):
    """A catalogue read: 409 when the project has no catalogue to read it from (or no private one, for
    what only a copy has), 503 when a public project's public catalogue does not answer."""
    try:
        return read()
    except catalogue.NotPrivate as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except catalogue.PublicUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/projects/{slug}/catalogue")
def get_catalogue(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """The project's catalogue mode (none until it chooses) and whether the caller may update it."""
    return _catalogue_answer(_catalogue_project(slug, caller)["pid"], caller)


@router.post("/projects/{slug}/catalogue")
def choose_catalogue(slug: str, body: CatalogueChoiceIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """An owner or editor chooses public or private, once; private makes the copy now."""
    found = _catalogue_project(slug, caller, "editor")
    if body.mode not in catalogue.MODES:
        raise HTTPException(status_code=422, detail="mode is public or private")
    try:
        catalogue.choose(found["pid"], body.mode, caller.subject)
    except catalogue.AlreadyChosen as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except catalogue.PublicUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"{exc}; nothing was created")
    return _catalogue_answer(found["pid"], caller)


@router.post("/projects/{slug}/catalogue/update")
def update_catalogue(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    """An admin refreshes the project's private copy from the public catalogue."""
    found = _catalogue_project(slug, caller)
    if not caller.has_role(ADMIN_ROLE):
        raise HTTPException(status_code=403, detail="updating the catalogue takes an admin")
    try:
        return _private_reads(found["pid"], lambda: catalogue.update(found["pid"], token_from_headers(request.headers) or ""))
    except catalogue.PublicUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"{exc}; nothing was changed")


@router.get("/projects/{slug}/catalogue/api/tool/")
def catalogue_tools(slug: str, request: Request, detailed: bool = False,
                    caller: Caller = Depends(caller_dependency)) -> list:
    """The copy's tools, then the local ones, in the public catalogue's own shapes."""
    pid = _catalogue_project(slug, caller)["pid"]
    token = token_from_headers(request.headers) or ""
    return jsonable_encoder(_private_reads(pid, lambda: catalogue.tools(pid, token, detailed)))


@router.get("/projects/{slug}/catalogue/api/tool/{tool_id}/tags/")
def catalogue_tool_tags(slug: str, tool_id: int, request: Request,
                        caller: Caller = Depends(caller_dependency)) -> list:
    """One entry's tags, for the detail pop-up when an entry came without them."""
    pid = _catalogue_project(slug, caller)["pid"]
    token = token_from_headers(request.headers) or ""
    try:
        return jsonable_encoder(_private_reads(pid, lambda: catalogue.tool_tags(pid, tool_id, token)))
    except catalogue.NoEntry as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/projects/{slug}/catalogue/api/tool/{entry}/install-info")
def catalogue_install_info(slug: str, entry: str, request: Request,
                           caller: Caller = Depends(caller_dependency)) -> dict:
    """Whether this stack's package index has the entry's plugin, and its newest version there."""
    pid = _catalogue_project(slug, caller)["pid"]
    token = token_from_headers(request.headers) or ""
    try:
        return _private_reads(pid, lambda: catalogue.install_info(pid, entry, token))
    except catalogue.NoEntry as exc:
        raise HTTPException(status_code=404, detail=str(exc))


#: What an install of a test says to someone without the realm role admin, as the engine's own dialog does.
NOT_ADMIN_TO_INSTALL = "Installing a test takes the admin role."


@router.post("/projects/{slug}/catalogue/api/tool/{entry}/install")
def catalogue_install_test(slug: str, entry: str, request: Request,
                           caller: Caller = Depends(caller_dependency)) -> dict:
    """Install the entry's test into this project without leaving the catalogue, as a
    control already is. The catalogue's pages are on this API's origin, so the call is
    same-origin; the engine is called with the caller's own token, so it checks the admin role again and
    records the install as its own."""
    from platform_service import engine_components
    pid = _catalogue_project(slug, caller)["pid"]
    if not caller.has_role(ADMIN_ROLE):
        raise HTTPException(status_code=403, detail=NOT_ADMIN_TO_INSTALL)
    token = token_from_headers(request.headers) or ""
    try:
        info = _private_reads(pid, lambda: catalogue.install_info(pid, entry, token))
    except catalogue.NoEntry as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not info["installable"]:
        raise HTTPException(status_code=409, detail=info["reason"])
    version = info["version"]
    if info["fetched_on_install"]:
        repo = info["source"].removeprefix("lux-ai-factory/")
        # published before it is installed, never the other way round; published but not installed is reusable
        try:
            version = publisher.publish(repo, info["package_name"])["version"]
        except publisher.PublisherError as exc:
            raise HTTPException(status_code=502, detail=f"could not fetch {repo}: {exc}; nothing was installed")
    try:
        if info["fetched_on_install"]:
            # The engine installs only what it has listed since the package reached the index: its
            # plugin loader keeps that list in memory and only its package list refreshes it. The list
            # read above came before the publish, so it is read again, and must now hold this version.
            # Names compare as PEP 503 does and versions as PEP 440 does (1.0.0-rc1 is 1.0.0rc1);
            # the engine is then given the version as it lists it.
            listed = engine_components.available_plugins(pid, token)
            seen = next((p for p in listed
                         if catalogue._dist(p.get("package_name") or "") == catalogue._dist(info["package_name"])
                         and catalogue._same_version(str(p.get("version") or ""), version)), None)
            if seen is None:
                raise HTTPException(status_code=502, detail=(
                    f"could not fetch {repo}: the engine does not see {info['package_name']} {version} "
                    "after publishing; nothing was installed"))
            version = seen["version"]
        engine_components.install_plugin(pid, token, info["package_name"], version, entry)
    except engine_components.EngineUnavailable as exc:
        if exc.status == 403:
            raise HTTPException(status_code=403, detail=NOT_ADMIN_TO_INSTALL)
        if exc.status == 404:
            raise no_project(slug)
        raise HTTPException(status_code=502, detail=f"{exc}; nothing was installed")
    return {"slug": entry, "package_name": info["package_name"], "version": version}


@router.get("/projects/{slug}/catalogue/api/tags/")
def catalogue_tags(slug: str, caller: Caller = Depends(caller_dependency)) -> list:
    pid = _catalogue_project(slug, caller)["pid"]
    return _private_reads(pid, lambda: catalogue.tags(pid))


@router.get("/projects/{slug}/catalogue/api/metric/")
def catalogue_metrics(slug: str, caller: Caller = Depends(caller_dependency)) -> list:
    pid = _catalogue_project(slug, caller)["pid"]
    return _private_reads(pid, lambda: catalogue.metrics(pid))


@router.get("/projects/{slug}/catalogue/api/metadata/")
def catalogue_metadata(slug: str, caller: Caller = Depends(caller_dependency)) -> list:
    pid = _catalogue_project(slug, caller)["pid"]
    return _private_reads(pid, lambda: catalogue.metadata(pid))


@router.get("/projects/{slug}/catalogue/api/project-dimensions")
def catalogue_project_dimensions(slug: str, caller: Caller = Depends(caller_dependency)) -> list:
    """The catalogue's dimension tags of the project's selected control objectives."""
    pid = _catalogue_project(slug, caller)["pid"]
    return _private_reads(pid, lambda: (catalogue._chosen(pid), catalogue.project_dimensions(pid))[1])


@router.get("/projects/{slug}/catalogue/control/{control}/export")
def catalogue_control_export(slug: str, control: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """The checklist package of one control of the project's catalogue, which the controls app installs:
    from the copy for a private project, the public catalogue's export for a public one.
    `slug` may be the project's pid, as the controls app names it."""
    pid = _catalogue_project(slug, caller)["pid"]
    try:
        return _private_reads(pid, lambda: catalogue.control_package(pid, control))
    except catalogue.NoEntry as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/projects/{slug}/catalogue/local/{package}/dimensions")
def put_local_dimensions(slug: str, package: str, body: LocalDimensionsIn,
                         caller: Caller = Depends(caller_dependency)) -> dict:
    """An admin gives a local entry its dimensions (REQ1 to REQ11)."""
    found = _catalogue_project(slug, caller)
    if not caller.has_role(ADMIN_ROLE):
        raise HTTPException(status_code=403, detail="classifying a local plugin takes an admin")
    try:
        dims = _private_reads(found["pid"], lambda: catalogue.set_local_dimensions(found["pid"], package, body.dimensions))
    except catalogue.InvalidDimensions as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"package_name": package, "dimensions": dims}
