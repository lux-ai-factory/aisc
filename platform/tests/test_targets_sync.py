"""Targets follow the AI card (targets plan v2, TG2 to TG5, TG9, TG10): the platform reads the
latest card version's graph from qualification with the caller's own token, takes the components
of its Components block (the nodes that carry qual:componentKey) and keeps one target per key,
mirrored in the engine. Runs on the throwaway; qualification and the engine are local fakes."""
from __future__ import annotations

import pytest

from tests.conftest import needs_database
from tests.connection_support import EngineFake, Stub

pytestmark = needs_database
ALICE = "00000000-0000-0000-0000-00000000a11c"
BOB = "00000000-0000-0000-0000-000000000b0b"
EVE = "00000000-0000-0000-0000-000000000e0e"
QUAL = "https://lux-ai-factory.github.io/qualification/ns#"
AIRO = "https://w3id.org/airo#"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
K1, K2, K3 = ("0b9c7a1e-0000-4000-8000-000000000001", "0b9c7a1e-0000-4000-8000-000000000002",
              "0b9c7a1e-0000-4000-8000-000000000003")


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.stop()


@pytest.fixture(autouse=True)
def _env(monkeypatch, stub):
    monkeypatch.setenv("ENGINE_URL", stub.base)
    monkeypatch.setenv("QUALIFICATION_URL", stub.base + "/qualification")


def jsonld(*components):
    """A card graph as qualification serves it: the system, and one node per Components-block row."""
    nodes = [{"@id": "urn:x#system", "@type": [AIRO + "AISystem"], RDFS_LABEL: [{"@value": "MCAS 1.2.0"}]}]
    for key, label, kind in components:
        cls = {"model": "AIModel", "training_data": "Data"}.get(kind, "AIComponent")
        nodes.append({"@id": f"urn:x#component-{key}", "@type": [AIRO + cls], RDFS_LABEL: [{"@value": label}],
                      QUAL + "componentKey": [{"@value": key}], QUAL + "kind": [{"@value": kind}]})
    # a positional extraction node of an older card carries no key: never a target
    nodes.append({"@id": "urn:x#component0", "@type": [AIRO + "AIComponent"], RDFS_LABEL: [{"@value": "Guess"}]})
    return nodes


def version(client, as_user, project, name="MCAS"):
    r = client.post(f"/projects/{project['slug']}/system-versions", json={"name": name, "version": "1.2.0"},
                    headers=as_user(ALICE))
    assert r.status_code == 201, r.text
    return r.json()


def card(stub, project, v, graph, status=200):
    stub.route("GET", f"/qualification/p/{project['pid']}/api/system-versions/{v['pid']}/ontology.jsonld",
               (status, graph))


@pytest.fixture
def project(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("sync")}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    return made.json()


def sync(client, as_user, project, who=ALICE):
    return client.post(f"/projects/{project['slug']}/targets/sync", headers=as_user(who))


def listed(client, as_user, project, who=ALICE):
    r = client.get(f"/projects/{project['slug']}/targets", headers=as_user(who))
    assert r.status_code == 200, r.text
    return r.json()


def by_key(d):
    return {t["key"]: t for t in d["targets"]}


# ── TG2 from the card ───────────────────────────────────────────────────────

def test_tg2_every_keyed_component_of_the_latest_card_becomes_a_target(client, as_user, project, stub):
    engine = EngineFake(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, jsonld((K1, "Scoring model", "model"), (K2, "Training data", "training_data")))
    r = sync(client, as_user, project)
    assert r.status_code == 200 and r.json()["reason"] is None, r.text
    t = by_key(r.json())
    assert set(t) == {"system", f"component:{K1}", f"component:{K2}"}
    assert t[f"component:{K1}"]["label"] == "Scoring model" and t[f"component:{K1}"]["component_kind"] == "model"
    assert t[f"component:{K2}"]["first_card_number"] == 1 and t[f"component:{K2}"]["status"] == "current"
    assert engine.named(f"target:{project['pid']}/component:{K2}")["name"] == \
        "Target · Component: Training data (training data)"


def test_tg2_the_callers_token_goes_to_qualification_both_ways(client, as_user, project, stub):
    EngineFake(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, jsonld((K1, "Scoring model", "model")))
    sync(client, as_user, project)
    call = stub.requests("GET", f"/qualification/p/{project['pid']}/api/system-versions/")[-1]
    token = as_user(ALICE)["Authorization"]
    assert call["headers"]["authorization"] == token
    assert call["headers"]["x-auth-request-access-token"] == token.split(" ", 1)[1]


def test_tg2_the_system_target_is_named_after_the_latest_card(client, as_user, project, stub):
    engine = EngineFake(stub, project["pid"])
    v1 = version(client, as_user, project, name="MicroCredit Assist Score")
    card(stub, project, v1, jsonld())
    t = by_key(sync(client, as_user, project).json())
    assert t["system"]["label"] == "MicroCredit Assist Score"
    assert engine.named(f"target:{project['pid']}/system")["name"] == "Target · System: MicroCredit Assist Score"


# ── TG3 and TG4 a later card ────────────────────────────────────────────────

def test_tg3_a_component_the_latest_card_no_longer_has_stays_flagged(client, as_user, project, stub):
    engine = EngineFake(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, jsonld((K1, "Scoring model", "model"), (K3, "Policy-rule engine", "rule_engine")))
    sync(client, as_user, project)
    v2 = version(client, as_user, project)
    card(stub, project, v2, jsonld((K1, "Scoring model", "model")))
    t = by_key(sync(client, as_user, project).json())
    gone = t[f"component:{K3}"]
    assert gone["status"] == "stale" and gone["last_card_number"] == 1
    assert engine.named(f"target:{project['pid']}/component:{K3}")["name"].endswith("(not in card v2)")
    assert t[f"component:{K1}"]["status"] == "current" and t[f"component:{K1}"]["last_card_number"] == 2


def test_tg4_a_renamed_component_is_the_same_target_renamed(client, as_user, project, stub):
    engine = EngineFake(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, jsonld((K1, "Scoring model", "model")))
    sync(client, as_user, project)
    mirror = engine.named(f"target:{project['pid']}/component:{K1}")["pid"]
    v2 = version(client, as_user, project)
    card(stub, project, v2, jsonld((K1, "Credit scoring model", "model")))
    t = by_key(sync(client, as_user, project).json())
    assert t[f"component:{K1}"]["label"] == "Credit scoring model" and t[f"component:{K1}"]["first_card_number"] == 1
    renamed = engine.named(f"target:{project['pid']}/component:{K1}")
    assert renamed["pid"] == mirror and renamed["name"].startswith("Target · Component: Credit scoring model")


# ── TG5 when the card cannot be read ────────────────────────────────────────

def test_tg5_no_card_yet_leaves_the_system_target_only(client, as_user, project, stub):
    EngineFake(stub, project["pid"])
    d = sync(client, as_user, project).json()
    assert set(by_key(d)) == {"system"} and d["reason"] is None


def test_tg5_qualification_down_leaves_the_targets_as_they_were_with_a_reason(client, as_user, project, stub):
    EngineFake(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, jsonld((K1, "Scoring model", "model")))
    sync(client, as_user, project)
    v2 = version(client, as_user, project)
    card(stub, project, v2, {"detail": "down"}, status=502)
    d = sync(client, as_user, project).json()
    assert "qualification" in d["reason"]
    assert by_key(d)[f"component:{K1}"]["last_card_number"] == 1


def test_tg5_a_version_without_a_card_adds_no_component(client, as_user, project, stub):
    EngineFake(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, {"detail": "no card"}, status=404)
    assert set(by_key(sync(client, as_user, project).json())) == {"system"}


# ── TG9 and TG10 who sees and who refreshes ─────────────────────────────────

def member(client, as_user, project, subject, role):
    r = client.post(f"/projects/{project['slug']}/members", json={"subject": subject, "role": role}, headers=as_user(ALICE))
    assert r.status_code == 201, r.text


def test_tg10_any_member_reads_the_targets_an_editor_refreshes_them_a_stranger_is_told_nothing(client, as_user, project, stub):
    EngineFake(stub, project["pid"])
    member(client, as_user, project, BOB, "viewer")
    assert set(by_key(listed(client, as_user, project, BOB))) == {"system"}
    assert sync(client, as_user, project, BOB).status_code == 403
    assert client.get(f"/projects/{project['slug']}/targets", headers=as_user(EVE)).status_code == 404
    assert sync(client, as_user, project, EVE).status_code == 404


def test_tg9_the_list_says_each_targets_status_and_mirror(client, as_user, project, stub):
    engine = EngineFake(stub, project["pid"])
    v1 = version(client, as_user, project)
    card(stub, project, v1, jsonld((K1, "Scoring model", "model")))
    sync(client, as_user, project)
    t = by_key(listed(client, as_user, project))
    assert t[f"component:{K1}"]["engine_component"] == engine.named(f"target:{project['pid']}/component:{K1}")["pid"]
    assert t["system"]["status"] == "current"
