"""Shared pieces of the ledger tests (docs/superpowers/ledger-2026-10-02/04-test-plan.md, spec v2).

The ledger is written by the platform alone. The witness is called the way Caddy calls it, header for
header (06-spike.md G8): the gateway secret, the app named by the handle, the unstripped original URI,
the stripped X-Forwarded-Uri. Witness records live in the platform's Postgres; the relay copies them
and the apps' events into immudb. These tests use an in-memory ledger except the immudb store tests,
which need a throwaway immudb 1.11.1 (LEDGER_TEST_IMMUDB_URL, host:port, and its superuser password in
LEDGER_TEST_IMMUDB_ADMIN_PASSWORD). With LEDGER_TESTS_REQUIRED=1 a missing service fails instead of
skipping (spec section 9). Nothing here touches the live stack.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

IMMUDB_URL = os.environ.get("LEDGER_TEST_IMMUDB_URL")
IMMUDB_ADMIN_PASSWORD = os.environ.get("LEDGER_TEST_IMMUDB_ADMIN_PASSWORD")
SUPERUSER_DSN = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
REQUIRED = os.environ.get("LEDGER_TESTS_REQUIRED") == "1"

GATEWAY_SECRET = "test-gateway-secret-0123456789abcdef"
#: The master keys, versioned: per-project, per-purpose keys are derived from them (spec 6.1, N5).
LEDGER_KEYS = "v1:" + "a1" * 32
GATEWAY_CLIENT = "aisc-gateway"

OWNER = "00000000-0000-0000-0000-0000000000a1"
MEMBER = "00000000-0000-0000-0000-0000000000b2"
STRANGER = "00000000-0000-0000-0000-0000000000c3"

#: The site each app is served on, as X-Forwarded-Host shows it (port kept, G1).
HOSTS = {"launcher": "localhost:8100", "platform": "localhost:8100", "schema": "localhost:8100",
         "pgadmin": "localhost:8100", "dashboard": "localhost:8088"}
#: The prefix Caddy's handle_path strips before forward_auth runs (G1).
STRIPPED = {"control_objectives": "/control-objectives", "report_composer": "/report-composer",
            "platform": "/api", "schema": "/inspect/schema"}


def need(condition, reason: str):
    """Skip without a service, or fail when the run says every service is there (spec section 9)."""
    if not condition:
        if REQUIRED:
            pytest.fail(f"LEDGER_TESTS_REQUIRED=1 but {reason}")
        pytest.skip(reason)


def _database_up() -> bool:
    from tests.conftest import _database_up as up

    return up()


@pytest.fixture
def _database_required():
    need(_database_up(), "no platform database reachable (PLATFORM_TEST_DATABASE_URL)")


#: The ledger's own "needs a database": a fixture, so LEDGER_TESTS_REQUIRED=1 turns it into a failure.
#: The platform's `needs_database` is a collection-time skipif, which nothing can (second review 6.2).
needs_db = pytest.mark.usefixtures("_database_required")


#: What these tests made in the platform database, so the session can remove exactly that (third review
#: M4, fourth review 1). A row is deleted only if its id was recorded here: project ids, request ids,
#: the stores' server ids and the subjects of the tokens the tests made. Never a pattern on real data.
MADE: dict[str, set] = {"pids": set(), "requests": set(), "servers": set(), "subs": set()}

CLEANUP = [
    ("ledger.witness", "DELETE FROM ledger.witness WHERE request_id::text = ANY(%(requests)s)"
                       " OR project_pid::text = ANY(%(pids)s)"),
    ("ledger.actor", "DELETE FROM ledger.actor WHERE scope = ANY(%(pids)s)"
                     " OR (scope = 'platform' AND sub = ANY(%(subs)s))"),
    ("ledger.event_index", "DELETE FROM ledger.event_index WHERE project_pid::text = ANY(%(pids)s)"),
    ("ledger.page_view", "DELETE FROM ledger.page_view WHERE project_pid::text = ANY(%(pids)s)"),
    ("ledger.content", "DELETE FROM ledger.content WHERE project_pid::text = ANY(%(pids)s)"),
    ("core.outbox", "DELETE FROM core.outbox WHERE project_pid::text = ANY(%(pids)s)"
                    " OR request_id::text = ANY(%(requests)s)"),
    ("ledger.state", "DELETE FROM ledger.state WHERE db IN (SELECT db FROM ledger.pool"
                     " WHERE server_id = ANY(%(servers)s))"),
    ("ledger.pool", "DELETE FROM ledger.pool WHERE server_id = ANY(%(servers)s)"),
]


def remove_made(dsn: str, made: dict) -> list[str]:
    """Delete exactly what `made` names, one statement per transaction; returns the failures, so a
    caller can't miss them (fourth review 1)."""
    import psycopg

    params = {k: sorted(v) for k, v in made.items()}
    failures = []
    with psycopg.connect(dsn, connect_timeout=2, autocommit=True) as conn:
        for table, statement in CLEANUP:
            if not conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0]:
                continue                                            # not built yet
            try:
                conn.execute(statement, params)
            except Exception as exc:
                failures.append(f"{table}: {exc}")
    return failures


@pytest.fixture(scope="session", autouse=True)
def _remove_what_the_tests_made():
    yield
    import warnings

    from tests.conftest import DSN
    try:
        failures = remove_made(DSN, MADE)
    except Exception as exc:                                        # no database at all: nothing was made
        failures = [] if not any(MADE.values()) else [f"connect: {exc}"]
    for failure in failures:
        warnings.warn(f"ledger test cleanup left rows behind: {failure}")


@pytest.fixture(autouse=True)
def _ledger_settings(monkeypatch):
    monkeypatch.setenv("AISC_WITNESS_GATEWAY_SECRET", GATEWAY_SECRET)
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", LEDGER_KEYS)
    monkeypatch.setenv("AISC_GATEWAY_CLIENT_ID", GATEWAY_CLIENT)


@pytest.fixture
def settings():
    """The named settings (WINDOW, CLOCK_SKEW, ...): tests use them, never the numbers (R6.8)."""
    from platform_service.ledger import settings

    return settings


@pytest.fixture
def memory_ledger(_database_required):
    """The platform's ledger, in memory, for one test, with a small pool of databases made the way the
    operator's script makes them (spec 7.1). Pool rows name their server, so a later test's store is
    never handed this store's databases (second review N1). Projects are made after it."""
    from platform_service import ledger
    from platform_service.ledger import testing
    from platform_service.ledger.store import MemoryLedger

    store = MemoryLedger()
    MADE["servers"].add(store.server_id)
    testing.fill_pool(store, n=8)                  # creates the databases + the platform log, registers them
    previous = ledger.use(store)
    yield store
    ledger.use(previous)


@pytest.fixture
def own_store(memory_ledger):
    """own_store(n) -> a ledger with a pool of n databases, made current until the test ends. It
    depends on memory_ledger so it is torn down first and restores it in order (third review n-a)."""
    from platform_service import ledger
    from platform_service.ledger import testing
    from platform_service.ledger.store import MemoryLedger

    made = []

    def run(n):
        store = MemoryLedger()
        MADE["servers"].add(store.server_id)
        testing.fill_pool(store, n=n)
        made.append(ledger.use(store))
        return store
    yield run
    for previous in reversed(made):
        ledger.use(previous)


@pytest.fixture
def platform_dsn(_database_required, dsn):
    """The platform database's DSN, migrated first (the platform migrates on its first pool use, so a
    test reaching ledger.* directly must not depend on another test having done it)."""
    from platform_service import db

    db.pool()
    return dsn


def log_of(pid: str) -> str:
    """The immudb database a project's log lives in: looked up, never derived from the pid (N1)."""
    from platform_service.ledger import provision

    db = provision.database_for(pid)
    assert db, f"project {pid} has no ledger database"
    return db


def fresh_databases(n: int) -> list[str]:
    """New immudb databases made the way the operator's pool script makes them (spec 7.1), with
    aisc_ledger granted RW; unique per test, so a persistent server never shares them (R4.4)."""
    from platform_service.ledger import pool

    from platform_service.ledger.naming import pool_name

    names = [pool_name() for _ in range(n)]
    pool.create_databases(IMMUDB_URL, admin_password=IMMUDB_ADMIN_PASSWORD, names=names,
                          grantee="aisc_ledger", grantee_password=LEDGER_USER_PASSWORD)
    return names


LEDGER_USER_PASSWORD = "Ledger-test-pw-123!"


@pytest.fixture(params=["memory", "immudb"])
def any_store(request):
    """Each store test runs on both stores: the behaviour is the contract, not the backend. The immudb
    store logs in as aisc_ledger, never the superuser (R3.1). Returns (store, [db, db])."""
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger, MemoryLedger

    if request.param == "memory":
        store = MemoryLedger()
        dbs = ["ledger" + uuid.uuid4().hex, "ledger" + uuid.uuid4().hex]
        for db in dbs:
            store.create(db)                       # what the pool script does, in memory
        return store, dbs
    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD,
         "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set (a throwaway immudb 1.11.1)")
    dbs = fresh_databases(2)
    return ImmudbLedger(IMMUDB_URL, user="aisc_ledger", password=LEDGER_USER_PASSWORD,
                        state_store=MemoryStateStore()), dbs


@pytest.fixture
def mode(monkeypatch):
    """Set LEDGER_MODE for one test: mode('enforce')."""
    return lambda value: monkeypatch.setenv("LEDGER_MODE", value)


@pytest.fixture
def through_gateway(client, as_user, call_witness, gateway_token):
    """A platform API call as the launcher's gateway makes it, in whatever mode is set: the witness
    first (app `platform`, path `/api` + path), then the call citing the id it gave, if it gave one.
    Tests create their projects this way, so a test may set `enforce` before it has a project
    (second review N2): no route is exempt from the witness to make setup work."""
    def run(subject, method, path, **kwargs):
        w = call_witness(gateway_token(subject), method, "platform", "/api" + path)
        assert w.status_code == 200, w.text
        headers = as_user(subject)
        if "X-AISC-Request-Id" in w.headers:
            headers["X-AISC-Request-Id"] = w.headers["X-AISC-Request-Id"]
        return client.request(method, path, headers=headers, **kwargs)
    return run


@pytest.fixture
def make_project(memory_ledger, through_gateway, unique):
    """make_project(owner, editors=()) -> {"pid", "slug"}, made through the gateway."""
    def run(owner, editors=()):
        made = through_gateway(owner, "POST", "/projects", json={"name": unique("ledger")})
        assert made.status_code == 201, made.text
        p = made.json()
        MADE["pids"].add(p["pid"])
        for editor in editors:
            r = through_gateway(owner, "POST", f"/projects/{p['slug']}/members",
                                json={"subject": editor, "role": "editor"})
            assert r.status_code in (200, 201), r.text
        return {"pid": p["pid"], "slug": p["slug"]}
    return run


@pytest.fixture
def project(make_project):
    """A project owned by OWNER with MEMBER as editor: {"pid", "slug"}."""
    return make_project(OWNER, editors=(MEMBER,))


@pytest.fixture
def gateway_token(key):
    """A token as oauth2-proxy forwards it: issued to the gateway's client (azp)."""
    import jwt

    from tests.conftest import ISSUER

    def make(subject, *, username=None, roles=("primary-user",), **claims):
        MADE["subs"].add(subject)
        body = {"sub": subject, "email": f"{subject}@localhost", "preferred_username": username or subject,
                "iss": ISSUER, "azp": GATEWAY_CLIENT, "exp": int(time.time()) + 300,
                "realm_access": {"roles": list(roles)}}
        body.update(claims)
        return jwt.encode(body, key, algorithm="RS256")
    return make


def caddy_headers(token: str | None, method: str, app: str, original_uri: str, *, gateway=GATEWAY_SECRET,
                  bearer: str | None = None, project_header: str | None = None,
                  next_action: str | None = None) -> dict:
    """Exactly what Caddy's witness forward_auth sends to /authz/witness (06-spike.md G8)."""
    prefix = STRIPPED.get(app, "")
    stripped = original_uri[len(prefix):] if prefix and original_uri.startswith(prefix) else original_uri
    headers = {"X-Forwarded-Method": method, "X-Forwarded-Uri": stripped or "/",
               "X-Forwarded-Host": HOSTS.get(app, "localhost"), "X-Forwarded-Proto": "http",
               "X-AISC-App": app, "X-AISC-Original-Uri": original_uri}
    if gateway is not None:
        headers["X-AISC-Gateway"] = gateway
    if token is not None:
        headers["X-Auth-Request-Access-Token"] = token
    if bearer is not None:
        headers["Authorization"] = f"Bearer {bearer}"
    if project_header is not None:
        headers["X-AISC-Project"] = project_header
    if next_action is not None:
        headers["Next-Action"] = next_action
    return headers


def witness_path(original_uri: str) -> str:
    """forward_auth appends the client's query to the witness URI (G10)."""
    _, _, query = original_uri.partition("?")
    return "/authz/witness" + (f"?{query}" if query else "")


@pytest.fixture
def call_witness(client):
    """Call the witness the way Caddy does; returns the response."""
    def run(token, method, app, original_uri, **kw):
        r = client.get(witness_path(original_uri), headers=caddy_headers(token, method, app, original_uri, **kw))
        if "X-AISC-Request-Id" in r.headers:
            MADE["requests"].add(r.headers["X-AISC-Request-Id"])
        return r
    return run


@pytest.fixture
def witnessed(call_witness, gateway_token):
    """A request the witness accepted; returns the request id it gave."""
    def run(subject: str, method: str, app: str, original_uri: str, *, username: str | None = None, **kw) -> str:
        r = call_witness(gateway_token(subject, username=username), method, app, original_uri, **kw)
        assert r.status_code == 200, r.text
        request_id = r.headers.get("X-AISC-Request-Id")
        assert request_id and uuid.UUID(request_id)
        return request_id
    return run


def record(request_id: str):
    """The witness record of one request (platform Postgres, `ledger.witness`), or None."""
    from platform_service.ledger import witness

    return witness.record(request_id)


def person(pid: str | None, actor_ref: str | None):
    """Who an actor reference stands for, while the mapping exists: (sub, name) or None (I10)."""
    from platform_service.ledger import actors

    return actors.resolve(pid, actor_ref)


def relay_all(pid: str | None = None):
    from platform_service.ledger import relay

    return relay.relay_once(pid)


def entries(store, db: str) -> list:
    """Every entry of one ledger database, oldest first."""
    return store.scan(db, after_seq=0, limit=10_000)
