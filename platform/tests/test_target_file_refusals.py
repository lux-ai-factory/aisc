"""A target file the engine refuses (too large, wrong type, empty) is refused with the engine's own status
and reason, not reported as an engine outage; and a target file is never named "." or "..". Runs on the
throwaway; the engine and qualification are local fakes."""
from __future__ import annotations

import pytest

from tests.conftest import needs_database
from tests.test_target_files import K1, _env, carded, stub, upload  # noqa: F401  (fixtures)

pytestmark = needs_database


@pytest.mark.parametrize("status", [413, 415, 422])
def test_an_engine_refusal_of_the_file_is_passed_on_not_502(client, admin, project, carded, stub, status):  # noqa: F811
    assert upload(client, project, f"component:{K1}", admin).status_code == 200
    made = carded.carrying(f"target:{project['pid']}/component:{K1}")[0]
    stub.route("PUT", f"/api/v1/components/{made['pid']}/data", (status, {"detail": "refused"}))
    r = upload(client, project, f"component:{K1}", admin, data=b"other", name="other.onnx")
    assert r.status_code == status, r.text
    assert "refused" in r.json()["detail"]


@pytest.mark.parametrize("name", [".", "..", " .. "])
def test_a_dot_name_is_refused(client, admin, project, carded, name):  # noqa: F811
    r = upload(client, project, f"component:{K1}", admin, name=name)
    assert r.status_code == 422, r.text
    assert carded.uploads == {}
