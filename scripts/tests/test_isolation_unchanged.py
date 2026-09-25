"""Isolation stage 2 (02-tests.md): guards for what the isolation must leave as it is.

I11.4: pgAdmin needs no change. It has one server, reads as inspector_ro, and uses `platform` as its
maintenance database, so every project database is listed.
I18.6: the diagrams gate and schema-docs keep the database regex `^(platform|project_[0-9a-f]{32})$`,
and pgAdmin and schema-docs stay on the `inspector` network. test_inspector_network.py pins the network
in detail; this file checks the regex and then relies on that suite.
These pass today and must stay green through every work package. Static, no database.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGEX = r"^(platform|project_[0-9a-f]{32})$"
EXAMPLE = "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"


def _compiled_in(path, name):
    src = (ROOT / path).read_text()
    m = re.search(name + r"\s*=\s*re\.compile\(r\"([^\"]+)\"\)", src)
    assert m, f"{path}: {name} regex not found"
    return m.group(1)


def test_i11_4_pgadmin_has_one_read_only_server_on_platform():
    servers = json.loads((ROOT / "inspector/pgadmin-servers.json").read_text())["Servers"]
    assert len(servers) == 1
    (server,) = servers.values()
    assert server["MaintenanceDB"] == "platform"
    assert server["Username"] == "inspector_ro"
    assert "DBRestriction" not in server, "I11.4: pgAdmin must list every database"


def test_i18_6_i11_2_schema_docs_keeps_the_database_regex():
    rx = _compiled_in("inspector/schema-docs/server.py", "DATABASE")
    assert rx == REGEX
    assert re.match(rx, EXAMPLE) and re.match(rx, "platform")
    for bad in ("superset", "keycloak", "project_3F2B", "project_" + "0" * 31, "platform2"):
        assert not re.match(rx, bad)


def test_i18_6_i11_2_the_diagrams_gate_keeps_the_database_regex():
    rx = _compiled_in("platform/platform_service/app.py", "SCHEMA_DATABASE")
    # app.py captures the hex part; the accepted set of names must be the same
    assert rx.replace("project_([0-9a-f]{32})", "project_[0-9a-f]{32}") == REGEX


def test_i18_6_the_inspector_network_suite_is_still_in_place():
    src = (ROOT / "scripts/tests/test_inspector_network.py").read_text()
    for name in ("test_wp3_inspector_is_only_on_its_own_network",
                 "test_wp3_no_other_service_shares_a_network_with_an_inspector"):
        assert f"def {name}" in src
