"""A catalogue install the engine is slow to confirm is not reported as nothing installed.

The platform waits a fixed time for the engine's install call. When the engine takes longer, the platform
cannot know whether the install happened: the engine goes on with it after the platform stops waiting. The
answer must not say "nothing was installed"; it says the engine did not confirm in time. Runs on the throwaway;
the public catalogue, the engine and the index are local fakes, the engine one that finishes its install late.
"""
from __future__ import annotations

import time

from platform_service import engine_components
from tests.conftest import needs_database
from tests.test_catalogue_choice import (ENGINE_PID, admin, choose, engine, evidence_project, index,  # noqa: F401
                                         public, url)
from tests.test_evidence import _reader, catalogue  # noqa: F401  (fixtures)

pytestmark = needs_database


def test_an_install_the_engine_confirms_late_is_not_said_to_have_installed_nothing(
        client, as_user, evidence_project, public, engine, index, monkeypatch):  # noqa: F811
    installed = []

    def slow_install(seen):
        time.sleep(1.5)                       # the engine's install outlasts the platform's wait, then completes
        installed.append(seen.json["package_name"])
        return (201, {"ok": True})

    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine.route("POST", f"/api/v1/projects/for-platform/{evidence_project['pid']}",
                 (200, {"pid": ENGINE_PID, "name": "evd"}))
    engine.route("POST", "/api/v1/plugins", slow_install)
    # the install's own wait (a test's install has the worker read its manifest, so it is long), cut short here
    monkeypatch.setattr(engine_components, "INSTALL_TIMEOUT_S", 0.5)

    r = client.post(url(evidence_project, "/api/tool/langbite/install"), headers=admin(as_user))
    time.sleep(1.5)
    assert installed == ["aisc-plugin-langbite"], "the fake engine did not finish its install"
    detail = str(r.json().get("detail", ""))
    assert "nothing was installed" not in detail, (
        f"the person is told nothing was installed ({r.status_code}: {detail}) while the engine installed it")
    assert r.status_code == 504 and "did not confirm" in detail, (r.status_code, detail)


def test_an_engine_that_cannot_be_reached_still_installed_nothing(
        client, as_user, evidence_project, public, engine, index, monkeypatch):  # noqa: F811
    """Nothing was sent, so nothing was installed: that answer stays."""
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine.route("POST", f"/api/v1/projects/for-platform/{evidence_project['pid']}",
                 (200, {"pid": ENGINE_PID, "name": "evd"}))
    monkeypatch.setenv("ENGINE_URL", "http://127.0.0.1:9")      # nothing listens on the discard port
    r = client.post(url(evidence_project, "/api/tool/langbite/install"), headers=admin(as_user))
    assert r.status_code == 502 and "nothing was installed" in str(r.json().get("detail", "")), r.text
