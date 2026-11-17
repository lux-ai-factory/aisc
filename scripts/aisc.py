# /// script
# requires-python = ">=3.10"
# dependencies = ["cryptography>=42"]
# ///
"""Install and run AISC on Linux, macOS and Windows alike: the commands a person installing it runs.

    uv run scripts/aisc.py start                              # check, make the secrets, build, start, wait
    uv run scripts/aisc.py start --configurator               # the same for the Configurator's own deployment
                                                              # (docker-compose.configurator.yml, env.configurator)
    uv run scripts/aisc.py secrets                            # make the secrets if they are missing
    uv run scripts/aisc.py secrets --rotate                   # make new ones, replacing what is there
    uv run scripts/aisc.py secrets --add-ledger-key           # add the next version of the ledger's master key
    uv run scripts/aisc.py secrets --rotate-one NAME          # a new IMMUDB_ADMIN_PASSWORD, LEDGER_IMMUDB_PASSWORD
                                                              # or ENGINE_IMMUDB_PASSWORD
    uv run scripts/aisc.py stop                               # stop this install's containers, keep its data
    uv run scripts/aisc.py remove                             # delete this install's containers and all its data
    uv run scripts/aisc.py password                           # the admin and user accounts' passwords
    uv run scripts/aisc.py rotate-infra-password NAME [--ask] # a new value for an infrastructure password
    uv run scripts/aisc.py drift [--prefix STACK]             # which running containers differ from their image

scripts/start.sh, scripts/secrets.sh and scripts/rotate-infra-password.sh run the same commands. Only Python
and Docker are needed on the host: no bash, openssl, curl or awk, so a Windows terminal will do. uv fetches
Python and the one library this needs (cryptography, for the immudb signing key).

The secrets
-----------
A secret committed to the repo is a secret every clone shares. The worst of them would be the gateway's cookie
secret: whoever holds it can mint a session cookie for any user, offline, and that cookie is the session every
module trusts. So none of them has a default. The compose files refuse to start without these; `secrets` writes
them once into env.secrets, which is git-ignored. The realm import takes the one it holds from Keycloak's
environment (${GATEWAY_CLIENT_SECRET}).

PLATFORM_SECRETS_KEY is the exception to --rotate: it encrypts the LLM API keys stored in every project's
database, so a fresh one would make all of them unreadable. --rotate keeps it. To rotate it: prepend a new Fernet
key to it (comma list, newest first), restart the platform, run
  python -m platform_service.llm_store rotate
in the platform container, then drop the old key from the list.

The ledger's two secrets survive --rotate too:
- PLATFORM_LEDGER_KEYS is versioned ("v1:<hex>,v2:<hex>") and every version is kept for ever, because the
  digests in immudb were made with them. Rotating means adding the next version (--add-ledger-key) and
  restarting the platform; new digests use it, old ones still check.
- LEDGER_IMMUDB_PASSWORD (the platform's immudb user, aisc_ledger) and ENGINE_IMMUDB_PASSWORD (the engine's,
  aisc_engine) live in immudb too once the users exist; change them with --rotate-one, which ledger-pool then
  applies in immudb at the next start.

The infrastructure's own passwords (the Postgres superuser, MinIO's root, RabbitMQ, Keycloak's bootstrap admin,
the realm's admin and user accounts) are made here too. Their images apply them only when their volume is first
made, so:
- --rotate keeps them (a new value would no longer open the existing volume);
- an install made before they were generated runs on the values env.plugin_downloader used to hold. When
  env.secrets lacks one, this writes the value that install runs on (from its env.runtime, or else the old
  tracked value), never a new one. Such an install is on well-known passwords until rotate-infra-password
  changes each, in its service and then in env.secrets; a new install gets random ones.

The realm's two accounts, admin and user, get generated passwords on every new install (`password` prints
them). An install made before that may still be on admin / admin and user / user: start says so, naming the
rotate-infra-password command for each, never the value.

Caddy publishes the browser ports on this machine only (127.0.0.1) unless the install asks for the network:
AISC_LAN=on (in the environment or env.local), or an install served over https. env.runtime then gets
CADDY_BIND_ADDRESS=0.0.0.0; a CADDY_BIND_ADDRESS line in env.local (an address of this machine) is taken over both.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

#: the package beside this file, one module per job: settings (files, env files, the Compose project), secrets,
#: ports, docker (every program run, and the Stack), keycloak (the sign-in), infra_passwords
#: (rotate-infra-password), stack (start, stop, remove) and image_drift (drift)
PACKAGE = Path(__file__).resolve().parent / "aisc"


def load_package():
    """scripts/aisc/ as the package `aisc`, from this file's own folder, its modules run afresh: a copy of the
    checkout loaded in the same process (the tests load scratch copies) never runs another copy's modules, and
    nothing is added to sys.path (the package's secrets module would hide the standard library's)."""
    for name in [n for n in sys.modules if n == "aisc" or n.startswith("aisc.")]:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location("aisc", PACKAGE / "__init__.py",
                                                  submodule_search_locations=[str(PACKAGE)])
    package = importlib.util.module_from_spec(spec)
    sys.modules["aisc"] = package
    spec.loader.exec_module(package)


load_package()

from aisc import docker, image_drift, infra_passwords, keycloak, ports, secrets, settings, stack  # noqa: E402

# Every name the modules define stays a name of this script too, so what the tests and wrappers read here
# (SECRETS, COMPOSE, settle_ports, Stack, sign_in_clients, ...) is still here. A test that replaces a name
# replaces it in the module that uses it (stack.docker_in_time, ports.ON_WINDOWS, ...).
for _module in (settings, secrets, docker, ports, keycloak, infra_passwords, stack, image_drift):
    globals().update((name, value) for name, value in vars(_module).items() if not name.startswith("__"))

#: the docker command this process's PATH finds, as the module loads (start finds it again: Stack.use_docker)
DOCKER = docker.Stack.docker

COMMANDS = {"start": stack.start, "secrets": secrets.make_secrets, "password": secrets.show_passwords,
            "rotate-infra-password": infra_passwords.rotate_infra_password, "stop": stack.stop,
            "remove": stack.remove, "drift": image_drift.drift}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        settings.warn(f"usage: uv run scripts/aisc.py {{{'|'.join(COMMANDS)}}} [options]  (see the top of "
                      "scripts/aisc.py)")
        return 2
    os.chdir(settings.ROOT)
    try:
        COMMANDS[argv[0]](argv[1:])
    except settings.Refused as refused:
        if argv[0] == "start" and not stack.STACK_BEING_STARTED:
            # A refusal that is followed by a hand-run compose up leaves half-made containers behind. After `up`
            # the refusals give their own advice, and "nothing was started" would no longer be true.
            settings.warn(f"aisc.py start: {str(refused).rstrip('.')}. Nothing was started. Fix this and run start "
                          "again, not docker compose directly.")
        else:
            settings.warn(f"aisc.py {argv[0]}: {refused}" if argv[0] == "start" else str(refused))
        return refused.code
    except OSError as failed:
        settings.warn(f"aisc.py {argv[0]}: {failed.strerror or failed} ({failed.filename or 'a file here'}); the "
                      "files already there are as they were")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
