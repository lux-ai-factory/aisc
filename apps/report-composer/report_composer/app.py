"""The report composer (report run 2026-09-23): step 7 of the platform.

    uvicorn report_composer.app:app --host 0.0.0.0 --port 8095 --proxy-headers
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import api, db, errors, pages
from .migrate import migrate
from .renderer_client import HttpRendererClient

STATIC = Path(__file__).resolve().parent / "static"


def create_app(*, database_url=None, renderer=None, clock=None) -> FastAPI:
    database_url = database_url or os.environ.get("REPORT_COMPOSER_DATABASE_URL", "")
    if renderer is None:
        renderer = HttpRendererClient(os.environ.get("REPORT_RENDERER_URL", "http://report-renderer:8001"),
                                      os.environ.get("REPORT_SERVICE_TOKEN", ""))
    clock = clock or (lambda: datetime.now(timezone.utc))

    @asynccontextmanager
    async def lifespan(app):
        with db.connect(database_url) as conn:
            migrate(conn)
        yield

    root_path = os.environ.get("REPORT_COMPOSER_ROOT_PATH", "")
    app = FastAPI(root_path=root_path, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(RestorePrefix, prefix=root_path)
    app.state.database_url = database_url
    app.state.renderer = renderer
    app.state.clock = clock
    errors.install(app)
    app.include_router(api.router)
    app.include_router(pages.router)
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
    return app


class RestorePrefix:
    """Caddy's handle_path strips /report-composer before the request reaches us. Starlette
    resolves routes and the static mount against the full path (root_path included), so a
    stripped /static/composer.css was a 404 and the pages came up unstyled. Put it back."""

    def __init__(self, app, prefix: str = ""):
        self.app, self.prefix = app, prefix.rstrip("/")

    async def __call__(self, scope, receive, send):
        if self.prefix and scope["type"] in ("http", "websocket") \
                and scope["path"] != self.prefix and not scope["path"].startswith(self.prefix + "/"):
            scope = dict(scope, path=self.prefix + scope["path"])
            if "raw_path" in scope and scope["raw_path"] is not None:
                scope["raw_path"] = self.prefix.encode() + scope["raw_path"]
        await self.app(scope, receive, send)


_app = None


def __getattr__(name):
    """`report_composer.app.app` for uvicorn, built on first access."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
