"""A database and some tokens, for the tests that need them.

The membership rules are unit-tested without either. What cannot be: that the
queries actually filter, and that the API answers 404 rather than 403 to a
stranger. Those run against a real Postgres and skip when there is not one,
the same way the engine's Keycloak tests skip when Keycloak is not up.
"""
import os
import time
import uuid

import pytest

DSN = os.environ.get(
    "PLATFORM_TEST_DATABASE_URL",
    os.environ.get("PLATFORM_DATABASE_URL", "postgresql://platform_rw:platform_rw@127.0.0.1:5432/platform"),
)
ISSUER = "http://keycloak:8080/realms/aisc"


def _database_up() -> bool:
    try:
        import psycopg

        with psycopg.connect(DSN, connect_timeout=2):
            return True
    except Exception:
        return False


needs_database = pytest.mark.skipif(not _database_up(), reason="no platform database reachable")


@pytest.fixture(scope="session")
def dsn():
    return DSN


@pytest.fixture(autouse=True)
def _point_the_service_at_the_test_database(monkeypatch):
    monkeypatch.setenv("PLATFORM_DATABASE_URL", DSN)


#: Everything these tests create is named this way, and everything named this
#: way is deleted afterwards. The suite runs against the real database, so it
#: has to leave it as it found it, including after a run that crashed.
TEST_PREFIX = "pytest-"


@pytest.fixture
def unique():
    """A slug nobody else is using, and that the cleanup below recognises."""
    return lambda prefix="p": f"{TEST_PREFIX}{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="session", autouse=True)
def _leave_the_database_as_we_found_it():
    yield
    if not _database_up():
        return
    import psycopg

    from platform_service import projectdb

    with psycopg.connect(DSN) as conn:
        pids = [r[0] for r in conn.execute(
            "SELECT pid FROM core.project WHERE slug LIKE %s", (TEST_PREFIX + "%",)
        ).fetchall()]
        # members and systems follow their project: both are ON DELETE CASCADE.
        conn.execute("DELETE FROM core.project WHERE slug LIKE %s", (TEST_PREFIX + "%",))
        conn.commit()
    for pid in pids:
        projectdb.drop(DSN, pid)


@pytest.fixture(scope="session")
def key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def token(key):
    import jwt

    def make(subject, roles=("primary-user",), username=None):
        return jwt.encode(
            {
                "sub": subject,
                "email": f"{subject}@localhost",
                "preferred_username": username or subject,
                "iss": ISSUER,
                "exp": int(time.time()) + 300,
                "realm_access": {"roles": list(roles)},
            },
            key,
            algorithm="RS256",
        )

    return make


@pytest.fixture
def client(monkeypatch, key):
    """The API with authentication on, verifying against the test key."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/unused-in-tests")
    monkeypatch.setattr(
        "aisc_identity.service.key_for_jwks", lambda url: (lambda _t: key.public_key())
    )
    from platform_service.app import app

    return TestClient(app)


@pytest.fixture
def as_user(token):
    """Headers for a caller, the way the gateway sends them."""
    return lambda subject, roles=("primary-user",): {"Authorization": f"Bearer {token(subject, roles)}"}
