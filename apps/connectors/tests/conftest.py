"""A throwaway Postgres, a secrets key, tokens and clients, for the tests that need them.

The database is a `docker run --rm` container on a port the kernel picks, removed at the end.
It is never the live stack: a CONNECTORS_TEST_DATABASE_URL on port 5432 is refused.
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import time
import uuid

import psycopg
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
ISSUER = "http://keycloak:8080/realms/aisc"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def database_url():
    given = os.environ.get("CONNECTORS_TEST_DATABASE_URL")
    if given:
        assert ":5432/" not in given, "refusing a database on the live port 5432"
        yield given
        return
    name = f"aisc-t-connectors-{uuid.uuid4().hex[:8]}"
    port = _free_port()
    subprocess.run(
        ["docker", "run", "--rm", "-d", "--name", name, "-e", "POSTGRES_PASSWORD=pw",
         "-e", "POSTGRES_DB=platform", "-p", f"127.0.0.1:{port}:5432", "postgres:15-alpine"],
        check=True, capture_output=True,
    )
    try:
        superuser = f"postgresql://postgres:pw@127.0.0.1:{port}/platform"
        for _ in range(120):
            try:
                psycopg.connect(superuser, connect_timeout=1).close()
                break
            except psycopg.OperationalError:
                time.sleep(0.5)
        time.sleep(1)  # the image restarts once after initdb
        for _ in range(60):
            try:
                psycopg.connect(superuser, connect_timeout=1).close()
                break
            except psycopg.OperationalError:
                time.sleep(0.5)
        subprocess.run(
            ["docker", "exec", "-i", name, "psql", "-U", "postgres", "-d", "platform", "-v", "ON_ERROR_STOP=1"],
            input=(ROOT / "init" / "connectors-db.sql").read_bytes(), check=True, capture_output=True,
        )
        yield f"postgresql://connector_rw:connector_rw@127.0.0.1:{port}/platform"
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def secrets_key(monkeypatch):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CONNECTOR_SECRETS_KEY", key)
    return key


@pytest.fixture
def db(database_url, monkeypatch, secrets_key):
    monkeypatch.setenv("CONNECTORS_DATABASE_URL", database_url)
    from aisc_connectors import db as dbm

    dbm.reset_pool()
    pool = dbm.pool()
    yield pool
    with pool.connection() as conn:
        conn.execute("TRUNCATE connector.connector, connector.call_log CASCADE")
    dbm.reset_pool()


@pytest.fixture(scope="session")
def rsa_key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def as_user(rsa_key):
    """Headers for a caller, signed with the test key."""
    import jwt

    def make(subject="alice", roles=("admin",)):
        token = jwt.encode(
            {"sub": subject, "email": f"{subject}@localhost", "preferred_username": subject,
             "iss": ISSUER, "exp": int(time.time()) + 300, "realm_access": {"roles": list(roles)}},
            rsa_key, algorithm="RS256",
        )
        return {"Authorization": f"Bearer {token}"}

    return make


@pytest.fixture
def auth_on(monkeypatch, rsa_key):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/unused-in-tests")
    monkeypatch.setattr("aisc_identity.service.key_for_jwks", lambda url: (lambda _t: rsa_key.public_key()))
