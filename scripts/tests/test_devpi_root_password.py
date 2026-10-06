"""devpi's root password is generated and required (review pass 2026-10-06, catalogue finding S).

Whoever can log in to devpi as root can publish a package under a plugin's name, and the engine installs
and runs what devpi serves. The stack started devpi with DEVPI_ROOT_PASSWORD empty, so root stayed open to
any container on the backend network (plugin code in the eval worker included). scripts/secrets.sh now
makes it; devpi sets it at start (apps/catalogue/devpi/entrypoint.sh) and plugin-publisher uploads with it."""
import re

import yaml

from conftest import ROOT

APP = yaml.safe_load((ROOT / "docker-compose.development.yml").read_text())["services"]
REQUIRED = "${DEVPI_ROOT_PASSWORD:?run scripts/secrets.sh first}"


def test_secrets_sh_makes_it():
    assert re.search(r"^DEVPI_ROOT_PASSWORD=rand$", (ROOT / "scripts/secrets.sh").read_text(), re.M)


def test_devpi_and_the_publisher_require_it():
    assert APP["devpi"]["environment"]["DEVPI_ROOT_PASSWORD"] == REQUIRED
    assert APP["plugin-publisher"]["environment"]["TWINE_PASSWORD"] == REQUIRED


def test_no_settings_file_hands_compose_an_empty_one():
    """env.runtime is env.plugin_downloader followed by env.secrets: an empty DEVPI_ROOT_PASSWORD= in the
    settings would sit beside the generated one, and env.development is the documented local copy."""
    for name in ("env.plugin_downloader", "env.development"):
        assert not re.search(r"^DEVPI_ROOT_PASSWORD=\s*$", (ROOT / name).read_text(), re.M), name
