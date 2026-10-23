"""Who holds the plugin publisher's secrets, read from the resolved compose files, and where its token comes from.

The publisher builds and uploads what devpi serves, so devpi's root password reaches it and devpi only. It
fetches private plugin repos with GITHUB_TOKEN, held by it alone. The platform asks it to publish a plugin
with PLUGIN_PUBLISHER_TOKEN, held by the two of them. Nothing is started: `docker compose config` reads
scratch copies of the compose files, and secrets.sh runs on a scratch copy of the checkout.
"""
import re

import pytest

import compose_cfg
from compose_cfg import FILES
from conftest import aisc_py
from test_dashboard_bridge_token import printed, runtime_of, scratch  # noqa: F401 (fixture)
from test_llm_keys import run_secrets, secrets_of

#: the file sets an install runs with, and the profile the inspection tools run under
RUNS = [(FILES, ()), (FILES, ("inspect",)),
        (FILES + ["docker-compose.https.yml", "docker-compose.admin-ports.yml"], ())]
IDS = ["default", "inspect", "https-and-admin-ports"]


def holders(tmp_path, files, profiles, name):
    """The services whose environment holds NAME's value, under any variable."""
    value = f"value-of-{name.lower()}"
    services = compose_cfg.config(tmp_path, *profiles, files=files, env={name: value})["services"]
    return sorted(s for s, svc in services.items()
                  if any(value in str(v) for v in (svc.get("environment") or {}).values()))


@pytest.mark.parametrize("files, profiles", RUNS, ids=IDS)
def test_only_the_publisher_and_devpi_hold_the_devpi_password_and_the_github_token(tmp_path, files, profiles):
    (tmp_path / "devpi").mkdir()
    (tmp_path / "github").mkdir()
    assert holders(tmp_path / "devpi", files, profiles, "DEVPI_ROOT_PASSWORD") == ["devpi", "plugin-publisher"]
    assert holders(tmp_path / "github", files, profiles, "GITHUB_TOKEN") == ["plugin-publisher"]


@pytest.mark.parametrize("files, profiles", RUNS, ids=IDS)
def test_only_the_platform_and_the_publisher_hold_the_publisher_token(tmp_path, files, profiles):
    assert holders(tmp_path, files, profiles, "PLUGIN_PUBLISHER_TOKEN") == ["platform", "plugin-publisher"]


def test_the_platform_reaches_the_publisher_on_its_port(tmp_path):
    services = compose_cfg.config(tmp_path)["services"]
    assert services["platform"]["environment"]["PLUGIN_PUBLISHER_URL"] == "http://plugin-publisher:8000"


def test_compose_refuses_to_start_without_the_publisher_token(tmp_path):
    assert "PLUGIN_PUBLISHER_TOKEN" in compose_cfg.required()
    r = compose_cfg.run(tmp_path, quiet=True, missing=("PLUGIN_PUBLISHER_TOKEN",))
    assert r.returncode != 0 and "PLUGIN_PUBLISHER_TOKEN" in r.stderr, r.stderr[-1000:]


def test_the_publisher_token_is_generated_with_the_other_secrets(scratch):  # noqa: F811
    assert dict(aisc_py().SECRETS).get("PLUGIN_PUBLISHER_TOKEN") == "rand"
    r = run_secrets(scratch)
    token = secrets_of(scratch).get("PLUGIN_PUBLISHER_TOKEN", "")
    assert re.fullmatch(r"[0-9a-f]{64}", token), "PLUGIN_PUBLISHER_TOKEN missing or not 64 hex in env.secrets"
    assert runtime_of(scratch).get("PLUGIN_PUBLISHER_TOKEN") == token, "not in env.runtime"
    assert token not in printed(r), "secrets.sh printed the publisher token"
