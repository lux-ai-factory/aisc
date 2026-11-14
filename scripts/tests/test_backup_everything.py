"""The backup covers what the stack would lose with its volumes, not only Postgres: the immudb ledger and its
signing key, the MinIO files and the secrets file whose keys open stored secrets and verify the ledger.

Each volume is archived private (0600), restored into a fresh throwaway volume and compared file by file
(`restore-check <volume> PASS`). The secrets file is kept encrypted: the backup never holds its values in
the clear.

Throwaway volumes and a throwaway Postgres only (backup_bed.py); the running stack is never read.
"""
from __future__ import annotations

import subprocess

import pytest

import backup_bed
from conftest import ROOT

SCRIPT = ROOT / "scripts/backup-databases.sh"


@pytest.fixture(scope="module")
def backed_up(tmp_path_factory):
    bed = backup_bed.start(tmp_path_factory.mktemp("backup-bed"))
    out = tmp_path_factory.mktemp("backup-out")
    try:
        r = subprocess.run(["bash", str(SCRIPT), "--dir", str(out)], cwd=ROOT, capture_output=True, text=True,
                           env=bed.env, timeout=600)
        yield r, out, bed
    finally:
        backup_bed.stop(bed)


def test_the_backup_runs(backed_up):
    r, _, _ = backed_up
    assert r.returncode == 0, (r.stdout + r.stderr)[-2000:]


@pytest.mark.parametrize("volume", backup_bed.VOLUMES)
def test_each_volume_is_archived_restored_and_compared(backed_up, volume):
    r, out, _ = backed_up
    archives = [p for p in out.iterdir() if p.name.startswith(volume + "_")]
    assert archives, f"no archive of {volume} in the backup"
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in archives), f"an archive of {volume} is not private"
    assert f"restore-check {volume} PASS" in r.stdout, f"no passing restore check for {volume}"


def test_the_secrets_file_is_backed_up_encrypted(backed_up):
    _, out, _ = backed_up
    copies = [p for p in out.iterdir() if p.name.startswith("secrets_")]
    assert copies, "the secrets file is not in the backup"
    for copy in copies:
        assert copy.stat().st_mode & 0o777 == 0o600, "the secrets copy is not private"
        data = copy.read_bytes()
        clear = [name for name, value in backup_bed.FAKE_SECRETS.items() if value.encode() in data]
        assert not clear, f"the backup holds these values in the clear: {clear}"
