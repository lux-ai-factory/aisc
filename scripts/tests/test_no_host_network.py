"""The stack runs where Docker runs in a virtual machine (Docker Desktop on macOS and Windows), whose
host network is not this machine's (workshop 2026-10-06: the gateway answered 502 for ever on a Mac,
dialling host.docker.internal:4180 where oauth2-proxy was not). So no service uses network_mode: host,
and nothing needs file ACLs (setfacl does not exist on macOS):

- oauth2-proxy and the dashboard are on the compose network; Caddy reaches them by service name.
- Keycloak's public address is fixed (KC_HOSTNAME), so every token says the issuer the browser knows
  (http://localhost:8081/realms/aisc) wherever it was asked for; oauth2-proxy sends the browser there and
  redeems and fetches keys on keycloak:8080.
- The realm is imported from the template as it is in git: Keycloak fills ${GATEWAY_CLIENT_SECRET} from
  its environment, so no file holding the secret is written for it to read.
- immudb's signing key is handed over by a one-off job that copies it into a volume as immudb's user.

Static checks of the compose files, the Caddyfile, the realm and scripts/secrets.sh."""
import json
import re

import yaml

from conftest import ROOT

DEV = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]


def services(*files):
    out = {}
    for f in files:
        out.update(yaml.safe_load((ROOT / f).read_text()).get("services") or {})
    return out


def flags(spec):
    return [str(a) for a in (spec.get("command") or [])]


def test_no_service_uses_the_host_network():
    for path in sorted(ROOT.glob("docker-compose*.yml")):
        for name, spec in (yaml.safe_load(path.read_text()).get("services") or {}).items():
            assert (spec or {}).get("network_mode") != "host", f"{path.name}: {name} uses the host network"


def test_caddy_reaches_the_sign_in_and_the_dashboard_by_service_name():
    caddyfile = (ROOT / "Caddyfile").read_text()
    assert "host.docker.internal:4180" not in caddyfile
    assert re.search(r"forward_auth oauth2-proxy:4180", caddyfile)
    assert re.search(r"reverse_proxy oauth2-proxy:4180", caddyfile)
    caddy = services(*DEV)["caddy"]
    assert caddy["environment"]["DASHBOARD_UPSTREAM"].startswith("dashboard:")


def test_oauth2_proxy_sends_the_browser_to_the_public_address_and_talks_to_keycloak_inside():
    s = services(*DEV)
    proxy = s["oauth2-proxy"]
    assert "backend" in proxy["networks"] and "backend" in s["caddy"]["networks"]
    f = flags(proxy)
    assert "--oidc-issuer-url=${KEYCLOAK_URL_EXTERNAL}/realms/aisc" in f
    assert "--skip-oidc-discovery=true" in f
    assert "--login-url=${KEYCLOAK_URL_EXTERNAL}/realms/aisc/protocol/openid-connect/auth" in f
    internal = "${KEYCLOAK_INTERNAL_URL:-http://keycloak:8080}/realms/aisc/protocol/openid-connect"
    assert f"--redeem-url={internal}/token" in f
    assert f"--oidc-jwks-url={internal}/certs" in f
    assert f"--backend-logout-url={internal}/logout?id_token_hint={{id_token}}" in f
    assert not any("localhost:4180" in a or "127.0.0.1" in a for a in f)


def test_keycloak_says_one_issuer_whoever_asks():
    env = services(*DEV)["keycloak"]["environment"]
    assert env["KC_HOSTNAME"] == "${KEYCLOAK_URL_EXTERNAL}"
    assert str(env["KC_HOSTNAME_BACKCHANNEL_DYNAMIC"]).lower() == "true"


def test_the_realm_is_imported_from_the_template_with_the_secret_from_the_environment():
    keycloak = services(*DEV)["keycloak"]
    assert "./keycloak/aisc-realm.json:/opt/keycloak/data/import/aisc-realm.json:ro" in keycloak["volumes"]
    assert not any("aisc-realm.local.json" in v for v in keycloak["volumes"])
    assert keycloak["environment"]["GATEWAY_CLIENT_SECRET"].startswith("${GATEWAY_CLIENT_SECRET:?")
    realm = json.loads((ROOT / "keycloak/aisc-realm.json").read_text())
    gateway = next(c for c in realm["clients"] if c["clientId"] == "aisc-gateway")
    assert gateway["secret"] == "${GATEWAY_CLIENT_SECRET}"
    assert "__GATEWAY_CLIENT_SECRET__" not in (ROOT / "keycloak/aisc-realm.json").read_text()


def test_immudb_gets_its_key_from_a_volume_a_one_off_job_fills():
    s = services(*DEV)
    immudb, job = s["immudb"], s["immudb-key"]
    assert not any("immudb-signing.key" in v for v in immudb["volumes"])
    assert any(v.startswith("immudb_key:") for v in immudb["volumes"])
    assert immudb["depends_on"]["immudb-key"]["condition"] == "service_completed_successfully"
    assert str(job.get("user")) in ("0", "root")
    assert any("immudb-signing.key" in v and v.endswith(":ro") or "immudb-signing.key" in v and ":ro," in v
               for v in job["volumes"])
    script = " ".join(job["command"]) if isinstance(job["command"], list) else job["command"]
    assert "3322" in script and "400" in script


def test_the_dashboard_reaches_everything_by_service_name():
    s = services(*DEV)
    dash = s["dashboard"]
    assert "backend" in dash["networks"]
    env = dash["environment"]
    joined = json.dumps(env)
    assert "localhost:5432" not in joined and "172.17.0.1" not in joined
    assert env["SUPERSET_BIND_ADDRESS"] == "0.0.0.0"
    assert env["REDIS_HOST"] == "redis" and env["IMMUDB_HOST"] == "immudb"
    assert env["AISC_PROJECT_DB_HOSTPORT"] == "postgres:5432"
    assert "@postgres:5432/superset" in env["SUPERSET_DB_URI"]
    assert env["GATEWAY_JWKS_URL"].startswith("${KEYCLOAK_INTERNAL_URL:-http://keycloak:8080}/")
    assert env["PLATFORM_URL"].startswith("${DASHBOARD_PLATFORM_URL:-http://platform:")
    assert s["platform"]["environment"]["DASHBOARD_BRIDGE_URL"].startswith("http://dashboard:")


def test_secrets_sh_needs_no_acl_and_writes_no_realm_copy():
    text = (ROOT / "scripts/secrets.sh").read_text()
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "setfacl" not in code
    assert "aisc-realm.local.json" not in code
