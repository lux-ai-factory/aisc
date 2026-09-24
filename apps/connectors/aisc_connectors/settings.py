"""Everything the service reads from its environment, read in one place."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    #: Comma-separated Fernet keys, newest first. Only this service holds them.
    secrets_key: str
    #: The engine's public API, called with the admin's own token.
    engine_api_url: str
    #: How plugins on the backend network reach this service.
    gateway_base_url: str
    max_response_bytes: int
    max_spec_bytes: int


def settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "CONNECTORS_DATABASE_URL", "postgresql://connector_rw:connector_rw@postgres:5432/platform"
        ),
        secrets_key=os.environ.get("CONNECTOR_SECRETS_KEY", ""),
        engine_api_url=os.environ.get("ENGINE_API_URL", "http://aisc-backend:8000/api/v1").rstrip("/"),
        gateway_base_url=os.environ.get("GATEWAY_BASE_URL", "http://connectors:8097").rstrip("/"),
        max_response_bytes=int(os.environ.get("CONNECTORS_MAX_RESPONSE_BYTES", str(20 * 1024 * 1024))),
        max_spec_bytes=int(os.environ.get("CONNECTORS_MAX_SPEC_BYTES", str(5 * 1024 * 1024))),
    )
