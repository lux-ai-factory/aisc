"""A throwaway stand-in for the stack that the backup tests point scripts/backup-databases.sh at.

A Postgres from scripts/lib/throwaway-pg.sh holding the databases the stack has (platform, keycloak, superset
and two project databases, each with a table of rows), and three throwaway named volumes shaped like the
stack's (`<stack>_immudb_data`, `<stack>_immudb_key`, `<stack>_minio_data`) holding a few files. A scratch
secrets file with made-up values stands in for env.secrets, and a scratch passphrase file for the one the
secrets copy is encrypted with. Nothing of the running stack is read or touched:
every name starts with aisc-t-backup-, and everything is removed when the tests end.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from conftest import ROOT

PROJECTS = ("project_" + "a" * 32, "project_" + "b" * 32)
DATABASES = ("platform", "keycloak", "superset", *PROJECTS)
VOLUMES = ("immudb_data", "immudb_key", "minio_data")
FAKE_SECRETS = {"PLATFORM_SECRETS_KEY": "fake-platform-secrets-key-for-the-backup-test",
                "DJANGO_SECRET_KEY": "fake-django-key-for-the-backup-test",
                "PLATFORM_LEDGER_KEYS": "v1:" + "c3" * 32}


def docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


@dataclass
class Bed:
    stack: str
    container: str
    superuser: str
    secrets_file: Path
    databases: tuple = PROJECTS
    volumes: list = field(default_factory=list)

    @property
    def env(self) -> dict:
        return {**os.environ, "BACKUP_PG_CONTAINER": self.container, "POSTGRES_USER": self.superuser,
                "BACKUP_STACK": self.stack, "AISC_SECRETS_FILE": str(self.secrets_file),
                "AISC_BACKUP_PASSPHRASE_FILE": str(self.secrets_file.with_name("backup-passphrase"))}

    def psql(self, db: str, sql: str) -> str:
        return docker("exec", self.container, "psql", "-h", "127.0.0.1", "-U", self.superuser, "-d", db,
                      "-XAtc", sql).stdout


def start(tmp: Path) -> Bed:
    out = subprocess.run(["bash", "-c", '. scripts/lib/throwaway-pg.sh && TPG_OWN_TRAP=1 tpg_start backup >/dev/null'
                          ' && echo "$TPG_NAME" && echo "$TPG_SU"'],
                         cwd=ROOT, capture_output=True, text=True, env={**os.environ, "TPG_OWN_TRAP": "1"})
    assert out.returncode == 0, out.stderr[-2000:]
    name, su = out.stdout.split()[:2]
    stack = f"aisc-t-backup-{uuid.uuid4().hex[:8]}"
    secrets_file = tmp / "env.secrets"
    secrets_file.write_text("".join(f"{k}={v}\n" for k, v in FAKE_SECRETS.items()))
    secrets_file.chmod(0o600)
    # the passphrase the secrets copy is encrypted with: made up, like the secrets
    passphrase = tmp / "backup-passphrase"
    passphrase.write_text("a-made-up-passphrase-for-the-backup-test\n")
    passphrase.chmod(0o600)
    bed = Bed(stack=stack, container=name, superuser=su, secrets_file=secrets_file)
    for db in DATABASES:
        if db != "platform":
            bed.psql("platform", f'CREATE DATABASE "{db}"')
        bed.psql(db, "CREATE SCHEMA core; CREATE TABLE core.project (id int primary key, name text);"
                     " INSERT INTO core.project SELECT g, 'p' || g FROM generate_series(1, 7) g")
    for volume in VOLUMES:
        full = f"{stack}_{volume}"
        docker("volume", "create", full)
        bed.volumes.append(full)
        docker("run", "--rm", "-v", f"{full}:/v", "postgres:15-alpine", "sh", "-c",
               f"mkdir -p /v/sub && for i in 1 2 3; do echo {volume}-$i > /v/sub/f$i; done && chmod 600 /v/sub/f1")
    return bed


def stop(bed: Bed) -> None:
    docker("rm", "-fv", bed.container, check=False)
    for volume in bed.volumes:
        docker("volume", "rm", "-f", volume, check=False)
