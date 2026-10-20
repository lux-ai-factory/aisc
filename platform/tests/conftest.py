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

def _test_database_url() -> str:
    """PLATFORM_TEST_DATABASE_URL, a throwaway database; never the stack's own PLATFORM_DATABASE_URL and no
    default, so a shell that runs the stack can't point these tests at it. A URL on port 5432 (the running
    stack's PostgreSQL) is refused. Empty: the database tests skip."""
    from urllib.parse import urlsplit

    url = os.environ.get("PLATFORM_TEST_DATABASE_URL", "")
    try:
        port = urlsplit(url).port
    except ValueError:
        return ""
    return "" if not url or port in (None, 5432) else url


DSN = _test_database_url()
ISSUER = "http://keycloak:8080/realms/aisc"


def _database_up() -> bool:
    if not DSN:
        return False
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
    superuser = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
    for pid in pids:
        try:
            projectdb.drop(DSN, pid)
        except psycopg.errors.InsufficientPrivilege:
            # another role's session was still closing; platform_rw may not end it, the superuser may
            if not superuser:
                raise
            projectdb.drop(superuser, pid)


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


#: The owner of a test project unless a test says otherwise.
ALICE = "00000000-0000-0000-0000-00000000a11c"


@pytest.fixture
def admin(as_user):
    """Headers for a platform admin."""
    return as_user("root", roles=("admin",))


@pytest.fixture
def make_project(client, as_user, unique):
    """make_project(owner=ALICE, editors=(), viewers=()) -> the project as POST /projects answers it,
    made by `owner` (who owns it), with the given members added by the owner."""
    def make(owner=ALICE, editors=(), viewers=(), prefix="proj"):
        made = client.post("/projects", json={"name": unique(prefix)}, headers=as_user(owner))
        assert made.status_code == 201, made.text
        body = made.json()
        for role, subjects in (("editor", editors), ("viewer", viewers)):
            for subject in subjects:
                added = client.post(f"/projects/{body['slug']}/members", json={"subject": subject, "role": role},
                                    headers=as_user(owner))
                assert added.status_code in (200, 201), added.text
        return body
    return make


@pytest.fixture
def project(make_project):
    """A project Alice made, so Alice owns it and nobody else is in it."""
    return make_project()


def project_db(dsn, project, role=None, **kwargs):
    """A connection to a project's own database (`project` is the project or its pid), as the dsn's
    user or, autocommit, as `role` (whose password is its name in the throwaway)."""
    import psycopg
    from psycopg.conninfo import make_conninfo

    from platform_service import projectdb

    name = projectdb.database_name(project["pid"] if isinstance(project, dict) else project)
    if role is None:
        return psycopg.connect(make_conninfo(dsn, dbname=name), **kwargs)
    return psycopg.connect(make_conninfo(dsn, dbname=name, user=role, password=role), autocommit=True)


def one(dsn, project, statement, params=()):
    """The first row of `statement` in a project's own database."""
    with project_db(dsn, project) as conn:
        return conn.execute(statement, params).fetchone()
