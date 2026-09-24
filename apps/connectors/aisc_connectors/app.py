"""The connectors service: admin routes, the gateway plugins call, and a health check."""
from fastapi import FastAPI

app = FastAPI(title="AISC connectors")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
