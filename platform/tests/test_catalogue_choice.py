"""A project's catalogue, public or private, chosen once (docs/superpowers/local-catalogue-2026-10-03/01-specs.md
P1 to P4). The public catalogue is a stub serving a trimmed real sample of it (tests/fixtures/
public_catalogue_sample.json, read 2026-10-03); the engine's plugin list is a stub too."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from platform_service import catalogue as cat
from tests.conftest import needs_database
from tests.connection_support import Stub
from tests.test_evidence import ALICE, BOB, VERA, _reader, catalogue, project, sql  # noqa: F401

pytestmark = needs_database
SAMPLE = json.loads((Path(__file__).parent / "fixtures" / "public_catalogue_sample.json").read_text())
ADMIN = "00000000-0000-0000-0000-0000000ad111"
EXTRA = {"aisc_local", "aisc_installed"}


def public_routes(stub, sample):
    stub.route("GET", "/tool/", (200, sample["tool_detailed"]))
    stub.route("GET", "/tags/", (200, sample["tags"]))
    stub.route("GET", "/metric/", (200, sample["metric"]))
    stub.route("GET", "/metadata/", (200, sample["metadata"]))


@pytest.fixture
def public(monkeypatch):
    stub = Stub()
    public_routes(stub, SAMPLE)
    monkeypatch.setenv("CATALOGUE_URL", stub.base)
    yield stub
    stub.stop()


@pytest.fixture
def engine(monkeypatch):
    stub = Stub()
    stub.route("GET", "/api/v1/plugins", (200, [
        {"package_name": "aisc-plugin-langbite", "version": "0.1.0", "source": "registry"},
        {"package_name": "my-probe", "version": "0.2.0+local", "source": "local"},
    ]))
    monkeypatch.setenv("ENGINE_URL", stub.base)
    yield stub
    stub.stop()


def url(project, tail=""):
    return f"/projects/{project['slug']}/catalogue{tail}"


def admin(as_user):
    return as_user(ADMIN, ("primary-user", "admin"))


def choose(client, as_user, project, mode, who=ALICE):
    return client.post(url(project), json={"mode": mode}, headers=as_user(who))


def has_schema(dsn, project):
    return sql(dsn, project["pid"], "SELECT count(*) FROM pg_namespace WHERE nspname = 'catalogue'")[0][0] == 1


# ── P1 the choice ───────────────────────────────────────────────────────────

def test_p1_1_no_choice_yet_and_who_may_update(client, as_user, project, dsn):
    r = client.get(url(project), headers=as_user(VERA))
    assert r.status_code == 200 and r.json()["mode"] is None and r.json()["can_update"] is False
    assert client.get(url(project), headers=admin(as_user)).json()["can_update"] is True
    assert not has_schema(dsn, project)                       # P1.4


def test_p1_2_p1_3_public_is_recorded_once_and_is_final(client, as_user, project, dsn, public):
    assert choose(client, as_user, project, "public", BOB).status_code == 200
    assert client.get(url(project), headers=as_user(VERA)).json()["mode"] == "public"
    assert sql(dsn, project["pid"], "SELECT mode, chosen_by FROM catalogue.mode") == [("public", BOB)]
    again = choose(client, as_user, project, "private")
    assert again.status_code == 409
    assert not any(r["path"].startswith("/tool") for r in public.seen)   # public copies nothing


def test_p1_2_a_viewer_cannot_choose_and_nonsense_is_refused(client, as_user, project):
    assert choose(client, as_user, project, "public", VERA).status_code in (403, 404)
    assert choose(client, as_user, project, "shared").status_code == 422


def test_p1_3_private_makes_and_fills_the_copy(client, as_user, project, dsn, public, engine):
    r = choose(client, as_user, project, "private")
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "private" and r.json()["updated_at"]
    slugs = {t["slug"] for t in client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()}
    assert {t["slug"] for t in SAMPLE["tool_detailed"]} <= slugs


def test_p1_3_a_failed_copy_leaves_nothing_and_the_project_can_choose_again(client, as_user, project, dsn,
                                                                             monkeypatch, engine):
    down = Stub()
    monkeypatch.setenv("CATALOGUE_URL", down.base)            # no routes: every read is a 404
    r = choose(client, as_user, project, "private")
    down.stop()
    assert r.status_code == 503
    assert not has_schema(dsn, project)
    assert client.get(url(project), headers=as_user(ALICE)).json()["mode"] is None


# ── P2 the update ───────────────────────────────────────────────────────────

def test_p2_2_update_is_for_admins_and_refreshes_public_entries_keeping_local_ones(client, as_user, project,
                                                                                   public, engine):
    assert choose(client, as_user, project, "private").status_code == 200
    assert client.post(url(project, "/update"), headers=as_user(ALICE)).status_code == 403
    changed = copy.deepcopy(SAMPLE)
    gone = changed["tool_detailed"].pop()                     # removed upstream
    changed["tool_detailed"][0]["description"] = "rewritten upstream"
    added = copy.deepcopy(changed["tool_detailed"][0])
    added.update(id=999, slug="brand-new-tool", name="Brand new")
    changed["tool_detailed"].append(added)
    public.routes.clear()
    public_routes(public, changed)
    r = client.post(url(project, "/update"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1 and r.json()["updated"] == 1 and r.json()["removed"] == 1
    assert r.json()["unchanged"] == len(SAMPLE["tool_detailed"]) - 2 and r.json()["local_kept"] == 1
    tools = {t["slug"]: t for t in client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()}
    assert gone["slug"] not in tools and "brand-new-tool" in tools and "local-my-probe" in tools
    assert tools[changed["tool_detailed"][0]["slug"]]["description"] == "rewritten upstream"


def test_p2_2_update_with_the_public_catalogue_down_changes_nothing(client, as_user, project, public, engine):
    assert choose(client, as_user, project, "private").status_code == 200
    public.routes.clear()
    r = client.post(url(project, "/update"), headers=admin(as_user))
    assert r.status_code == 503
    assert len(client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()) >= len(SAMPLE["tool_detailed"])


# ── P3 the catalogue-shaped reads ───────────────────────────────────────────

def test_p3_1_p3_4_the_reads_have_the_public_shapes(client, as_user, project, public, engine):
    assert choose(client, as_user, project, "private").status_code == 200
    get = lambda tail: client.get(url(project, "/api/" + tail), headers=as_user(VERA)).json()
    detailed, plain = get("tool/?detailed=true"), get("tool/")
    public_detailed = set(SAMPLE["tool_detailed"][0])
    public_plain = set(SAMPLE["tool"][0])
    assert all(set(t) == public_detailed | EXTRA for t in detailed), "detailed tool shape"
    assert all(set(t) == public_plain | EXTRA for t in plain), "plain tool shape"
    assert all(set(t) == set(SAMPLE["tags"][0]) for t in get("tags/"))
    assert all(set(m) == set(SAMPLE["metric"][0]) for m in get("metric/"))
    assert all(set(m) == set(SAMPLE["metadata"][0]) for m in get("metadata/"))
    assert len(get("metric/")) == len(SAMPLE["metric"]) and len(get("metadata/")) >= len(SAMPLE["metadata"])


def test_p3_1_the_reads_refuse_writes(client, as_user, project, public):
    """A public project's reads answer too, live (test_catalogue_controls.py C2, plan 2026-10-04 D1)."""
    assert choose(client, as_user, project, "public").status_code == 200
    assert client.get(url(project, "/api/tool/"), headers=as_user(VERA)).status_code == 200
    assert client.post(url(project, "/api/tool/"), json={}, headers=as_user(ALICE)).status_code in (404, 405)


def test_p3_2_installed_is_said_per_entry(client, as_user, project, dsn, public, engine):
    assert choose(client, as_user, project, "private").status_code == 200
    control = next(t for t in SAMPLE["tool_detailed"] if (t.get("storage_path") or "").startswith("/controls/"))
    sql(dsn, project["pid"], "INSERT INTO controls.checklist (id, \"catalogueId\", title) VALUES ('ck9', %s, 'x')",
        (control["slug"],))
    tools = {t["slug"]: t for t in client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()}
    assert tools["langbite"]["aisc_installed"] is True        # aisc-plugin-langbite is in the engine table
    assert tools[control["slug"]]["aisc_installed"] is True
    assert tools["local-my-probe"]["aisc_local"] is True and tools["langbite"]["aisc_local"] is False


def test_p3_3_the_projects_dimensions_as_catalogue_tags(client, as_user, project, public, engine):
    """The project's latest card version selects O1 (R1) and O24 (R6) (test_evidence's fixture)."""
    assert choose(client, as_user, project, "private").status_code == 200
    got = client.get(url(project, "/api/project-dimensions"), headers=as_user(VERA)).json()
    assert got == ["human-agency-oversight", "societal-environmental-wellbeing"]


def test_p3_5_an_entrys_tags_by_its_id(client, as_user, project, public, engine):
    """The detail pop-up asks for an entry's tags by id when the entry came without them."""
    assert choose(client, as_user, project, "private").status_code == 200
    tools = client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()
    for t in (tools[0], next(t for t in tools if t["aisc_local"])):
        r = client.get(url(project, f"/api/tool/{t['id']}/tags/"), headers=as_user(VERA))
        assert r.status_code == 200 and r.json() == t["tags"], t["slug"]
    assert client.get(url(project, "/api/tool/987654321/tags/"), headers=as_user(VERA)).status_code == 404


INDEX_PAGE = (b'<html><body><a href="../../+f/1/aisc_plugin_langbite-0.1.0.tar.gz">aisc_plugin_langbite-0.1.0.tar.gz</a>'
              b'<a href="x">aisc_plugin_langbite-0.1.1-py3-none-any.whl</a>'
              b'<a href="y">aisc_plugin_langbite-0.2.0rc1.tar.gz</a></body></html>')


@pytest.fixture
def index(monkeypatch):
    """The stack's package index (devpi), which the engine installs from."""
    stub = Stub()
    stub.route("GET", "/root/public/+simple/aisc-plugin-langbite/", (200, INDEX_PAGE))
    stub.route("GET", "/root/public/+simple/ai-fairness-360/", (200, b"<html><body></body></html>"))
    # the index's own list of what it holds (PEP 503 root page)
    stub.route("GET", "/root/public/+simple/", (200, b'<html><body><a href="aisc-plugin-langbite/">aisc-plugin-langbite</a>'
                                                     b'<a href="my_probe/">my_probe</a></body></html>'))
    monkeypatch.setenv("PACKAGE_REGISTRY_URL", stub.base)
    monkeypatch.setenv("PACKAGE_REGISTRY_INDEX", "root/public")
    yield stub
    stub.stop()


def test_p3_6_install_info_is_answered_from_the_stacks_own_index(client, as_user, project, public, engine, index):
    """The public catalogue's install-info shape, but what decides is this stack's index: the newest
    release it serves, the pre-release only when nothing else is there."""
    assert choose(client, as_user, project, "private").status_code == 200
    info = lambda slug: client.get(url(project, f"/api/tool/{slug}/install-info"), headers=as_user(VERA))
    r = info("langbite")
    assert r.status_code == 200, r.text
    assert r.json() == {"slug": "langbite", "package_name": "aisc-plugin-langbite", "version": "0.1.1",
                        "index_url": f"{index.base}/root/public/+simple/", "installable": True, "reason": None}
    local = info("local-my-probe").json()                    # an engine package the index doesn't serve
    assert local["package_name"] == "my-probe" and local["installable"] is False
    assert local["reason"] == "my-probe is not on this stack's package index"


def test_p3_6_an_entry_without_package_name_uses_its_storage_path_like_the_public_catalogue(
        client, as_user, project, public, engine, index):
    """Like the real ai-fairness-360 entry (2026-10-04): no package_name, storage_path /packages/<name>."""
    sample = copy.deepcopy(SAMPLE)
    unnamed = copy.deepcopy(next(t for t in sample["tool_detailed"] if t["slug"] == "langbite"))
    unnamed.update(id=501, slug="ai-fairness-360", name="AI Fairness 360", package_name=None,
                   storage_path="/packages/ai-fairness-360")
    sample["tool_detailed"].append(unnamed)
    public_routes(public, sample)
    assert choose(client, as_user, project, "private").status_code == 200
    got = client.get(url(project, "/api/tool/ai-fairness-360/install-info"), headers=as_user(VERA)).json()
    assert got["package_name"] == "ai-fairness-360" and got["installable"] is False


def test_p3_6_install_info_of_no_entry_and_with_the_index_down(client, as_user, project, public, engine,
                                                              monkeypatch):
    assert choose(client, as_user, project, "private").status_code == 200
    down = Stub()
    monkeypatch.setenv("PACKAGE_REGISTRY_URL", down.base)
    assert client.get(url(project, "/api/tool/no-such-entry/install-info"), headers=as_user(VERA)).status_code == 404
    r = client.get(url(project, "/api/tool/langbite/install-info"), headers=as_user(VERA))
    down.stop()
    assert r.status_code == 200 and r.json()["installable"] is False      # nothing guessed


def test_p3_6_an_entry_the_public_catalogue_names_under_another_package_installs_as_the_published_one(
        client, as_user, project, dsn, public, engine, index, monkeypatch):
    """The public AgentDojo entry names package `agentdojo` (storage /packages/agentdojo, 2026-10-04); the
    repo publishes aisc-plugin-agentdojo. The stack's list says so: the rich entry installs, is marked
    installed, and the engine's package is not a second, bare Local entry."""
    sample = copy.deepcopy(SAMPLE)
    dojo = copy.deepcopy(next(t for t in sample["tool_detailed"] if t["slug"] == "langbite"))
    dojo.update(id=502, slug="agentdojo", name="AgentDojo", package_name=None, storage_path="/packages/agentdojo")
    sample["tool_detailed"].append(dojo)
    public_routes(public, sample)
    engine.route("GET", "/api/v1/plugins", (200, [
        {"package_name": "aisc-plugin-langbite", "version": "0.1.0", "source": "registry"},
        {"package_name": "aisc-plugin-agentdojo", "version": "0.1.0", "source": "registry"},
    ]))
    index.route("GET", "/root/public/+simple/aisc-plugin-agentdojo/",
                (200, b'<a href="z">aisc_plugin_agentdojo-0.1.0-py3-none-any.whl</a>'))
    assert choose(client, as_user, project, "private").status_code == 200
    sql(dsn, project["pid"], "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name)"
        " VALUES ('aisc-plugin-agentdojo', '0.1.0', 'AgentDojo')")
    got = client.get(url(project, "/api/tool/agentdojo/install-info"), headers=as_user(VERA)).json()
    assert got["package_name"] == "aisc-plugin-agentdojo" and got["version"] == "0.1.0" and got["installable"]
    tools = {t["slug"]: t for t in client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()}
    assert tools["agentdojo"]["aisc_installed"] is True
    assert "local-aisc-plugin-agentdojo" not in tools


def test_p3_7_a_test_is_ready_exactly_when_this_stacks_index_has_its_package(client, as_user, project, public,
                                                                             engine, index):
    """completion_status drives the card's colour and the Plugin available filter. In a private copy it
    says whether the test can be installed here: blue only then, pink otherwise, whatever the public
    catalogue says. Controls keep the public value."""
    sample = copy.deepcopy(SAMPLE)
    stub_here = copy.deepcopy(next(t for t in sample["tool_detailed"] if t["slug"] == "langbite"))
    stub_here.update(id=503, slug="probe-entry", name="Probe", package_name="my-probe", completion_status="stub")
    sample["tool_detailed"].append(stub_here)
    public_routes(public, sample)
    assert choose(client, as_user, project, "private").status_code == 200
    tools = {t["slug"]: t for t in client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()}
    assert tools["langbite"]["completion_status"] == "full"            # on the index
    assert tools["probe-entry"]["completion_status"] == "full"         # "stub" upstream, but installable here
    assert tools["snt-data-drift"]["completion_status"] == "stub"      # "full" upstream, data-monitor not here
    controls = [t for t in SAMPLE["tool_detailed"] if (t.get("storage_path") or "").startswith("/controls/")]
    for c in controls:
        assert tools[c["slug"]]["completion_status"] == c.get("completion_status")
    assert all(t["completion_status"] == "full" for t in tools.values() if t["aisc_local"])


def test_p3_7_with_the_index_down_the_public_values_stay(client, as_user, project, public, engine, monkeypatch):
    """Nothing known about the index: nothing is repainted."""
    down = Stub()
    monkeypatch.setenv("PACKAGE_REGISTRY_URL", down.base)
    assert choose(client, as_user, project, "private").status_code == 200
    tools = {t["slug"]: t for t in client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()}
    down.stop()
    for t in SAMPLE["tool_detailed"]:
        assert tools[t["slug"]]["completion_status"] == t.get("completion_status"), t["slug"]


def test_p3_5_p3_6_refused_for_a_project_that_has_not_chosen(client, as_user, project, public):
    """A public project answers them live (test_catalogue_controls.py C2); a project with no catalogue yet
    has nothing to answer from."""
    assert client.get(url(project, "/api/tool/1/tags/"), headers=as_user(VERA)).status_code == 409
    assert client.get(url(project, "/api/tool/langbite/install-info"), headers=as_user(VERA)).status_code == 409


# ── P4 local plugins ────────────────────────────────────────────────────────

def test_p4_1_a_package_not_in_the_public_catalogue_is_a_local_entry(client, as_user, project, public, engine):
    assert choose(client, as_user, project, "private").status_code == 200
    tools = client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()
    local = [t for t in tools if t["aisc_local"]]
    assert [t["package_name"] for t in local] == ["my-probe"]          # langbite is public, not local
    probe = local[0]
    assert probe["slug"] == "local-my-probe" and probe["version"] == "0.2.0+local"
    # this stack can install it, so it is ready: blue in the catalogue, kept by "Plugin available"
    assert probe["completion_status"] == "full"
    assert [g["slug"] for g in probe["tags"]] == ["source-local", "test"]   # not classified yet
    assert any(g["slug"] == "source-local" and g["section"] == "source"
               for g in client.get(url(project, "/api/tags/"), headers=as_user(VERA)).json())


def test_p4_2_an_admin_sets_a_local_entrys_dimensions(client, as_user, project, public, engine):
    assert choose(client, as_user, project, "private").status_code == 200
    put = lambda body, who: client.put(url(project, "/local/my-probe/dimensions"), json=body, headers=who)
    assert put({"dimensions": ["R5"]}, as_user(ALICE)).status_code == 403
    assert put({"dimensions": ["R12"]}, admin(as_user)).status_code == 422
    assert put({"dimensions": ["R5", "R2"]}, admin(as_user)).status_code == 200
    probe = next(t for t in client.get(url(project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()
                 if t["slug"] == "local-my-probe")
    assert {g["slug"] for g in probe["tags"] if g["section"] == "dimension"} == {
        "diversity-non-discrimination-fairness", "technical-robustness-safety"}


def test_unit_readiness_of_a_tool_entry_strips_to_the_plain_shape():
    plain = cat.plain_tool(SAMPLE["tool_detailed"][0])
    assert set(plain) == set(SAMPLE["tool"][0])
