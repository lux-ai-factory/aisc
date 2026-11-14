"""A backup restores into working services: back up while they run, wipe them, restore, and count the same.

A throwaway immudb (the stack's image, its data and signing key on volumes named as the stack names them),
a throwaway MinIO (the stack's own image) and a throwaway Postgres (backup_bed.py) hold made-up entries,
objects and rows, and a scratch secrets file holds made-up values. scripts/backup-databases.sh backs them up
while they run (it pauses the containers that use a volume while it archives it). Then every container,
volume and database is removed, and each part is restored with the commands of
docs/runbooks/restore-a-backup.md. The services start again on what was restored, and the ledger entries, the
objects and the rows are counted: the same numbers as before. Every name starts with aisc-t-backup-; the
running stack is never read.

    cd scripts/tests && uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' pytest -q -p no:cacheprovider test_backup_restore_real_services.py
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import time

import psycopg
import pytest

import backup_bed
from conftest import ROOT

SCRIPT = ROOT / "scripts/backup-databases.sh"
HELPER = "postgres:15-alpine"
IMMUDB_IMAGE = "codenotary/immudb:1.11.1"
MINIO_IMAGE = "aisc-minio:latest"
IMMUDB_PASSWORD = "Az9-made-up-for-the-test"
MINIO_USER, MINIO_PASSWORD = "backuptest", "made-up-minio-password-for-the-test"
ENTRIES, OBJECTS = 25, 12
docker = backup_bed.docker


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait(check, what):
    for _ in range(60):
        try:
            if check():
                return
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(1)
    pytest.fail(f"{what} did not come up")


class Services:
    """immudb and MinIO on the stack-named volumes, started and removed on demand."""

    def __init__(self, stack):
        self.stack = stack
        self.immudb = f"{stack}-immudb"
        self.minio = f"{stack}-minio"
        self.port = 0

    def start(self):
        self.port = _free_port()
        docker("run", "-d", "--name", self.immudb, "-p", f"127.0.0.1:{self.port}:5432",
               "-e", f"IMMUDB_ADMIN_PASSWORD={IMMUDB_PASSWORD}", "-e", "IMMUDB_SIGNINGKEY=/keys/signing.key",
               "-v", f"{self.stack}_immudb_data:/var/lib/immudb", "-v", f"{self.stack}_immudb_key:/keys:ro",
               IMMUDB_IMAGE)
        docker("run", "-d", "--name", self.minio, "-e", f"MINIO_ROOT_USER={MINIO_USER}",
               "-e", f"MINIO_ROOT_PASSWORD={MINIO_PASSWORD}", "-v", f"{self.stack}_minio_data:/data",
               "--entrypoint", "/usr/bin/minio", MINIO_IMAGE, "server", "/data")
        _wait(lambda: self.ledger().close() is None, "immudb")
        _wait(lambda: docker("exec", self.minio, "mc", "ready", "local", check=False).returncode == 0, "minio")

    def remove(self):
        for name in (self.immudb, self.minio):
            docker("rm", "-fv", name, check=False)

    def ledger(self):
        return psycopg.connect(host="127.0.0.1", port=self.port, user="immudb", password=IMMUDB_PASSWORD,
                               dbname="defaultdb", autocommit=True, sslmode="disable", connect_timeout=3)

    def entries(self):
        with self.ledger() as conn:
            rows = conn.execute("SELECT COUNT(*) FROM entry", prepare=False).fetchall()
        return rows[0][0]

    def mc(self, *args):
        url = f"http://{MINIO_USER}:{MINIO_PASSWORD}@localhost:9000"
        return docker("exec", "-e", f"MC_HOST_t={url}", self.minio, "mc", *args)

    def objects(self):
        out = self.mc("ls", "--recursive", "t/artifacts").stdout
        return len([line for line in out.splitlines() if line.strip()])


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    if not shutil.which("docker") or docker("info", check=False).returncode != 0:
        pytest.fail("docker is not available")
    if docker("image", "inspect", MINIO_IMAGE, check=False).returncode != 0:
        pytest.fail(f"{MINIO_IMAGE} is not built (docker compose build minio)")
    tmp = tmp_path_factory.mktemp("backup-real")
    bed = backup_bed.start(tmp)
    services = Services(bed.stack)
    extra = []
    try:
        # the bed's volumes hold sample files; the real services start on empty ones of the same names
        for volume in bed.volumes:
            docker("volume", "rm", "-f", volume)
            docker("volume", "create", volume)
        key = tmp / "signing.key"
        subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(key)],
                       check=True, capture_output=True)
        subprocess.run(["docker", "run", "-i", "--rm", "-v", f"{bed.stack}_immudb_key:/v", HELPER, "sh", "-c",
                        "cat > /v/signing.key && chown 3322:3322 /v/signing.key && chmod 400 /v/signing.key"],
                       input=key.read_bytes(), check=True, capture_output=True)
        services.start()
        with services.ledger() as conn:
            conn.execute("CREATE TABLE entry (id INTEGER, note VARCHAR, PRIMARY KEY id)", prepare=False)
            for i in range(1, ENTRIES + 1):
                conn.execute(f"INSERT INTO entry (id, note) VALUES ({i}, 'entry {i}')", prepare=False)
        services.mc("mb", "t/artifacts")
        for i in range(OBJECTS):
            docker("exec", services.minio, "sh", "-c", f"echo object {i} > /tmp/o{i}")
            services.mc("cp", f"/tmp/o{i}", f"t/artifacts/run-{i % 3}/o{i}.txt")
        yield bed, services, tmp, extra
    finally:
        services.remove()
        for name in extra:
            docker("rm", "-fv", name, check=False)
        backup_bed.stop(bed)


def test_a_backup_of_running_services_restores_into_working_services_with_the_same_counts(world):
    bed, services, tmp, extra = world
    assert services.entries() == ENTRIES and services.objects() == OBJECTS
    rows = {db: bed.psql(db, "SELECT count(*) FROM core.project").strip() for db in backup_bed.DATABASES}
    out = tmp / "backup"
    r = subprocess.run(["bash", str(SCRIPT), "--dir", str(out)], cwd=ROOT, capture_output=True, text=True,
                       env=bed.env, timeout=900)
    assert r.returncode == 0, (r.stdout + r.stderr)[-3000:]
    assert docker("inspect", "-f", "{{.State.Status}}", services.immudb).stdout.strip() == "running", \
        "immudb was left paused"

    # wipe: the services, their volumes and the Postgres with every database
    services.remove()
    for volume in bed.volumes:
        docker("volume", "rm", "-f", volume)
    docker("rm", "-fv", bed.container)

    # restore, as the runbook says
    for volume in backup_bed.VOLUMES:
        archive = sorted(out.glob(f"{volume}_2*.tar.gz"))[-1]
        docker("volume", "create", f"{bed.stack}_{volume}")
        restored = subprocess.run(
            f'gzip -dc "{archive}" | docker run -i --rm -v "{bed.stack}_{volume}:/v" {HELPER} '
            "tar --numeric-owner -C /v -xpf -", shell=True, capture_output=True, text=True)
        assert restored.returncode == 0, restored.stderr[-1000:]
    fresh = subprocess.run(["bash", "-c", '. scripts/lib/throwaway-pg.sh && TPG_OWN_TRAP=1 tpg_start backup '
                            '>/dev/null && echo "$TPG_NAME"'], cwd=ROOT, capture_output=True, text=True)
    assert fresh.returncode == 0, fresh.stderr[-1000:]
    pg = fresh.stdout.split()[0]
    extra.append(pg)
    for db in backup_bed.DATABASES:
        dump = sorted(out.glob(f"{db}_2*.dump"))[-1]
        if db != "platform":
            docker("exec", pg, "psql", "-X", "-q", "-U", bed.superuser, "-d", "postgres", "-c",
                   f'CREATE DATABASE "{db}"')
        with dump.open("rb") as f:
            done = subprocess.run(["docker", "exec", "-i", pg, "pg_restore", "--exit-on-error", "-U", bed.superuser,
                                   "-d", db], stdin=f, capture_output=True)
        assert done.returncode == 0, done.stderr[-1000:]
    copy = sorted(out.glob("secrets_2*.enc"))[-1]
    opened = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-md", "sha256",
                             "-pass", f"file:{bed.env['AISC_BACKUP_PASSPHRASE_FILE']}", "-in", str(copy)],
                            capture_output=True)
    assert opened.returncode == 0

    # count
    services.start()
    _wait(lambda: services.entries() == ENTRIES, "the restored ledger")
    assert services.entries() == ENTRIES, "the restored immudb does not hold every entry"
    assert services.objects() == OBJECTS, "the restored MinIO does not hold every object"
    for db, count in rows.items():
        got = docker("exec", pg, "psql", "-X", "-At", "-U", bed.superuser, "-d", db, "-c",
                     "SELECT count(*) FROM core.project").stdout.strip()
        assert got == count, f"{db}: {got} rows restored, {count} backed up"
    assert opened.stdout == bed.secrets_file.read_bytes(), "the secrets copy does not open to the secrets file"
