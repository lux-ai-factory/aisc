"""The connectors service: the admin routes and a health check."""
from fastapi import FastAPI

app = FastAPI(title="AISC connectors")

from aisc_connectors import routes_admin  # noqa: E402

app.include_router(routes_admin.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
