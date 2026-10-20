"""Every database connection the composer opens gives up after a bounded time (a test suite once hung
on this): psycopg.connect has no timeout of its own, so a server that accepts the connection and
never answers (a docker-proxy left behind a restarted daemon, a stuck Postgres) held a request, a
migration or a test forever. No database needed: a socket that accepts and stays silent."""
import socket
import threading

import psycopg
import pytest


@pytest.fixture
def silent_server():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(8)
    held = []

    def accept():
        while True:
            try:
                held.append(server.accept()[0])
            except OSError:
                return

    threading.Thread(target=accept, daemon=True).start()
    yield f"postgresql://u:p@127.0.0.1:{server.getsockname()[1]}/x"
    server.close()
    for c in held:
        c.close()


def gives_up(fn, seconds=15.0):
    """fn raises psycopg.OperationalError (or ApiError) within `seconds` instead of waiting forever."""
    out = {}

    def run():
        try:
            fn()
            out["result"] = "returned"
        except Exception as exc:  # noqa: BLE001
            out["result"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), "still waiting on a silent server"
    return out["result"]


@pytest.fixture(autouse=True)
def short(monkeypatch):
    from report_composer import db

    monkeypatch.setattr(db, "CONNECT_TIMEOUT_S", 2, raising=False)


def test_db_connect_gives_up(silent_server):
    from report_composer import db

    def go():
        with db.connect(silent_server):
            pass

    assert isinstance(gives_up(go), psycopg.OperationalError)


def test_a_project_database_connect_gives_up(silent_server):
    from report_composer.errors import ApiError
    from report_composer.projectdb import ProjectDatabases

    dbs = ProjectDatabases(silent_server.rsplit("/", 1)[0] + "/{database}", silent_server)
    result = gives_up(lambda: dbs._open("a1000000-0000-4000-8000-000000000001"))
    assert isinstance(result, ApiError) and result.status == 503


def test_the_migration_gives_up(silent_server):
    from report_composer.migrate import project_databases

    assert isinstance(gives_up(lambda: project_databases(silent_server)), psycopg.OperationalError)
