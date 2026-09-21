"""The platform API: the projects every module will come to reference.

Authentication is the gateway's job. Every request that arrives here has already
been through Keycloak, and for now every account may see every project, so there
is no authorisation logic to get wrong. When that changes it changes here.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from psycopg import errors
from pydantic import BaseModel

from platform_service import db
from platform_service.projects import InvalidProject, normalise_name, slug_for, validate_slug
from platform_service.systems import InvalidSystem, system_key

app = FastAPI(title="AISC platform", docs_url="/docs")


class ProjectIn(BaseModel):
    name: str
    slug: str | None = None
    description: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/projects")
def projects() -> list[dict]:
    return db.list_projects()


@app.get("/projects/{slug}")
def project(slug: str) -> dict:
    found = db.get_project(slug)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no project {slug!r}")
    return found


@app.post("/projects", status_code=201)
def add_project(body: ProjectIn) -> dict:
    try:
        name = normalise_name(body.name)
        slug = validate_slug(body.slug) if body.slug else slug_for(name)
    except InvalidProject as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        return db.create_project(name, slug, body.description)
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"a project {slug!r} already exists")


class SystemIn(BaseModel):
    name: str
    version: str | None = None
    provider: str | None = None
    description: str | None = None


@app.get("/projects/{slug}/systems")
def systems(slug: str) -> list[dict]:
    if db.get_project(slug) is None:
        raise HTTPException(status_code=404, detail=f"no project {slug!r}")
    return db.list_systems(slug)


@app.post("/projects/{slug}/systems", status_code=201)
def register_system(slug: str, body: SystemIn) -> dict:
    """Name a system inside a project, or find the one already named.

    Qualification calls this when it starts describing a system and the engine
    when it runs tests against one: the same call either way, because the same
    name and version in the same project is the same system.
    """
    try:
        name, version = system_key(body.name, body.version)
    except InvalidSystem as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    found = db.register_system(slug, name, version, body.provider, body.description)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no project {slug!r}")
    return found


@app.get("/systems/{pid}")
def system(pid: str) -> dict:
    found = db.get_system(pid)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no system {pid}")
    return found


@app.exception_handler(InvalidProject)
def invalid_project(_, exc: InvalidProject) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(InvalidSystem)
def invalid_system(_, exc: InvalidSystem) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})
