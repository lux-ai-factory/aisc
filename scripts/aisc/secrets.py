"""The secrets: what env.secrets holds, how each value is made, what --rotate keeps, and env.runtime made from
them (see the top of scripts/aisc.py)."""
from __future__ import annotations

import base64
import os
import re
import secrets as random_source
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .settings import (COMBINED, INSTALL, LOCAL, OUT, SIGNING_KEY, SIGNING_PUB, Refused, settings_file,
                       caddy_bind_address, container_prefix, install_id, lines_of, new_install_id, private, project,
                       say, stack_name, text_of, up_hint, use_stack, value_in, warn, with_value, write_beside)


# ---------------------------------------------------------------------------------------------- the secrets

# Every secret, in the order a new env.secrets lists them, with the kind of value it takes. A secret added here
# reaches existing installs too: a plain run appends whatever an env.secrets lacks, never replacing a value that
# is there.
SECRETS = [
    # the infrastructure (VOLUME_BOUND below): Postgres superuser, MinIO root, RabbitMQ, Keycloak's admin
    ("POSTGRES_PASSWORD", "rand"),
    ("S3_PASSWORD", "rand"),
    ("RABBITMQ_PASSWORD", "rand"),
    ("KEYCLOAK_ADMIN_PASSWORD", "rand"),
    # the engine's and the platform's own MinIO accounts (aisc-engine, aisc-platform): make_buckets sets them
    # on every start (infra/minio/make-buckets.sh), so they are not volume-bound and --rotate renews them
    ("S3_ENGINE_PASSWORD", "rand"),
    ("S3_PLATFORM_PASSWORD", "rand"),
    # MinIO's key for what it stores (server-side encryption of every bucket): made once and kept, --rotate
    # included, since every object written under it is unreadable without it
    ("MINIO_KMS_SECRET_KEY", "minio_kms"),
    # the RabbitMQ accounts of the engine, the workers and Flower (aisc-engine, aisc-worker, aisc-flower), none an
    # administrator: rabbitmq-setup sets them on every start (infra/rabbitmq/setup_users.py), so --rotate renews
    # them; RABBITMQ_PASSWORD, the administrator's, is for operators only
    ("RABBITMQ_ENGINE_PASSWORD", "rand"),
    ("RABBITMQ_WORKER_PASSWORD", "rand"),
    ("RABBITMQ_FLOWER_PASSWORD", "rand"),
    # the realm's two accounts, admin and user: the realm import puts these into it, and its database keeps them
    # after, so they are volume-bound too. Generated on every new install (account below)
    ("AISC_ADMIN_PASSWORD", "account"),
    ("AISC_USER_PASSWORD", "account"),
    ("GATEWAY_COOKIE_SECRET", "cookie"),
    ("GATEWAY_CLIENT_SECRET", "rand"),
    ("DJANGO_SECRET_KEY", "rand"),
    # the engine's own key for the credentials it stores (aisc_backend/utils/encryption.py), held by the backend and
    # the eval worker; values stored before it, under DJANGO_SECRET_KEY, still decrypt
    ("ENGINE_SECRETS_KEY", "fernet"),
    ("INTERNAL_API_KEY", "rand"),
    ("SUPERSET_SECRET_KEY", "rand"),
    # signs the dashboard's guest tokens (embedding is on): never Superset's published default
    ("SUPERSET_GUEST_TOKEN_SECRET", "rand"),
    # the platform's calls to the dashboard's bridge (/api/v1/aisc_project); with none, it refuses them all
    ("DASHBOARD_BRIDGE_TOKEN", "rand"),
    ("REPORT_SERVICE_TOKEN", "rand"),
    # Keycloak's and Superset's own database roles (init/keycloak-role.sql, init/superset-role.sql)
    ("KEYCLOAK_DB_PASSWORD", "rand"),
    ("SUPERSET_DB_PASSWORD", "rand"),
    ("REPORT_RO_PASSWORD", "rand"),
    ("REPORT_COMPOSER_PASSWORD", "rand"),
    ("INSPECTOR_PASSWORD", "rand"),
    # One token per agentic system, so each agent resolves only its own choice and key.
    ("PLATFORM_CARD_AGENT_TOKEN", "rand"),
    ("PLATFORM_RISK_MAPPER_TOKEN", "rand"),
    ("PLATFORM_CHART_ASSISTANT_TOKEN", "rand"),
    # the chart assistant: the dashboard's calls to it, and its role on the mock databases (init/chart-assistant-role.sql)
    ("ASSISTANT_DASHBOARD_TOKEN", "rand"),
    ("ASSISTANT_MOCK_PASSWORD", "rand"),
    # the plugin-side client of Manage -> Connections resolves a connection with it (platform, eval worker)
    ("PLATFORM_CONNECTIONS_TOKEN", "rand"),
    # One token per caller edge of the service-only APIs: each is held by its caller and its callee only, so no
    # service can call another with a token it was not given.
    ("QUALIFICATION_AGENTS_TO_WEB_TOKEN", "rand"),
    ("QUALIFICATION_WEB_TO_AGENTS_TOKEN", "rand"),
    ("QUALIFICATION_WEB_TO_ONTOLOGY_TOKEN", "rand"),
    ("QUALIFICATION_AGENTS_TO_ONTOLOGY_TOKEN", "rand"),
    ("QUALIFICATION_WEB_TO_PREFILL_TOKEN", "rand"),
    ("QUALIFICATION_WEB_TO_PDF_TOKEN", "rand"),
    ("CONTROLS_WEB_TO_PDF_TOKEN", "rand"),
    ("PLATFORM_SECRETS_KEY", "fernet"),
    # immudb's superuser: compose starts immudb with IMMUDB_FORCE_ADMIN_PASSWORD, so a new value is applied at
    # its next start
    ("IMMUDB_ADMIN_PASSWORD", "immudbpw"),
    # the ledger: the platform's immudb user, and its versioned master keys (both kept by --rotate)
    ("LEDGER_IMMUDB_PASSWORD", "immudbpw"),
    # the engine's own immudb user, aisc_engine, on auditdb only (read on defaultdb): ledger-pool makes it with
    # this password, so like the ledger user's it is kept by --rotate (--rotate-one changes it)
    ("ENGINE_IMMUDB_PASSWORD", "immudbpw"),
    ("PLATFORM_LEDGER_KEYS", "ledgerkey"),
    # platform_rw, the platform service's database role: postgres-setup applies it on every start
    ("PLATFORM_RW_PASSWORD", "rand"),
    # the migrator logins, one per owner role (init/owner-roles.sql): postgres-setup applies them on every start.
    # A migrator's sessions act as its module's owner role; only the platform uses its own so far
    # (PLATFORM_MIGRATE_DATABASE_URL), to migrate, make and drop project databases.
    ("PLATFORM_MIGRATOR_PASSWORD", "rand"),
    ("QUALIFICATION_MIGRATOR_PASSWORD", "rand"),
    ("CONTROLS_MIGRATOR_PASSWORD", "rand"),
    ("CONTROL_OBJECTIVES_MIGRATOR_PASSWORD", "rand"),
    ("REPORT_COMPOSER_MIGRATOR_PASSWORD", "rand"),
    ("ENGINE_MIGRATOR_PASSWORD", "rand"),
    # qualification_rw, the qualification app's database role: postgres-setup applies it on every start
    ("QUALIFICATION_RW_PASSWORD", "rand"),
    # control_objectives_rw, the control objectives service's database role: postgres-setup applies it
    ("CONTROL_OBJECTIVES_RW_PASSWORD", "rand"),
    ("CONTROLS_RW_PASSWORD", "rand"),
    ("DEVPI_ROOT_PASSWORD", "rand"),
    ("ENGINE_RW_PASSWORD", "rand"),
    # keys the engine's run tickets; the backend only (the eval worker runs plugin code)
    ("RUN_TICKET_KEY", "rand"),
    # dashboard_ro, the results dashboard's read role: postgres-setup applies it
    ("DASHBOARD_RO_PASSWORD", "rand"),
    # the dashboard's own Redis (Superset's cache, dashboard-redis): its password, held by the dashboard only
    ("DASHBOARD_REDIS_PASSWORD", "rand"),
    # the shared Redis, where the worker's Celery results are kept: the backend's URL carries it (REDIS_BACKEND_URL
    # in env.plugin_downloader refers to it), the worker and flower build theirs from it
    ("REDIS_PASSWORD", "rand"),
    # the ledger witness: Caddy sends it, the platform checks it
    ("AISC_WITNESS_GATEWAY_SECRET", "rand"),
    # one token per caller that posts ledger events, held by it and the platform only
    ("PLATFORM_LEDGER_ENGINE_TOKEN", "rand"),
    ("PLATFORM_LEDGER_DASHBOARD_TOKEN", "rand"),
    ("PLATFORM_LEDGER_AGENTS_TOKEN", "rand"),
    # the platform asks the plugin publisher to fetch, build and publish a plugin with it; held by the two only
    ("PLUGIN_PUBLISHER_TOKEN", "rand"),
    # the engine backend asks the platform whether a card target has a connection with it; held by the two only
    ("PLATFORM_ENGINE_TOKEN", "rand"),
    # the controls app sends and reads the proof files of checklist answers with it; held by the two only
    ("PLATFORM_CONTROLS_TOKEN", "rand"),
]
# The infrastructure passwords: their volumes hold them (see the top of this file).
VOLUME_BOUND = ("POSTGRES_PASSWORD", "S3_PASSWORD", "RABBITMQ_PASSWORD", "KEYCLOAK_ADMIN_PASSWORD",
                "AISC_ADMIN_PASSWORD", "AISC_USER_PASSWORD")
# What env.runtime defines first, from env.secrets only: compose expands a setting built from one of these with the
# values defined above it (REDIS_BACKEND_URL holds $REDIS_PASSWORD).
FIRST_IN_RUNTIME = (*VOLUME_BOUND, "REDIS_PASSWORD")
# What --rotate keeps: replacing any of these would make stored data unreadable or unverifiable.
# DEVPI_ROOT_PASSWORD: devpi's volume holds root's password and devpi refuses to start on another one.
# SUPERSET_SECRET_KEY: it encrypts the database connections Superset stores; to change it, set
# PREVIOUS_SECRET_KEY to the old one and run `superset re-encrypt-secrets` in the dashboard container.
# ENGINE_SECRETS_KEY: the engine encrypts the credentials it stores with it (aisc_backend/utils/encryption.py).
# DJANGO_SECRET_KEY: credentials the engine stored before ENGINE_SECRETS_KEY existed are under a key derived from
# it, so it stays kept until every stored value has been encrypted again under ENGINE_SECRETS_KEY.
KEPT_ON_ROTATE = ("PLATFORM_SECRETS_KEY", "LEDGER_IMMUDB_PASSWORD", "ENGINE_IMMUDB_PASSWORD", "PLATFORM_LEDGER_KEYS",
                  "DEVPI_ROOT_PASSWORD", "SUPERSET_SECRET_KEY", "DJANGO_SECRET_KEY", "ENGINE_SECRETS_KEY",
                  "MINIO_KMS_SECRET_KEY", *VOLUME_BOUND)
# The keys that open what is stored: an emptied line for one of them is refused, never made again, since every value
# encrypted or signed under the old key would become unreadable or unverifiable. PLATFORM_SECRETS_KEY opens the stored
# LLM keys, ENGINE_SECRETS_KEY and DJANGO_SECRET_KEY the engine's stored credentials, PLATFORM_LEDGER_KEYS checks the
# ledger's past signatures, MINIO_KMS_SECRET_KEY the files MinIO stores.
NEVER_MADE_AGAIN = ("PLATFORM_SECRETS_KEY", "DJANGO_SECRET_KEY", "ENGINE_SECRETS_KEY", "PLATFORM_LEDGER_KEYS",
                    "MINIO_KMS_SECRET_KEY")
# What --rotate replaces: every other secret, named here so that a secret added to SECRETS is put in one of the
# two by a decision (scripts/tests/test_aisc_py.py fails until it is), never fresh by default.
FRESH_ON_ROTATE = ("GATEWAY_COOKIE_SECRET", "GATEWAY_CLIENT_SECRET", "INTERNAL_API_KEY", "SUPERSET_GUEST_TOKEN_SECRET",
                   "DASHBOARD_BRIDGE_TOKEN", "REPORT_SERVICE_TOKEN", "KEYCLOAK_DB_PASSWORD", "SUPERSET_DB_PASSWORD",
                   "REPORT_RO_PASSWORD", "REPORT_COMPOSER_PASSWORD", "INSPECTOR_PASSWORD", "PLATFORM_CARD_AGENT_TOKEN",
                   "PLATFORM_RISK_MAPPER_TOKEN", "PLATFORM_CHART_ASSISTANT_TOKEN", "ASSISTANT_DASHBOARD_TOKEN",
                   "ASSISTANT_MOCK_PASSWORD", "PLATFORM_CONNECTIONS_TOKEN", "QUALIFICATION_AGENTS_TO_WEB_TOKEN",
                   "QUALIFICATION_WEB_TO_AGENTS_TOKEN", "QUALIFICATION_WEB_TO_ONTOLOGY_TOKEN",
                   "QUALIFICATION_AGENTS_TO_ONTOLOGY_TOKEN", "QUALIFICATION_WEB_TO_PREFILL_TOKEN",
                   "QUALIFICATION_WEB_TO_PDF_TOKEN", "CONTROLS_WEB_TO_PDF_TOKEN", "IMMUDB_ADMIN_PASSWORD",
                   "PLATFORM_RW_PASSWORD", "QUALIFICATION_RW_PASSWORD", "CONTROL_OBJECTIVES_RW_PASSWORD",
                   "CONTROLS_RW_PASSWORD", "ENGINE_RW_PASSWORD", "RUN_TICKET_KEY", "DASHBOARD_RO_PASSWORD",
                   "DASHBOARD_REDIS_PASSWORD", "REDIS_PASSWORD", "AISC_WITNESS_GATEWAY_SECRET", "PLATFORM_LEDGER_ENGINE_TOKEN",
                   "PLATFORM_LEDGER_DASHBOARD_TOKEN", "PLATFORM_LEDGER_AGENTS_TOKEN", "PLUGIN_PUBLISHER_TOKEN",
                   "PLATFORM_ENGINE_TOKEN", "PLATFORM_CONTROLS_TOKEN", "PLATFORM_MIGRATOR_PASSWORD",
                   "QUALIFICATION_MIGRATOR_PASSWORD", "CONTROLS_MIGRATOR_PASSWORD", "CONTROL_OBJECTIVES_MIGRATOR_PASSWORD",
                   "REPORT_COMPOSER_MIGRATOR_PASSWORD", "ENGINE_MIGRATOR_PASSWORD", "S3_ENGINE_PASSWORD",
                   "S3_PLATFORM_PASSWORD", "RABBITMQ_ENGINE_PASSWORD", "RABBITMQ_WORKER_PASSWORD",
                   "RABBITMQ_FLOWER_PASSWORD")
# The immudb passwords the stack brings to a new value itself (--rotate-one).
ROTATE_ONE = ("IMMUDB_ADMIN_PASSWORD", "LEDGER_IMMUDB_PASSWORD", "ENGINE_IMMUDB_PASSWORD")
LEDGER_KEYS = re.compile(r"v[1-9][0-9]*:[0-9a-f]{64}(,v[1-9][0-9]*:[0-9a-f]{64})*")


def rand() -> str:
    return random_source.token_hex(32)


def cookie() -> str:
    # oauth2-proxy decodes this as base64url and wants exactly 32 bytes out. With padding it does not decode,
    # and it then measures the string itself and refuses to start: "cookie_secret must be 16, 24, or 32 bytes".
    return base64.urlsafe_b64encode(random_source.token_bytes(32)).decode().rstrip("=")


def fernet() -> str:
    # Fernet wants urlsafe base64 of 32 bytes WITH its `=` padding: 44 characters.
    return base64.urlsafe_b64encode(random_source.token_bytes(32)).decode()


def minio_kms() -> str:
    # MinIO's single static key: "<key name>:<base64 of 32 bytes>"
    return "aisc-key:" + base64.b64encode(random_source.token_bytes(32)).decode()


def immudbpw() -> str:
    # immudb refuses a password without an upper and a lower case letter, a digit and a symbol, or over 32
    # characters: 24 random hex (96 bits) behind a fixed prefix that has one of each.
    return "Az9-" + random_source.token_hex(12)


def account(name: str) -> str:
    """A realm account's password: random on every install, served over https or not (the realm's sign-in is
    reached through Caddy, which may be on the network)."""
    return rand()


#: each realm account's setting, its name, and the password it had on a local install before they were generated
KNOWN_ACCOUNT_PASSWORDS = {"AISC_ADMIN_PASSWORD": ("admin", "admin"), "AISC_USER_PASSWORD": ("user", "user")}


def warn_known_account_passwords(path: str) -> None:
    """Tells an install whose env.secrets still holds a realm account's well-known password which command changes
    it. Names the setting and the command, never the value."""
    if not Path(path).is_file():
        return
    for name, (account_name, known) in KNOWN_ACCOUNT_PASSWORDS.items():
        if value_in(name, path).strip("'\"") == known:
            warn(f"The realm account '{account_name}' still has the well-known password this install was made with. "
                 f"Anyone who reaches the sign-in can use it. Change it with: scripts/aisc.py rotate-infra-password "
                 f"{name}")


def fresh(kind: str, name: str) -> str:
    """A new value of this kind; the ledger's master key list starts at version 1."""
    return {"cookie": cookie, "fernet": fernet, "immudbpw": immudbpw, "minio_kms": minio_kms,
            "ledgerkey": lambda: "v1:" + rand(),
            "account": lambda: account(name)}.get(kind, rand)()


def kept_value(name: str) -> str:
    return value_in(name, OUT) if Path(OUT).is_file() else ""


def was_tracked(name: str) -> str:
    """The value env.plugin_downloader held for an infrastructure password before they were generated."""
    return {"KEYCLOAK_ADMIN_PASSWORD": "admin", "AISC_ADMIN_PASSWORD": "admin", "AISC_USER_PASSWORD": "user"}.get(
        name, "dev-password")


def running_value(name: str) -> str:
    """An install whose env.secrets predates the infrastructure passwords: the value its volumes were made with.
    Its env.runtime says what it runs on; without one, the value env.plugin_downloader held."""
    value = value_in(name, COMBINED) if Path(COMBINED).is_file() else ""
    return value or was_tracked(name)


def missing_value(name: str, kind: str, existed: bool) -> str:
    """The value a secret takes when env.secrets lacks it: a new one, but for an existing install's
    infrastructure password, the one it runs on."""
    return running_value(name) if existed and name in VOLUME_BOUND else fresh(kind, name)


def add_ledger_key() -> None:
    """The next version of the ledger's master key, appended; nothing else changes."""
    if not Path(OUT).is_file():
        raise Refused(f"{OUT} does not exist: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    current = value_in("PLATFORM_LEDGER_KEYS", OUT)
    if not current:
        raise Refused(f"PLATFORM_LEDGER_KEYS is missing from {OUT}: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    if not LEDGER_KEYS.fullmatch(current):
        raise Refused(f"PLATFORM_LEDGER_KEYS in {OUT} is not v<N>:<64 hex>[,...]: fix it by hand; nothing changed")
    following = max(int(k.split(":", 1)[0][1:]) for k in current.split(",")) + 1
    write_beside(OUT, text_of(with_value(lines_of(OUT), "PLATFORM_LEDGER_KEYS", f"{current},v{following}:{rand()}")))
    say(f"added ledger key version v{following} to {OUT} (restart the platform to sign new digests with it)")


def rotate_one(name: str) -> None:
    """A new value for one of immudb's passwords; every other line of env.secrets stays as it is. A restart
    finishes it: immudb applies its superuser's at start (IMMUDB_FORCE_ADMIN_PASSWORD), and ledger-pool, as the
    superuser, gives aisc_ledger and aisc_engine their new ones."""
    if name not in ROTATE_ONE:
        raise Refused(f"--rotate-one takes one of: {' '.join(ROTATE_ONE)} (the immudb passwords the stack brings to "
                      "a new value itself)", 2)
    if not Path(OUT).is_file():
        raise Refused(f"{OUT} does not exist: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    if not any(line.startswith(name + "=") for line in lines_of(OUT)):
        raise Refused(f"{name} is missing from {OUT}: run scripts/aisc.py secrets (scripts/secrets.sh) first")
    write_beside(OUT, text_of(with_value(lines_of(OUT), name, immudbpw())))
    hint = (f"  docker compose -p {project()} --env-file env.runtime \\\n"
            "    -f docker-compose-infra.development.yml -f docker-compose.development.yml")
    say(f"rotated {name} in {OUT}. To apply it, recreate immudb, ledger-pool, platform and aisc-backend:",
        hint + " up -d immudb ledger-pool platform aisc-backend",
        f"  ledger-pool must exit 0 (docker compose -p {project()} ps -a ledger-pool), then, whichever name was rotated:",
        hint + " restart aisc-backend",
        "  (so the engine runs on the new password at once; after immudb's restart its audit clerk would also log in"
        " again by itself on its next write)")


def install_line(path: str) -> str | None:
    """The file's AISC_INSTALL line, None when it has none."""
    return next((line for line in lines_of(path) if line.startswith(INSTALL + "=")), None)


def new_file(rotate: bool, existed: bool) -> list[str]:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [f"# Generated by scripts/aisc.py secrets on {stamp}. Not in git.",
             "# Rotating these signs everyone out. start hands a new GATEWAY_CLIENT_SECRET to Keycloak's",
             "# aisc-gateway client."]
    if not existed:
        lines.append(f"{INSTALL}={new_install_id()}")
    elif install_line(OUT) is not None:
        lines.append(install_line(OUT))
    for name, kind in SECRETS:
        if name in KEPT_ON_ROTATE and kept_value(name):
            lines.append(f"{name}={kept_value(name)}")
        else:
            lines.append(f"{name}={missing_value(name, kind, existed)}")
    return lines


def with_missing_added(existed: bool) -> list[str]:
    say(f"{OUT} exists; keeping its values and adding any that are missing (--rotate to replace)")
    lines = lines_of(OUT)
    for name, kind in SECRETS:
        if not any(line.startswith(name + "=") for line in lines):
            lines.append(f"{name}={missing_value(name, kind, existed)}")
            if name in VOLUME_BOUND:
                say(f"added {name} to {OUT}: the value this install already runs on (its volume holds it)")
            else:
                say(f"added {name} to {OUT}")
    return lines


def make_signing_key() -> None:
    """immudb signs its states with this key; the platform checks them with the public half. Made once and never
    replaced, --rotate included: a new key would make every saved state unverifiable. Private to this user; the
    stack's immudb-key job hands immudb its own copy."""
    key, pub = Path(SIGNING_KEY), Path(SIGNING_PUB)
    if not key.is_file() or key.stat().st_size == 0:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        made = ec.generate_private_key(ec.SECP256R1())
        pub.write_bytes(made.public_key().public_bytes(serialization.Encoding.PEM,
                                                       serialization.PublicFormat.SubjectPublicKeyInfo))
        new = Path(SIGNING_KEY + ".new")
        new.write_bytes(made.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
        private(str(new))
        os.replace(new, key)
        say(f"made {SIGNING_KEY} and {SIGNING_PUB}")
    if os.name != "nt":
        os.chmod(key, 0o600)
        os.chmod(pub, 0o644)


#: Postgres's key and certificate for the Configurator (start --configurator), and its name in them
POSTGRES_TLS_DIR, POSTGRES_TLS_NAME = "postgres-tls", "postgres"


def make_postgres_tls() -> None:
    """The Configurator's Postgres speaks TLS only, with this key and a certificate it signs itself (its clients
    require TLS, not a known certificate: sslmode=require). Made once and kept, --rotate included; private to this
    user. The stack's postgres-tls job hands Postgres its own copy."""
    folder = Path(POSTGRES_TLS_DIR)
    key, cert = folder / "server.key", folder / "server.crt"
    if key.is_file() and key.stat().st_size and cert.is_file() and cert.stat().st_size:
        return
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    folder.mkdir(mode=0o700, exist_ok=True)
    made = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, POSTGRES_TLS_NAME)])
    now = datetime.now(timezone.utc)
    signed = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(made.public_key())
              .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
              .not_valid_after(now + timedelta(days=3650))
              .add_extension(x509.SubjectAlternativeName([x509.DNSName(POSTGRES_TLS_NAME)]), critical=False)
              .sign(made, hashes.SHA256()))
    new = folder / "server.key.new"
    new.write_bytes(made.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                       serialization.NoEncryption()))
    private(str(new))
    cert.write_bytes(signed.public_bytes(serialization.Encoding.PEM))
    private(str(cert))
    os.replace(new, key)
    say(f"made {key} and {cert}")


def write_runtime() -> None:
    """compose takes one --env-file, so the settings and the secrets are combined into one. Also git-ignored,
    also made again from its two sources. The infrastructure passwords come from env.secrets only (a value still
    in the tracked file is dropped), and first: compose expands a setting built from one (REDIS_BACKEND_URL holds
    $REDIS_PASSWORD) with the values defined above it in the file."""
    def infra(line: str) -> bool:
        name = line.split("=", 1)[0]
        return " " not in name and name in FIRST_IN_RUNTIME

    secret_lines, tracked = lines_of(OUT), lines_of(settings_file())
    # this install's own settings (the ports start chose) come last, so compose takes them over the tracked ones
    local = lines_of(LOCAL) if Path(LOCAL).is_file() else []
    # where Caddy publishes the browser ports (caddy_bind_address), before env.local so a line there wins
    combined = ([line for line in secret_lines if infra(line)] + [line for line in tracked if not infra(line)]
                + [line for line in secret_lines if not infra(line)]
                + [f"CADDY_BIND_ADDRESS={caddy_bind_address()}"] + local)
    prefix = container_prefix(install_id())
    if prefix:
        combined.append(f"CONTAINER_PREFIX={prefix}")
    write_beside(COMBINED, text_of(combined))
    say(f"wrote {COMBINED} ({settings_file()} + {OUT}{' + ' + LOCAL if local else ''})")


def make_secrets(args: list[str], hint: bool = True) -> None:
    """The secrets command. hint: end with how to run the stack by hand; start, which runs it itself, does
    not want a refusal of its own to be followed by that."""
    # Every file written here holds secrets or is made from them: private from the moment it exists.
    os.umask(0o077)
    mode = args[0] if args else ""
    if mode not in ("", "--rotate", "--rotate-one", "--add-ledger-key"):
        raise Refused(f"secrets does not take {mode}: it takes --rotate, --rotate-one NAME or --add-ledger-key "
                      "(or nothing, to keep the values and add any that are missing). Nothing changed.", 2)
    existed = Path(OUT).is_file()
    if existed:
        emptied = [name for name in NEVER_MADE_AGAIN if f"{name}=" in lines_of(OUT)]
        if emptied:
            raise Refused(f"{OUT} has an empty {', '.join(emptied)}. A new value would leave what is stored under the "
                          "old one unreadable, so none is made. Put the old value back (from env.runtime, if it still "
                          "holds it, or from a backup of the secrets file), then run this again. Nothing changed.")
    if mode == "--add-ledger-key":
        add_ledger_key()
    elif mode == "--rotate-one":
        rotate_one(args[1] if len(args) > 1 else "")
    rotate = mode == "--rotate"

    if rotate or not existed:
        lines = new_file(rotate, existed)
        made = f"{len(SECRETS)} secrets, {'rotated' if rotate else 'new'}"
    else:
        lines = with_missing_added(existed)
        made = "kept, missing ones added"
    # An empty value is a missing one (an earlier run left NAME=): made again in its place, as a missing one is,
    # so an existing install's infrastructure password takes the value its volume holds.
    for name, kind in SECRETS:
        first = next((line for line in lines if line.startswith(name + "=")), None)
        if first == name + "=":
            lines = with_value(lines, name, missing_value(name, kind, existed))
            say(f"generated the empty {name} again")
    if INSTALL + "=" in lines:
        lines = with_value(lines, INSTALL, new_install_id())
        say(f"generated the empty {INSTALL} again")
    write_beside(OUT, text_of(lines))
    say(f"wrote {OUT} ({made})")
    use_stack(stack_name(install_id()))

    # The one with a shape requirement, checked here rather than discovered by a gateway that will not start.
    length = len(value_in("GATEWAY_COOKIE_SECRET", OUT))
    if length != 43:
        raise Refused(f"GATEWAY_COOKIE_SECRET is {length} characters; oauth2-proxy needs 32 bytes base64url (43)")
    make_signing_key()
    write_runtime()
    if hint:
        say("", "run the stack with:", up_hint())


def show_passwords(_args: list[str]) -> None:
    if not Path(OUT).is_file():
        raise Refused(f"{OUT} does not exist: run scripts/aisc.py secrets (or start) first")
    say(f"admin  {value_in('AISC_ADMIN_PASSWORD', OUT)}", f"user   {value_in('AISC_USER_PASSWORD', OUT)}")


#: a log line holding one of these is hidden whole: it is a secret's name or the secret itself
SECRET_WORDS = re.compile(r"PASSWORD|TOKEN|SECRET|KEY=", re.IGNORECASE)


def hide_secrets(text: str) -> str:
    """Log lines safe to show: a line naming a secret (PASSWORD, TOKEN, SECRET, KEY=) is replaced by a note, and
    the value of every secret in env.secrets is masked wherever else it appears. Without a readable env.secrets
    only the first applies: this runs while reporting a failure and must not fail itself."""
    try:
        values = [v for v in (value_in(name, OUT).strip("'\"") for name, _ in SECRETS) if len(v) >= 4]
    except (OSError, ValueError):
        values = []
    shown = []
    for line in text.splitlines():
        if SECRET_WORDS.search(line):
            line = "[a line naming a secret is hidden]"
        for value in values:
            line = line.replace(value, "***")
        shown.append(line)
    return "\n".join(shown)
