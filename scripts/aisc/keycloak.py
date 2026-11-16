"""The sign-in (Keycloak): kcadm in its container, and what start tells the realm on every start (the install's
addresses, the gateway's secret, the account lockout and the password policy)."""
from __future__ import annotations

import json
import os
import subprocess
import time

from .docker import Stack, captured, run_program
from .settings import COMPOSE, OUT, ROOT, Refused, effective, project, served_over_https, value_in, with_slash


def stack_container(docker_command: str, service: str) -> str:
    """The id of this project's running container of one service, empty when it runs none. Not the service's
    bare name: that is an older install's container, or a second copy's beside an install."""
    return captured([docker_command, *COMPOSE[1:], "ps", "-q", service]).stdout.strip()


def keycloak_container(docker_command: str) -> str:
    return stack_container(docker_command, "keycloak")


def kcadm_script(command: str) -> str:
    """A bash script for Keycloak's container: kcadm signs in to the master realm as Keycloak's admin, then runs
    one command (kcadm's arguments, in bash; "$cfg" is the session). kcadm starts Java with its arguments, and the
    host's `ps` shows a container's processes to every local user, so no secret is one of them: kcadm reads the
    admin's password from KC_CLI_PASSWORD itself, and a value to set comes on stdin. Each run keeps its session in
    a folder of its own, removed on exit: with one shared file, a rotate run beside a start would remove the
    other's session."""
    return f"""
    kc=/opt/keycloak/bin/kcadm.sh
    session=$(mktemp -d) || exit 1
    trap 'rm -rf "$session"' EXIT
    cfg=$session/kcadm.json
    "$kc" config credentials --config "$cfg" --server http://localhost:8080 --realm master \\
      --user "$KC_BOOTSTRAP_ADMIN_USERNAME" >/dev/null \\
      && "$kc" {command}"""


# runs the kcadm command given as bash -c's arguments, which hold no secret
KCADM_RUN = kcadm_script('"$@" --config "$cfg"')


def kcadm(docker_command: str, container: str, admin_password: str, *argv: str,
          stdin: str = "") -> subprocess.CompletedProcess:
    """One kcadm command in Keycloak's container, signed in as its admin. The password goes by name (docker exec
    -e KC_CLI_PASSWORD, its value in this process's environment only); what kcadm reads on stdin, stdin."""
    return run_program([docker_command, "exec", "-i", "-e", "KC_CLI_PASSWORD", container, "bash", "-c", KCADM_RUN,
                           "kcadm", *argv], env={**os.environ, "KC_CLI_PASSWORD": admin_password}, input=stdin,
                          capture_output=True, text=True)


def keycloak_realm_url() -> str:
    """The realm's own page on Keycloak's published port on this machine (the last KEYCLOAK_PORT_EXTERNAL line
    of env.runtime, else 8081), or START_SIGN_IN_URL. Not its public address: an https or other-host install's
    name may not resolve from here (hairpin NAT, a self-signed certificate) though the install is healthy."""
    given = os.environ.get("START_SIGN_IN_URL")
    if given:
        return given
    return f"http://localhost:{effective('KEYCLOAK_PORT_EXTERNAL') or '8081'}/realms/aisc"


def sign_in_clients(engine: str, launcher: str, dashboard: str, over_https: bool = False) -> dict[str, dict]:
    """What the realm's two clients must hold for this install's addresses: the gateway's callbacks on the
    engine, the launcher and the dashboard, and where it may send a person after signing out; the webapp's own
    address, beside the frontend's development server (http://localhost:5173) on an install not served over
    https. One served over https is public, and the webapp is a public client: an address on whatever machine
    signs in is no place to send its sign-in. The gateway's web origins are "+", Keycloak's shorthand
    for the origins of its redirect URIs, as the realm file has it. The launcher's address is given one ending
    with a slash when it has none: the sign-out rule is that address followed by *, and without the slash
    https://app.example.com* would also let the sign-out send a person on to https://app.example.com.evil.net/."""
    launcher = with_slash(launcher)
    development = [] if over_https else ["http://localhost:5173"]
    return {
        "aisc-gateway": {
            "redirectUris": [f"{engine}/oauth2/callback", f"{launcher}oauth2/callback", f"{dashboard}/oauth2/callback"],
            "webOrigins": ["+"],
            "attributes": {"post.logout.redirect.uris": f"{launcher}*##{engine}/*"},
        },
        "aisc-webapp": {
            "baseUrl": engine,
            "redirectUris": [f"{engine}/*", *(f"{d}/*" for d in development)],
            "webOrigins": [engine, *development],
        },
    }


#: the realm file's settings that lock an account after too many wrong passwords; start sends them to the realm
#: on every start, since the import that first gave them is never run again on an existing install
LOCKOUT_SETTINGS = ("bruteForceProtected", "permanentLockout", "maxTemporaryLockouts", "bruteForceStrategy",
                    "maxFailureWaitSeconds", "minimumQuickLoginWaitSeconds", "waitIncrementSeconds",
                    "quickLoginCheckMilliSeconds", "maxDeltaTimeSeconds", "failureFactor")


def realm_lockout() -> dict:
    """The account-lockout settings as keycloak/aisc-realm.json holds them."""
    realm = json.loads((ROOT / "keycloak" / "aisc-realm.json").read_text())
    return {name: realm[name] for name in LOCKOUT_SETTINGS if name in realm}


def realm_hardening_commands() -> list[list[str]]:
    """kcadm's commands that put the realm file's password policy and the lockout on realms made before them:
    the aisc realm (its people's sign-in) and the master realm (Keycloak's own admin console and kcadm). The
    master realm takes Keycloak's default lockout settings; only the switch is set there."""
    realm = json.loads((ROOT / "keycloak" / "aisc-realm.json").read_text())
    return [["update", "realms/aisc", "-s", "bruteForceProtected=true", "-s",
             "passwordPolicy=" + realm["passwordPolicy"]],
            ["update", "realms/master", "-s", "bruteForceProtected=true"]]


def sync_sign_in() -> None:
    """Tells Keycloak the addresses this install has now, the gateway client's current secret and the realm
    file's account lockout and password policy (and turns the lockout on in the master realm too). The realm import put the addresses, the secret and the lockout of its first start
    into the realm's database and is never run again, so a port that moved since would leave the sign-in sending
    people to an address nothing answers on, a rotated secret would leave oauth2-proxy refused, and a realm made
    before the lockout was turned on would take any number of wrong passwords. Run on every start once the realm answers; Keycloak may
    still refuse its admin for a moment then, so it is tried again (START_SYNC_TRIES times, START_SYNC_WAIT_S
    apart)."""
    tries = int(os.environ.get("START_SYNC_TRIES", "6"))
    wait_s = float(os.environ.get("START_SYNC_WAIT_S", "5"))
    clients = sign_in_clients(effective("API_URL_EXTERNAL") or "http://localhost",
                              effective("LAUNCHER_EXTERNAL_URL") or "http://localhost:8100/",
                              effective("DASHBOARD_EXTERNAL_URL") or "http://localhost:8188", served_over_https())
    # the gateway's client secret as env.secrets holds it: the realm import gave Keycloak only the first one, and
    # oauth2-proxy signs in with this one, so one made new by `secrets --rotate` reaches Keycloak here
    gateway_secret = value_in("GATEWAY_CLIENT_SECRET", OUT).strip("'\"")
    if gateway_secret:
        clients["aisc-gateway"]["secret"] = gateway_secret
    admin = value_in("KEYCLOAK_ADMIN_PASSWORD", OUT).strip("'\"")
    lockout = realm_lockout()

    def why_not_told() -> str:
        """Empty once both clients hold the addresses; else what kcadm said."""
        container = keycloak_container(Stack.docker)
        if not container:
            return f"Keycloak is not running in this install (docker compose -p {project()} ps keycloak)"
        for client_id, settings in clients.items():
            found = kcadm(Stack.docker, container, admin, "get", "clients", "-r", "aisc", "-q", f"clientId={client_id}")
            if found.returncode != 0:
                return found.stderr.strip() or f"kcadm could not read the client {client_id}"
            try:
                ids = [c["id"] for c in json.loads(found.stdout)]
            except (ValueError, TypeError, KeyError):
                ids = []
            if len(ids) != 1:
                return f"the realm aisc has no single client {client_id}"
            updated = kcadm(Stack.docker, container, admin, "update", f"clients/{ids[0]}", "-r", "aisc", "-f", "-",
                            stdin=json.dumps(settings))
            if updated.returncode != 0:
                return updated.stderr.strip() or f"kcadm could not update the client {client_id}"
        locked = kcadm(Stack.docker, container, admin, "update", "realms/aisc", "-f", "-", stdin=json.dumps(lockout))
        if locked.returncode != 0:
            return locked.stderr.strip() or "kcadm could not update the realm's account lockout"
        for command in realm_hardening_commands():
            hardened = kcadm(Stack.docker, container, admin, *command)
            if hardened.returncode != 0:
                return hardened.stderr.strip() or f"kcadm could not {' '.join(command[:2])}"
        return ""

    for attempt in range(tries):
        why = why_not_told()
        if not why:
            return
        if attempt + 1 < tries:
            time.sleep(wait_s)
    raise Refused(f"AISC is running, but its sign-in could not be told the install's addresses: {why[-400:]}. "
                  f"See why with: docker compose -p {project()} logs keycloak. Run start again.")
