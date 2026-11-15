"""The index never has a version replaced: a version already there with other content is refused, naming
what to do, and nothing is uploaded; at start the interface is not replaced either. A publish names the
sha256 of the wheel it published, which the platform hands the engine at install."""
import hashlib
import logging

from plugin_publisher.service import Publisher

REPO = "aisc-plugin-demo"
PACKAGE = "aisc-plugin-demo"


def test_a_version_on_the_index_whose_content_changed_is_refused(client, github, index, build):
    github(REPO, {"main": (PACKAGE, "1.1.0")})
    index.versions[PACKAGE] = {"1.1.0"}
    index.files[(PACKAGE, "1.1.0")] = b"wheel"
    build.content = b"wheel v2"

    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})

    assert status == 409, body
    assert "give the plugin a new version" in body["detail"] and "nothing was published" in body["detail"]
    assert index.uploads == []
    assert index.files[(PACKAGE, "1.1.0")] == b"wheel"


def test_an_interface_whose_content_changed_is_not_replaced_at_start(interface, index, build, workdir, caplog):
    index.versions["aisc-plugin-interface"] = {"0.2.8"}
    index.files[("aisc-plugin-interface", "0.2.8")] = b"wheel"
    build.content = b"wheel v2"
    publisher = Publisher(upload=index.upload, versions_on_index=index.versions_on_index,
                          wheel_on_index=index.wheel_on_index, build=build, workdir=workdir)
    with caplog.at_level(logging.INFO):
        publisher.publish_interface()
    assert index.uploads == []
    assert index.files[("aisc-plugin-interface", "0.2.8")] == b"wheel"
    assert "replaced" not in caplog.text


def test_the_answer_names_the_published_wheels_sha256(client, github, index, build):
    github(REPO, {"main": (PACKAGE, "1.2.0")})
    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})
    assert status == 200, body
    assert body.get("sha256") == hashlib.sha256(build.content).hexdigest(), body
    assert "replaced" not in body


def test_an_unchanged_version_names_the_sha256_of_the_wheel_on_the_index(client, github, index, build):
    github(REPO, {"main": (PACKAGE, "1.1.0")})
    index.versions[PACKAGE] = {"1.1.0"}
    index.files[(PACKAGE, "1.1.0")] = b"wheel"
    status, body = client.post("/publish", {"repo": REPO, "package": PACKAGE})
    assert status == 200, body
    assert body.get("published") is False and body.get("sha256") == hashlib.sha256(b"wheel").hexdigest(), body
