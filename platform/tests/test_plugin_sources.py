"""Which lux-ai-factory repo a test's package is built from, and the platform's client of the plugin
publisher, which fetches, builds and publishes that repo to this stack's package index."""
from __future__ import annotations

import pytest

from platform_service import plugin_sources, publisher
from tests.http_stub import Stub, closed_port_url

TOKEN = "publisher-token-for-tests"


def test_each_package_maps_to_its_repo():
    assert plugin_sources.repo_of("data-monitor") == "aisc-plugin-data-evaluation"
    assert plugin_sources.repo_of("explitest-plugin") == "aisc-plugin-explitest"
    assert plugin_sources.repo_of("fairness-awareness") == "aisc-plugin-fairness"
    assert plugin_sources.repo_of("predictive-insights") == "aisc-plugin-performance"
    assert plugin_sources.repo_of("aisc-plugin-langbite") == "aisc-plugin-langbite"
    assert plugin_sources.repo_of("my_probe") is None


def test_a_package_name_is_normalised_before_it_is_looked_up():
    assert plugin_sources.repo_of("Data_Monitor") == "aisc-plugin-data-evaluation"
    assert plugin_sources.repo_of("aisc_plugin_langbite") == "aisc-plugin-langbite"


@pytest.mark.parametrize("package", ["aisc-plugin-builder", "aisc-plugin-integrator", "aisc-plugin-interface",
                                     "aisc-plugin-manager", "aisc_plugin_interface"])
def test_the_plugin_tooling_has_no_source_to_install_from(package):
    assert plugin_sources.repo_of(package) is None


@pytest.mark.parametrize("package", ["aisc-plugin-", "aisc-plugin-x/../y", "aisc-plugin-" + "a" * 70, "agentdojo"])
def test_a_name_no_allowed_repo_could_have_has_no_source(package):
    assert plugin_sources.repo_of(package) is None


@pytest.fixture
def server(monkeypatch):
    stub = Stub()
    monkeypatch.setenv("PLUGIN_PUBLISHER_URL", stub.base)
    monkeypatch.setenv("PLUGIN_PUBLISHER_TOKEN", TOKEN)
    yield stub
    stub.stop()


def test_the_source_is_asked_with_the_service_token(server):
    server.route("GET", "/sources/aisc-plugin-langbite", (200, {
        "repo": "aisc-plugin-langbite", "branch": "feat/unified-modules", "package": "aisc-plugin-langbite",
        "version": "0.1.1"}))
    assert publisher.source("aisc-plugin-langbite")["version"] == "0.1.1"
    assert server.requests("GET")[-1].header("X-AISC-Service-Token") == TOKEN


def test_a_repo_the_publisher_cannot_read_has_no_source(server):
    server.route("GET", "/sources/aisc-plugin-gone", (404, {"detail": "clone failed"}))
    assert publisher.source("aisc-plugin-gone") is None


def test_a_publish_answers_the_published_version(server):
    server.route("POST", "/publish", (200, {"package": "data-monitor", "version": "0.3.2", "published": True}))
    assert publisher.publish("aisc-plugin-data-evaluation", "data-monitor") == {
        "package": "data-monitor", "version": "0.3.2", "published": True}
    sent = server.requests("POST", "/publish")[-1]
    assert sent.json == {"repo": "aisc-plugin-data-evaluation", "package": "data-monitor"}
    assert sent.header("X-AISC-Service-Token") == TOKEN


def test_a_refused_publish_carries_the_publishers_detail_and_never_the_token(server):
    server.route("POST", "/publish", (502, {"detail": "build failed for aisc-plugin-x: no pyproject.toml"}))
    with pytest.raises(publisher.PublisherError) as raised:
        publisher.publish("aisc-plugin-x", "aisc-plugin-x")
    assert "no pyproject.toml" in str(raised.value) and TOKEN not in str(raised.value)
    server.route("GET", "/sources/aisc-plugin-x", (401, {"detail": "a valid X-AISC-Service-Token is required"}))
    with pytest.raises(publisher.PublisherError) as raised:
        publisher.source("aisc-plugin-x")
    assert TOKEN not in str(raised.value)


def test_a_publisher_that_does_not_answer_is_an_error_without_its_credentials(monkeypatch):
    monkeypatch.setenv("PLUGIN_PUBLISHER_URL", closed_port_url().replace("http://", "http://user:secret@"))
    monkeypatch.setenv("PLUGIN_PUBLISHER_TOKEN", TOKEN)
    for call in (lambda: publisher.source("aisc-plugin-x"), lambda: publisher.publish("aisc-plugin-x", "aisc-plugin-x")):
        with pytest.raises(publisher.PublisherError) as raised:
            call()
        assert "secret" not in str(raised.value) and TOKEN not in str(raised.value)
        assert "not reachable" in str(raised.value)


def test_a_publisher_not_configured_is_an_error(monkeypatch):
    monkeypatch.delenv("PLUGIN_PUBLISHER_URL", raising=False)
    monkeypatch.setenv("PLUGIN_PUBLISHER_TOKEN", TOKEN)
    with pytest.raises(publisher.PublisherError, match="PLUGIN_PUBLISHER_URL"):
        publisher.source("aisc-plugin-x")
    monkeypatch.setenv("PLUGIN_PUBLISHER_URL", "http://plugin-publisher:8000")
    monkeypatch.delenv("PLUGIN_PUBLISHER_TOKEN", raising=False)
    with pytest.raises(publisher.PublisherError, match="PLUGIN_PUBLISHER_TOKEN"):
        publisher.publish("aisc-plugin-x", "aisc-plugin-x")


def test_the_waits_are_twenty_seconds_to_read_and_ten_minutes_to_publish():
    assert publisher.SOURCE_TIMEOUT_S == 20 and publisher.PUBLISH_TIMEOUT_S == 600


@pytest.mark.parametrize("call", ["source", "publish"])
def test_an_answer_that_is_not_json_is_unreadable(server, call):
    from tests.http_stub import Canned
    server.route("GET", "/sources/aisc-plugin-x", Canned(200, b"<html>proxy page</html>", {"Content-Type": "text/html"}))
    server.route("POST", "/publish", Canned(200, b"not json", {"Content-Type": "text/plain"}))
    with pytest.raises(publisher.PublisherError, match="^the plugin publisher answered something unreadable$"):
        publisher.source("aisc-plugin-x") if call == "source" else publisher.publish("aisc-plugin-x", "aisc-plugin-x")


@pytest.mark.parametrize("answer", [{"package": "aisc-plugin-x", "published": True}, ["0.1.0"],
                                    {"package": "aisc-plugin-x", "version": None, "published": True}])
def test_a_publish_answer_without_a_version_is_unreadable(server, answer):
    server.route("POST", "/publish", (200, answer))
    with pytest.raises(publisher.PublisherError, match="^the plugin publisher answered something unreadable$"):
        publisher.publish("aisc-plugin-x", "aisc-plugin-x")


def test_a_source_answer_that_is_not_an_object_is_unreadable(server):
    server.route("GET", "/sources/aisc-plugin-x", (200, ["aisc-plugin-x", "0.1.0"]))
    with pytest.raises(publisher.PublisherError, match="^the plugin publisher answered something unreadable$"):
        publisher.source("aisc-plugin-x")
