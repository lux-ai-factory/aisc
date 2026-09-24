"""The connectors service: the admin routes and a health check."""
from fastapi import FastAPI

from aisc_connectors import routes_admin

app = FastAPI(title="AISC connectors")
app.include_router(routes_admin.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
