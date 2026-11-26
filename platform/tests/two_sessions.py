"""Two signed-in people on one project. Not a test module.

A race between two people cannot be reached by a test with one client, so a test that needs two loads the
fixture here (`from tests.two_sessions import two_editors  # noqa: F401`). Each person is a Session: its own
client on the platform's app and its own token, sent the way the gateway sends it (Authorization: Bearer).
The two share nothing but the project. Tests act in order, never at once: A opens, B opens, B saves, A saves.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import pytest

from tests.conftest import ALICE, ISSUER

#: the two people: (subject, display name)
PERSON_A = ("00000000-0000-0000-0000-0000000000ea", "Ada Session-A")
PERSON_B = ("00000000-0000-0000-0000-0000000000eb", "Bea Session-B")


@dataclass(frozen=True)
class Session:
    """One signed-in person in one browser."""
    #: the name the platform shows for this person (the token's `name` and `preferred_username`: the same
    #: text in both, so a test does not decide which of the two claims a display name is read from)
    name: str
    subject: str
    _client: object = field(repr=False)
    _token: str = field(repr=False)

    def _send(self, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {self._token}", **(kwargs.pop("headers", None) or {})}
        return self._client.request(method, path, headers=headers, **kwargs)

    def get(self, path: str, **kwargs):
        return self._send("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self._send("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self._send("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self._send("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self._send("DELETE", path, **kwargs)


@dataclass(frozen=True)
class TwoSessions:
    project: dict
    a: Session
    b: Session


def _token(key, subject: str, name: str, realm_roles) -> str:
    import jwt

    return jwt.encode({"sub": subject, "email": f"{subject}@localhost", "preferred_username": name, "name": name,
                       "iss": ISSUER, "exp": int(time.time()) + 300,
                       "realm_access": {"roles": list(realm_roles)}}, key, algorithm="RS256")


def _two_editors(client, key, make_project, realm_roles) -> TwoSessions:
    from fastapi.testclient import TestClient

    # `client` has set the app up (authentication on, the test key); each person gets a client of their own
    project = make_project(owner=ALICE, editors=(PERSON_A[0], PERSON_B[0]))
    a, b = (Session(name=name, subject=subject, _client=TestClient(client.app),
                    _token=_token(key, subject, name, realm_roles))
            for subject, name in (PERSON_A, PERSON_B))
    return TwoSessions(project=project, a=a, b=b)


@pytest.fixture
def two_editors(client, key, make_project) -> TwoSessions:
    """A project with two members who are both editors: `.project`, and the callers `.a` and `.b`."""
    return _two_editors(client, key, make_project, realm_roles=("primary-user",))


@pytest.fixture
def two_editors_who_administer(client, key, make_project) -> TwoSessions:
    """The same two editors, each also holding the realm's admin role: the platform lets only a platform
    admin save a connection (routes/admission.py ACTIONS, "connection.write")."""
    return _two_editors(client, key, make_project, realm_roles=("primary-user", "admin"))
