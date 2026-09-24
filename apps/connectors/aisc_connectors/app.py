"""The connectors service: admin routes, the gateway plugins call, and a health check."""
from fastapi import FastAPI

app = FastAPI(title="AISC connectors")

from aisc_connectors import routes_admin  # noqa: E402

app.include_router(routes_admin.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
