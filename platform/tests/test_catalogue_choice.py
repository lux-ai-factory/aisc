"""A project's catalogue, public or private, chosen once. The public catalogue is a stub serving a trimmed
real sample of it (tests/fixtures/public_catalogue_sample.json, which names its source); the engine's plugin list is
a stub too."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from platform_service import catalogue as cat
from platform_service import publisher as publisher_client
from tests.conftest import needs_database
from tests.http_stub import Canned, Stub, _canned, closed_port_url
from tests.test_evidence import ALICE, BOB, VERA, _reader, catalogue, evidence_project, sql  # noqa: F401

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


# ── the choice ──────────────────────────────────────────────────────────────

def test_no_choice_yet_and_who_may_update(client, as_user, evidence_project, dsn):
    r = client.get(url(evidence_project), headers=as_user(VERA))
    assert r.status_code == 200 and r.json()["mode"] is None and r.json()["can_update"] is False
    assert client.get(url(evidence_project), headers=admin(as_user)).json()["can_update"] is True
    assert not has_schema(dsn, evidence_project)


def test_public_is_recorded_once_and_is_final(client, as_user, evidence_project, dsn, public):
    assert choose(client, as_user, evidence_project, "public", BOB).status_code == 200
    assert client.get(url(evidence_project), headers=as_user(VERA)).json()["mode"] == "public"
    assert sql(dsn, evidence_project["pid"], "SELECT mode, chosen_by FROM catalogue.mode") == [("public", BOB)]
    again = choose(client, as_user, evidence_project, "private")
    assert again.status_code == 409
    assert not any(r["path"].startswith("/tool") for r in public.seen)   # public copies nothing


def test_a_viewer_cannot_choose_and_nonsense_is_refused(client, as_user, evidence_project):
    assert choose(client, as_user, evidence_project, "public", VERA).status_code in (403, 404)
    assert choose(client, as_user, evidence_project, "shared").status_code == 422


def test_private_makes_and_fills_the_copy(client, as_user, evidence_project, dsn, public, engine):
    r = choose(client, as_user, evidence_project, "private")
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "private" and r.json()["updated_at"]
    slugs = {t["slug"] for t in client.get(url(evidence_project, "/api/tool/?detailed=true"),
                                           headers=as_user(VERA)).json()}
    assert {t["slug"] for t in SAMPLE["tool_detailed"]} <= slugs


def test_a_failed_copy_leaves_nothing_and_the_project_can_choose_again(client, as_user, evidence_project, dsn,
                                                                             monkeypatch, engine):
    down = Stub()
    monkeypatch.setenv("CATALOGUE_URL", down.base)            # no routes: every read is a 404
    r = choose(client, as_user, evidence_project, "private")
    down.stop()
    assert r.status_code == 503
    assert not has_schema(dsn, evidence_project)
    assert client.get(url(evidence_project), headers=as_user(ALICE)).json()["mode"] is None


# ── the update ──────────────────────────────────────────────────────────────

def test_update_is_for_admins_and_refreshes_public_entries_keeping_local_ones(client, as_user, evidence_project,
                                                                                   public, engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    assert client.post(url(evidence_project, "/update"), headers=as_user(ALICE)).status_code == 403
    changed = copy.deepcopy(SAMPLE)
    gone = changed["tool_detailed"].pop()                     # removed upstream
    changed["tool_detailed"][0]["description"] = "rewritten upstream"
    added = copy.deepcopy(changed["tool_detailed"][0])
    added.update(id=999, slug="brand-new-tool", name="Brand new")
    changed["tool_detailed"].append(added)
    public.routes.clear()
    public_routes(public, changed)
    r = client.post(url(evidence_project, "/update"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 1 and r.json()["updated"] == 1 and r.json()["removed"] == 1
    assert r.json()["unchanged"] == len(SAMPLE["tool_detailed"]) - 2 and r.json()["local_kept"] == 1
    tools = {t["slug"]: t for t in client.get(url(evidence_project, "/api/tool/?detailed=true"),
                                              headers=as_user(VERA)).json()}
    assert gone["slug"] not in tools and "brand-new-tool" in tools and "local-my-probe" in tools
    assert tools[changed["tool_detailed"][0]["slug"]]["description"] == "rewritten upstream"


def test_update_with_the_public_catalogue_down_changes_nothing(client, as_user, evidence_project, public, engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    public.routes.clear()
    r = client.post(url(evidence_project, "/update"), headers=admin(as_user))
    assert r.status_code == 503
    assert len(client.get(url(evidence_project, "/api/tool/?detailed=true"),
                          headers=as_user(VERA)).json()) >= len(SAMPLE["tool_detailed"])


# ── the catalogue-shaped reads ──────────────────────────────────────────────

def test_the_reads_have_the_public_shapes(client, as_user, evidence_project, public, engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    def get(tail):
        return client.get(url(evidence_project, "/api/" + tail), headers=as_user(VERA)).json()

    detailed, plain = get("tool/?detailed=true"), get("tool/")
    public_detailed = set(SAMPLE["tool_detailed"][0])
    public_plain = set(SAMPLE["tool"][0])
    assert all(set(t) == public_detailed | EXTRA for t in detailed), "detailed tool shape"
    assert all(set(t) == public_plain | EXTRA for t in plain), "plain tool shape"
    assert all(set(t) == set(SAMPLE["tags"][0]) for t in get("tags/"))
    assert all(set(m) == set(SAMPLE["metric"][0]) for m in get("metric/"))
    assert len(get("metric/")) == len(SAMPLE["metric"])


def test_the_reads_refuse_writes(client, as_user, evidence_project, public):
    """A public project's reads answer too, live (see test_catalogue_controls.py)."""
    assert choose(client, as_user, evidence_project, "public").status_code == 200
    assert client.get(url(evidence_project, "/api/tool/"), headers=as_user(VERA)).status_code == 200
    assert client.post(url(evidence_project, "/api/tool/"), json={}, headers=as_user(ALICE)).status_code in (404, 405)


def test_installed_is_said_per_entry(client, as_user, evidence_project, dsn, public, engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    control = next(t for t in SAMPLE["tool_detailed"] if (t.get("storage_path") or "").startswith("/controls/"))
    sql(dsn, evidence_project["pid"],
        "INSERT INTO controls.checklist (id, \"catalogueId\", title) VALUES ('ck9', %s, 'x')",
        (control["slug"],))
    tools = {t["slug"]: t for t in client.get(url(evidence_project, "/api/tool/?detailed=true"),
                                              headers=as_user(VERA)).json()}
    assert tools["langbite"]["aisc_installed"] is True        # aisc-plugin-langbite is in the engine table
    assert tools[control["slug"]]["aisc_installed"] is True
    assert tools["local-my-probe"]["aisc_local"] is True and tools["langbite"]["aisc_local"] is False


def test_the_projects_dimensions_as_catalogue_tags(client, as_user, evidence_project, public, engine):
    """The project's latest card version selects O1 (REQ1) and O24 (REQ6) (test_evidence's fixture)."""
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = client.get(url(evidence_project, "/api/project-dimensions"), headers=as_user(VERA)).json()
    assert got == ["human-agency-oversight", "societal-environmental-wellbeing"]


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


PUBLISHER_TOKEN = "publisher-token-for-tests"
SOURCES = {
    "aisc-plugin-langbite": {"repo": "aisc-plugin-langbite", "branch": "feat/unified-modules",
                             "package": "aisc-plugin-langbite", "version": "0.1.1"},
    "aisc-plugin-data-evaluation": {"repo": "aisc-plugin-data-evaluation", "branch": "main",
                                    "package": "data-monitor", "version": "0.3.1"},
}


def source_route(stub, repo, answer):
    stub.route("GET", f"/sources/{repo}", answer)


@pytest.fixture
def publisher(monkeypatch):
    """The plugin publisher, which reads a test's source on GitHub and publishes it to the index. By
    default langbite's source is at the version the index holds, data-monitor's is not on the index,
    and a publish answers the source's version as just published."""
    stub = Stub()
    for repo, found in SOURCES.items():
        source_route(stub, repo, (200, found))
    stub.route("POST", "/publish", lambda seen: (200, {
        "package": seen.json["package"], "version": SOURCES[seen.json["repo"]]["version"], "published": True}))
    monkeypatch.setenv("PLUGIN_PUBLISHER_URL", stub.base)
    monkeypatch.setenv("PLUGIN_PUBLISHER_TOKEN", PUBLISHER_TOKEN)
    yield stub
    stub.stop()


def test_install_info_is_answered_from_the_stacks_own_index(client, as_user, evidence_project, public, engine,
                                                                 index, publisher):
    """The public catalogue's install-info shape, but what decides is this stack's index: the newest
    release it serves, the pre-release only when nothing else is there."""
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    def info(slug):
        return client.get(url(evidence_project, f"/api/tool/{slug}/install-info"), headers=as_user(VERA))

    r = info("langbite")
    assert r.status_code == 200, r.text
    assert r.json() == {"slug": "langbite", "package_name": "aisc-plugin-langbite", "version": "0.1.1",
                        "index_url": f"{index.base}/root/public/+simple/", "installable": True, "reason": None,
                        "fetched_on_install": False, "source": "lux-ai-factory/aisc-plugin-langbite"}
    local = info("local-my-probe").json()                    # an engine package from local_plugins/
    assert local == {"slug": "local-my-probe", "package_name": "my-probe", "version": "0.2.0",
                     "index_url": f"{index.base}/root/public/+simple/", "installable": True, "reason": None,
                     "fetched_on_install": True, "source": "local_plugins"}


def test_an_entry_without_package_name_uses_its_storage_path_like_the_public_catalogue(
        client, as_user, evidence_project, public, engine, index):
    """Like the real ai-fairness-360 entry: no package_name, storage_path /packages/<name>."""
    sample = copy.deepcopy(SAMPLE)
    unnamed = copy.deepcopy(next(t for t in sample["tool_detailed"] if t["slug"] == "langbite"))
    unnamed.update(id=501, slug="ai-fairness-360", name="AI Fairness 360", package_name=None,
                   storage_path="/packages/ai-fairness-360")
    sample["tool_detailed"].append(unnamed)
    public_routes(public, sample)
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = client.get(url(evidence_project, "/api/tool/ai-fairness-360/install-info"), headers=as_user(VERA)).json()
    assert got["package_name"] == "ai-fairness-360" and got["installable"] is False


def test_install_info_of_no_entry_and_with_the_index_down(client, as_user, evidence_project, public, engine,
                                                              monkeypatch):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    down = Stub()
    monkeypatch.setenv("PACKAGE_REGISTRY_URL", down.base)
    assert client.get(url(evidence_project, "/api/tool/no-such-entry/install-info"),
                      headers=as_user(VERA)).status_code == 404
    r = client.get(url(evidence_project, "/api/tool/langbite/install-info"), headers=as_user(VERA))
    down.stop()
    # nothing guessed: no version, and neither index nor source answered, so only the publish can say
    assert r.status_code == 200 and r.json()["version"] is None and r.json()["fetched_on_install"] is True


def test_an_entry_the_public_catalogue_names_under_another_package_installs_as_the_published_one(
        client, as_user, evidence_project, dsn, public, engine, index, monkeypatch):
    """The public AgentDojo entry names package `agentdojo` (storage /packages/agentdojo); the
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
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    sql(dsn, evidence_project["pid"], "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name)"
        " VALUES ('aisc-plugin-agentdojo', '0.1.0', 'AgentDojo')")
    got = client.get(url(evidence_project, "/api/tool/agentdojo/install-info"), headers=as_user(VERA)).json()
    assert got["package_name"] == "aisc-plugin-agentdojo" and got["version"] == "0.1.0" and got["installable"]
    tools = {t["slug"]: t for t in client.get(url(evidence_project, "/api/tool/?detailed=true"),
                                              headers=as_user(VERA)).json()}
    assert tools["agentdojo"]["aisc_installed"] is True
    assert "local-aisc-plugin-agentdojo" not in tools


def test_a_test_is_ready_exactly_when_this_stacks_index_has_its_package(client, as_user, evidence_project, public,
                                                                             engine, index):
    """completion_status drives the card's colour and the Plugin available filter. In a private copy it
    says whether the test can be installed here, from the index or from its lux-ai-factory source: blue
    only then, pink otherwise, whatever the public catalogue says. Controls keep the public value."""
    sample = copy.deepcopy(SAMPLE)
    stub_here = copy.deepcopy(next(t for t in sample["tool_detailed"] if t["slug"] == "langbite"))
    stub_here.update(id=503, slug="probe-entry", name="Probe", package_name="my-probe", completion_status="stub")
    sample["tool_detailed"].append(stub_here)
    nowhere = copy.deepcopy(stub_here)
    nowhere.update(id=504, slug="nowhere-entry", name="Nowhere", package_name="nowhere-tool", completion_status="full")
    sample["tool_detailed"].append(nowhere)
    public_routes(public, sample)
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    tools = {t["slug"]: t for t in client.get(url(evidence_project, "/api/tool/?detailed=true"),
                                              headers=as_user(VERA)).json()}
    assert tools["langbite"]["completion_status"] == "full"            # on the index
    assert tools["probe-entry"]["completion_status"] == "full"         # "stub" upstream, but installable here
    assert tools["snt-data-drift"]["completion_status"] == "full"      # not on the index, but fetched on install
    assert tools["nowhere-entry"]["completion_status"] == "stub"       # "full" upstream, no index and no source
    controls = [t for t in SAMPLE["tool_detailed"] if (t.get("storage_path") or "").startswith("/controls/")]
    for c in controls:
        assert tools[c["slug"]]["completion_status"] == c.get("completion_status")
    assert all(t["completion_status"] == "full" for t in tools.values() if t["aisc_local"])


def test_with_the_index_down_the_public_values_stay(client, as_user, evidence_project, public, engine,
                                                         monkeypatch):
    """Nothing known about the index: nothing is repainted."""
    down = Stub()
    monkeypatch.setenv("PACKAGE_REGISTRY_URL", down.base)
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    tools = {t["slug"]: t for t in client.get(url(evidence_project, "/api/tool/?detailed=true"),
                                              headers=as_user(VERA)).json()}
    down.stop()
    for t in SAMPLE["tool_detailed"]:
        assert tools[t["slug"]]["completion_status"] == t.get("completion_status"), t["slug"]


def test_refused_for_a_project_that_has_not_chosen(client, as_user, evidence_project, public):
    """A public project answers them live (test_catalogue_controls.py); a project with no catalogue yet
    has nothing to answer from."""
    assert client.get(url(evidence_project, "/api/tags/"), headers=as_user(VERA)).status_code == 409
    assert client.get(url(evidence_project, "/api/tool/langbite/install-info"),
                      headers=as_user(VERA)).status_code == 409


# ── local plugins ───────────────────────────────────────────────────────────

def test_a_package_not_in_the_public_catalogue_is_a_local_entry(client, as_user, evidence_project, public, engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    tools = client.get(url(evidence_project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()
    local = [t for t in tools if t["aisc_local"]]
    assert [t["package_name"] for t in local] == ["my-probe"]          # langbite is public, not local
    probe = local[0]
    assert probe["slug"] == "local-my-probe" and probe["version"] == "0.2.0+local"
    # this stack can install it, so it is ready: blue in the catalogue, kept by "Plugin available"
    assert probe["completion_status"] == "full"
    assert [g["slug"] for g in probe["tags"]] == ["source-local", "test"]   # not classified yet
    assert any(g["slug"] == "source-local" and g["section"] == "source"
               for g in client.get(url(evidence_project, "/api/tags/"), headers=as_user(VERA)).json())


def test_an_admin_sets_a_local_entrys_dimensions(client, as_user, evidence_project, public, engine):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    def put(body, who):
        return client.put(url(evidence_project, "/local/my-probe/dimensions"), json=body, headers=who)

    assert put({"dimensions": ["REQ5"]}, as_user(ALICE)).status_code == 403
    assert put({"dimensions": ["REQ12"]}, admin(as_user)).status_code == 422
    assert put({"dimensions": ["REQ5", "REQ2"]}, admin(as_user)).status_code == 200
    probe = next(t for t in client.get(url(evidence_project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()
                 if t["slug"] == "local-my-probe")
    assert {g["slug"] for g in probe["tags"] if g["section"] == "dimension"} == {
        "diversity-non-discrimination-fairness", "technical-robustness-safety"}


def test_unit_readiness_of_a_tool_entry_strips_to_the_plain_shape():
    plain = cat.plain_tool(SAMPLE["tool_detailed"][0])
    assert set(plain) == set(SAMPLE["tool"][0])


# ── a test installed from the project's catalogue, without leaving it ─────────────────────────────────
# The catalogue's pages are on the launcher's origin, as this API is: the install is a same-origin call,
# and the platform makes it in the engine with the caller's own token, so the engine checks the admin role
# and records the install as if they had used the engine.

ENGINE_PID = "33333333-3333-3333-3333-333333333333"


def engine_takes_installs(engine, project, status=201):
    engine.route("POST", f"/api/v1/projects/for-platform/{project['pid']}", (200, {"pid": ENGINE_PID, "name": "evd"}))
    engine.route("POST", "/api/v1/plugins", (status, {"detail": "refused"} if status >= 300 else {"ok": True}))


def engine_like_the_real_one(engine, publisher, project, sees_published=True):
    """The engine as it behaves: it installs only a package==version it has listed since that package
    reached the index (its loader keeps the list in memory and only GET /api/v1/plugins refreshes it;
    anything else is its 500, a KeyError in load_package). The publisher's current /publish answer is
    wrapped so a successful publish puts the package on the index. `order` records publish, list and
    install as they happen."""
    order = []
    on_index = [("aisc-plugin-langbite", v) for v in ("0.1.0", "0.1.1", "0.2.0rc1")]
    listed = set()
    answers = list(publisher.routes[("POST", "/publish")])

    def publish(seen):
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        canned = _canned(answer, seen)
        order.append("publish")
        if canned.status == 200:
            body = json.loads(canned.body)
            if sees_published:
                on_index.append((body["package"], body["version"]))
        return canned

    def available(seen):
        order.append("list")
        listed.clear()
        listed.update(on_index)
        return (200, [{"package_name": p, "version": v, "source": "registry"} for p, v in on_index]
                + [{"package_name": "my-probe", "version": "0.2.0+local", "source": "local"}])

    def install(seen):
        order.append("install")
        if (seen.json["package_name"], seen.json["version"]) not in listed:
            return (500, {"detail": "Internal Server Error"})
        return (201, {"ok": True})

    publisher.route("POST", "/publish", publish)
    engine.route("GET", "/api/v1/plugins", available)
    engine.route("POST", f"/api/v1/projects/for-platform/{project['pid']}", (200, {"pid": ENGINE_PID, "name": "evd"}))
    engine.route("POST", "/api/v1/plugins", install)
    return order


def test_a_test_is_installed_from_the_catalogue_into_its_project(client, as_user, evidence_project, public, engine,
                                                                 index):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_takes_installs(engine, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/langbite/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert r.json() == {"slug": "langbite", "package_name": "aisc-plugin-langbite", "version": "0.1.1"}
    sent = engine.requests("POST", "/api/v1/plugins")[-1]
    assert sent["json"] == {"package_name": "aisc-plugin-langbite", "version": "0.1.1",
                            "project_uuid": ENGINE_PID, "catalogue_slug": "langbite"}
    assert sent["headers"]["x-aisc-project"] == evidence_project["pid"]
    assert sent["headers"]["authorization"].startswith("Bearer ")


def test_installing_a_test_from_the_catalogue_takes_the_admin_role(client, as_user, evidence_project, public, engine,
                                                                   index):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_takes_installs(engine, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/langbite/install"), headers=as_user(BOB))
    assert r.status_code == 403 and r.json()["detail"] == "Installing a test takes the admin role."
    assert engine.requests("POST", "/api/v1/plugins") == []


def local_publish(publisher, version="0.2.0", status=200):
    """The publisher's answer to publishing my-probe from local_plugins/."""
    publisher.route("POST", "/publish", (status, {"package": "my-probe", "version": version, "published": True}
                                         if status == 200 else {"detail": "no folder in local_plugins builds the package my-probe"}))


def test_a_plugin_of_local_plugins_is_published_from_its_folder_then_installed(
        client, as_user, evidence_project, public, engine, index, publisher):
    """my-probe is in local_plugins/ only: Install has the publisher build it from there and put it on the
    index, then the engine installs that version from the index (never the +local listing)."""
    local_publish(publisher)
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    order = engine_like_the_real_one(engine, publisher, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/local-my-probe/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert r.json() == {"slug": "local-my-probe", "package_name": "my-probe", "version": "0.2.0"}
    assert order[-3:] == ["publish", "list", "install"]
    assert publisher.requests("POST", "/publish")[-1].json == {"local": True, "package": "my-probe"}
    assert engine.requests("POST", "/api/v1/plugins")[-1]["json"]["version"] == "0.2.0"


def test_a_plugin_of_local_plugins_the_publisher_cannot_build_is_not_installed(
        client, as_user, evidence_project, public, engine, index, publisher):
    local_publish(publisher, status=404)
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_like_the_real_one(engine, publisher, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/local-my-probe/install"), headers=admin(as_user))
    assert r.status_code == 502, r.text
    assert "local_plugins" in r.json()["detail"] and "nothing was installed" in r.json()["detail"]
    assert all(req["json"].get("package_name") != "my-probe" for req in engine.requests("POST", "/api/v1/plugins"))


def test_a_local_plugin_whose_name_is_not_normalised_is_one_entry_and_installs_the_index_build(
        client, as_user, evidence_project, public, engine, index, publisher):
    """The index stores names normalised: the folder's my_probe (0.2.0+local) comes back from it as my-probe
    (0.2.0). One Local entry, and the engine is asked for the index build under the name it lists it by."""
    on_index = []
    publisher.route("POST", "/publish", lambda seen: (on_index.append(1), (200, {"package": "my_probe", "version": "0.2.0",
                                                                                "published": True}))[1])
    engine.route("GET", "/api/v1/plugins", lambda seen: (200, [{"package_name": "my_probe", "version": "0.2.0+local", "source": "local"}]
                                                         + ([{"package_name": "my-probe", "version": "0.2.0", "source": "registry"}] if on_index else [])))
    engine_takes_installs(engine, evidence_project)
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    r = client.post(url(evidence_project, "/api/tool/local-my_probe/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    sent = engine.requests("POST", "/api/v1/plugins")[-1]["json"]
    assert (sent["package_name"], sent["version"]) == ("my-probe", "0.2.0")
    tools = client.get(url(evidence_project, "/api/tool/?detailed=true"), headers=as_user(VERA)).json()
    assert [t["slug"] for t in tools if t.get("aisc_local") and "probe" in t["slug"]] == ["local-my_probe"]


def test_a_local_entry_only_on_the_index_installs_from_the_index_without_publishing(
        client, as_user, evidence_project, public, engine, index, publisher):
    """A package someone put on the index by hand (no folder in local_plugins/) installs as before."""
    index.route("GET", "/root/public/+simple/my-probe/", (200, b'<html><body><a href="x">my_probe-0.2.0-py3-none-any.whl</a></body></html>'))
    engine.route("GET", "/api/v1/plugins", (200, [{"package_name": "my-probe", "version": "0.2.0", "source": "registry"}]))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    info = install_info_of(client, as_user, evidence_project, "local-my-probe")
    assert (info["installable"], info["fetched_on_install"], info["version"], info["source"]) == (True, False, "0.2.0", None)


# ── a test whose package the index lacks is fetched from its source when it is installed ─────────────

def install_info_of(client, as_user, project, slug):
    r = client.get(url(project, f"/api/tool/{slug}/install-info"), headers=as_user(VERA))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_test_not_on_the_index_but_with_a_source_is_installable_and_fetched_on_install(
        client, as_user, evidence_project, public, engine, index, publisher):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = install_info_of(client, as_user, evidence_project, "snt-data-drift")
    assert got["package_name"] == "data-monitor" and got["version"] == "0.3.1"
    assert got["installable"] is True and got["reason"] is None
    assert got["fetched_on_install"] is True and got["source"] == "lux-ai-factory/aisc-plugin-data-evaluation"
    assert [s.path for s in publisher.seen] == ["/sources/aisc-plugin-data-evaluation"]   # read, not published


def test_a_test_on_the_index_at_the_source_version_is_not_fetched(client, as_user, evidence_project, public, engine,
                                                                 index, publisher):
    """An existing install whose index already holds the plugin: it installs with no publish."""
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = install_info_of(client, as_user, evidence_project, "langbite")
    assert got["version"] == "0.1.1" and got["installable"] and got["fetched_on_install"] is False
    engine_takes_installs(engine, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/langbite/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert publisher.requests("POST") == []
    assert engine.requests("POST", "/api/v1/plugins")[-1]["json"]["version"] == "0.1.1"


def test_a_source_newer_than_the_index_is_fetched_on_install(client, as_user, evidence_project, public, engine,
                                                             index, publisher):
    source_route(publisher, "aisc-plugin-langbite", (200, {**SOURCES["aisc-plugin-langbite"], "version": "0.2.0"}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = install_info_of(client, as_user, evidence_project, "langbite")
    assert got["version"] == "0.2.0" and got["installable"] and got["fetched_on_install"] is True


def test_the_publisher_down_falls_back_to_the_index_and_says_why(client, as_user, evidence_project, public, engine,
                                                                 index, monkeypatch):
    """No source can be read: what the index holds still installs from the index, what it lacks is left
    to the publish on install, and each answer names the repo it could not read. Never a 500, never the
    publisher's token."""
    monkeypatch.setenv("PLUGIN_PUBLISHER_URL", closed_port_url())
    monkeypatch.setenv("PLUGIN_PUBLISHER_TOKEN", PUBLISHER_TOKEN)
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    held = install_info_of(client, as_user, evidence_project, "langbite")
    assert held["version"] == "0.1.1" and held["installable"] is True and held["fetched_on_install"] is False
    assert "aisc-plugin-langbite" in held["reason"]
    # not on the index: still offered, the publish on install reads the version (and fails here)
    lacking = install_info_of(client, as_user, evidence_project, "snt-data-drift")
    assert lacking["installable"] is True and lacking["version"] is None and lacking["fetched_on_install"] is True
    assert "will be read on install" in lacking["reason"]
    assert "aisc-plugin-data-evaluation" in lacking["reason"] and PUBLISHER_TOKEN not in lacking["reason"]
    engine_takes_installs(engine, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 502, r.text
    assert r.json()["detail"].startswith("could not fetch aisc-plugin-data-evaluation: ")
    assert r.json()["detail"].endswith("; nothing was installed") and PUBLISHER_TOKEN not in r.text
    assert engine.requests("POST", "/api/v1/plugins") == []


def test_installing_publishes_first_then_calls_the_engine_with_the_published_version(
        client, as_user, evidence_project, public, engine, index, publisher):
    """The branch moved on between the read and the publish: the engine installs what was published,
    in one click, after it has listed the package that just reached the index."""
    publisher.route("POST", "/publish", (200, {"package": "data-monitor", "version": "0.3.2", "published": True}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    order = engine_like_the_real_one(engine, publisher, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert r.json() == {"slug": "snt-data-drift", "package_name": "data-monitor", "version": "0.3.2"}
    assert order[-3:] == ["publish", "list", "install"] and order.count("install") == 1
    sent = publisher.requests("POST", "/publish")[-1]
    assert sent.json == {"repo": "aisc-plugin-data-evaluation", "package": "data-monitor"}
    assert sent.header("X-AISC-Service-Token") == PUBLISHER_TOKEN
    assert engine.requests("POST", "/api/v1/plugins")[-1]["json"]["version"] == "0.3.2"


def test_an_engine_that_does_not_see_the_published_package_is_502_and_nothing_is_installed(
        client, as_user, evidence_project, public, engine, index, publisher):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    order = engine_like_the_real_one(engine, publisher, evidence_project, sees_published=False)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 502
    assert r.json()["detail"] == ("could not fetch aisc-plugin-data-evaluation: the engine does not see "
                                  "data-monitor 0.3.1 after publishing; nothing was installed")
    assert order[-2:] == ["publish", "list"] and "install" not in order


def test_the_engine_listing_a_published_version_under_its_canonical_spelling_installs_it(
        client, as_user, evidence_project, public, engine, index, publisher):
    """The publisher says the version as the pyproject spells it (0.3.2-rc1), the engine lists it as
    pip does (0.3.2rc1, data_monitor): the same release, so it installs, in the engine's spelling."""
    publisher.route("POST", "/publish", (200, {"package": "data-monitor", "version": "0.3.2-rc1",
                                               "published": True}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_takes_installs(engine, evidence_project)
    engine.route("GET", "/api/v1/plugins", (200, [
        {"package_name": "aisc-plugin-langbite", "version": "0.1.0", "source": "registry"},
        {"package_name": "data_monitor", "version": "0.3.2rc1", "source": "registry"},
    ]))
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    sent = engine.requests("POST", "/api/v1/plugins")[-1]["json"]
    assert sent["package_name"] == "data-monitor" and sent["version"] == "0.3.2rc1"


def test_a_test_installed_before_but_gone_from_the_index_is_published_again(
        client, as_user, evidence_project, dsn, public, engine, index, publisher):
    """The index's volume was wiped after the install: installing again fetches and publishes it again."""
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    sql(dsn, evidence_project["pid"], "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name)"
        " VALUES ('data-monitor', '0.3.1', 'Data monitor')")
    assert install_info_of(client, as_user, evidence_project, "snt-data-drift")["fetched_on_install"] is True
    engine_like_the_real_one(engine, publisher, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert len(publisher.requests("POST", "/publish")) == 1


def test_a_publish_that_finds_the_package_already_there_installs_normally(
        client, as_user, evidence_project, public, engine, index, publisher):
    publisher.route("POST", "/publish", (200, {"package": "data-monitor", "version": "0.3.1", "published": False}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_like_the_real_one(engine, publisher, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert engine.requests("POST", "/api/v1/plugins")[-1]["json"]["version"] == "0.3.1"


def test_a_publisher_failure_is_502_naming_the_repo_and_the_engine_is_not_called(
        client, as_user, evidence_project, public, engine, index, publisher):
    publisher.route("POST", "/publish", (502, {"detail": "build failed for aisc-plugin-data-evaluation: boom",
                                               "step": "build"}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_takes_installs(engine, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 502, r.text
    assert r.json()["detail"] == ("could not fetch aisc-plugin-data-evaluation: build failed for "
                                  "aisc-plugin-data-evaluation: boom; nothing was installed")
    assert engine.requests("POST", "/api/v1/plugins") == []


@pytest.mark.parametrize("unreadable", ["publisher error", "too slow"])
def test_a_source_that_cannot_be_read_is_still_published_then_installed(
        client, as_user, evidence_project, public, engine, index, publisher, monkeypatch, unreadable):
    """A slow source read, or a publisher that errors, does not stop an install: the publish fetches,
    checks the package and says the version, which the engine then installs."""
    if unreadable == "too slow":
        monkeypatch.setattr(publisher_client, "SOURCE_TIMEOUT_S", 0.3)
        source_route(publisher, "aisc-plugin-data-evaluation",
                     Canned(200, json.dumps(SOURCES["aisc-plugin-data-evaluation"]).encode(), delay=1.5))
    else:
        source_route(publisher, "aisc-plugin-data-evaluation", (503, {"detail": "busy"}))
    publisher.route("POST", "/publish", (200, {"package": "data-monitor", "version": "0.3.2", "published": True}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = install_info_of(client, as_user, evidence_project, "snt-data-drift")
    assert got["installable"] is True and got["fetched_on_install"] is True and got["version"] is None
    assert "aisc-plugin-data-evaluation" in got["reason"] and "will be read on install" in got["reason"]
    engine_like_the_real_one(engine, publisher, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "0.3.2"
    assert engine.requests("POST", "/api/v1/plugins")[-1]["json"]["version"] == "0.3.2"


def test_a_source_that_cannot_be_read_then_a_failed_publish_is_502_and_nothing_is_installed(
        client, as_user, evidence_project, public, engine, index, publisher):
    source_route(publisher, "aisc-plugin-data-evaluation", (503, {"detail": "busy"}))
    publisher.route("POST", "/publish", (502, {"detail": "could not clone aisc-plugin-data-evaluation: timeout"}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_takes_installs(engine, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 502
    assert r.json()["detail"] == ("could not fetch aisc-plugin-data-evaluation: could not clone "
                                  "aisc-plugin-data-evaluation: timeout; nothing was installed")
    assert engine.requests("POST", "/api/v1/plugins") == []


def test_a_source_the_publisher_cannot_find_and_the_index_lacks_is_not_installable(
        client, as_user, evidence_project, public, engine, index, publisher):
    """The publisher answers 404 for the repo (private with no GITHUB_TOKEN, or no such repo): no
    install can succeed, so none is offered, and the install is a 409 that publishes nothing."""
    source_route(publisher, "aisc-plugin-data-evaluation", (404, {"detail": "could not clone"}))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = install_info_of(client, as_user, evidence_project, "snt-data-drift")
    assert got["installable"] is False and got["fetched_on_install"] is False and got["version"] is None
    assert got["reason"].startswith("data-monitor is not in this installation's package index; ")
    assert "lux-ai-factory/aisc-plugin-data-evaluation" in got["reason"]
    assert "private" in got["reason"] and "GITHUB_TOKEN" in got["reason"] and "env.secrets" in got["reason"]
    engine_takes_installs(engine, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/snt-data-drift/install"), headers=admin(as_user))
    assert r.status_code == 409 and r.json()["detail"] == got["reason"]
    assert publisher.requests("POST") == [] and engine.requests("POST", "/api/v1/plugins") == []


def test_a_local_entry_is_never_replaced_by_a_github_source(client, as_user, evidence_project, public, engine,
                                                            index, publisher):
    """A local entry is this stack's own build: even under an aisc-plugin-* name it is not fetched."""
    engine.route("GET", "/api/v1/plugins", (200, [
        {"package_name": "aisc-plugin-langbite", "version": "0.1.0", "source": "registry"},
        {"package_name": "aisc-plugin-homegrown", "version": "0.1.0+local", "source": "local"},
    ]))
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = install_info_of(client, as_user, evidence_project, "local-aisc-plugin-homegrown")
    assert got["source"] == "local_plugins" and got["fetched_on_install"] is True and got["installable"] is True
    publisher.route("POST", "/publish", (200, {"package": "aisc-plugin-homegrown", "version": "0.1.0", "published": True}))
    engine_takes_installs(engine, evidence_project)
    client.post(url(evidence_project, "/api/tool/local-aisc-plugin-homegrown/install"), headers=admin(as_user))
    # published from its folder, never fetched from a lux-ai-factory repo of the same name
    assert [r.json for r in publisher.requests("POST", "/publish")] == [{"local": True, "package": "aisc-plugin-homegrown"}]
    assert publisher.requests("GET", "/sources/aisc-plugin-homegrown") == []


def test_a_package_without_a_source_and_not_on_the_index_is_still_409(client, as_user, evidence_project, public,
                                                                      engine, index, publisher):
    sample = copy.deepcopy(SAMPLE)
    nowhere = copy.deepcopy(next(t for t in sample["tool_detailed"] if t["slug"] == "langbite"))
    nowhere.update(id=505, slug="nowhere-entry", name="Nowhere", package_name="nowhere-tool")
    sample["tool_detailed"].append(nowhere)
    public_routes(public, sample)
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    got = install_info_of(client, as_user, evidence_project, "nowhere-entry")
    assert got["installable"] is False and got["source"] is None and got["fetched_on_install"] is False
    assert got["reason"] == "nowhere-tool is not in this installation's package index"
    engine_takes_installs(engine, evidence_project)
    r = client.post(url(evidence_project, "/api/tool/nowhere-entry/install"), headers=admin(as_user))
    assert r.status_code == 409 and r.json()["detail"] == "nowhere-tool is not in this installation's package index"
    assert publisher.seen == [] and engine.requests("POST", "/api/v1/plugins") == []


def test_an_entry_with_a_source_is_ready_without_asking_github(client, as_user, evidence_project, public, engine,
                                                               index, publisher):
    """The catalogue's colours come from the index and the table of sources alone: no publisher call."""
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    tools = {t["slug"]: t for t in client.get(url(evidence_project, "/api/tool/?detailed=true"),
                                              headers=as_user(VERA)).json()}
    assert tools["snt-data-drift"]["completion_status"] == "full"
    assert publisher.seen == []


def test_the_engines_refusal_is_passed_on(client, as_user, evidence_project, public, engine, index):
    assert choose(client, as_user, evidence_project, "private").status_code == 200
    engine_takes_installs(engine, evidence_project, status=403)
    r = client.post(url(evidence_project, "/api/tool/langbite/install"), headers=admin(as_user))
    assert r.status_code == 403 and r.json()["detail"] == "Installing a test takes the admin role."
    engine_takes_installs(engine, evidence_project, status=500)
    assert client.post(url(evidence_project, "/api/tool/langbite/install"), headers=admin(as_user)).status_code == 502
