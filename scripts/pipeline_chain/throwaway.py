"""A throwaway Postgres for the pipeline tests, from Python.

The same contract as scripts/lib/throwaway-pg.sh: postgres:15-alpine, a container named
aisc-t-<label>-<hex> on a port the kernel picks on 127.0.0.1, psql run inside the container
(the host has none), removed by `stop()`. Never the host's 5432.
"""

from __future__ import annotations

import json
import secrets
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "postgres:15-alpine"
SU = "aisc-postgres-user"
SHARED_PYTHONPATH = f"{ROOT}/shared/plugin-interface/src:{ROOT}/shared/plugin-manager/src"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Throwaway:
    def __init__(self, name: str, port: int, password: str):
        self.name, self.port, self.password = name, port, password

    @classmethod
    def start(cls, label: str) -> "Throwaway":
        port = free_port()
        assert port != 5432
        t = cls(f"aisc-t-{label}-{secrets.token_hex(4)}", port, secrets.token_hex(12))
        subprocess.run(
            ["docker", "run", "--rm", "-d", "--name", t.name, "-p", f"127.0.0.1:{port}:5432",
             "-e", f"POSTGRES_USER={SU}", "-e", f"POSTGRES_PASSWORD={t.password}",
             "-e", "POSTGRES_DB=platform", IMAGE],
            check=True, capture_output=True)
        for _ in range(60):
            r = subprocess.run(["docker", "exec", t.name, "psql", "-h", "127.0.0.1", "-U", SU,
                                "-d", "platform", "-tAc", "SELECT 1"], capture_output=True)
            if r.returncode == 0:
                return t
            time.sleep(1)
        t.stop()
        raise RuntimeError(f"{t.name} did not come up")

    def stop(self) -> None:
        subprocess.run(["docker", "rm", "-f", self.name], capture_output=True)

    def psql(self, db: str, sql: str, role: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
        role = role or SU
        pw = self.password if role == SU else role
        return subprocess.run(
            ["docker", "exec", "-i", "-e", f"PGPASSWORD={pw}", self.name, "psql", "-X", "-q",
             "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", role, "-d", db, "-f", "-"],
            input=sql, text=True, capture_output=True, check=check)

    def rows(self, db: str, sql: str, role: str | None = None) -> list[dict]:
        """Rows as dicts, through psql's JSON aggregation. psql prints tuples only, unaligned (-t -A), so
        the whole output is the one JSON value, however many lines json_agg spreads it over."""
        wrapped = f"SELECT coalesce(json_agg(t), '[]') FROM ({sql}) t"
        user = role or SU
        pw = self.password if user == SU else user
        r = subprocess.run(
            ["docker", "exec", "-i", "-e", f"PGPASSWORD={pw}", self.name, "psql", "-X", "-q", "-t", "-A",
             "-v", "ON_ERROR_STOP=1", "-h", "127.0.0.1", "-U", user, "-d", db, "-f", "-"],
            input=wrapped.replace("\n", " "), text=True, capture_output=True)
        if r.returncode != 0:
            raise AssertionError(f"query failed as {role or SU} on {db}: {r.stderr.strip()}")
        return json.loads(out) if (out := r.stdout.strip()) else []

    def scalar(self, db: str, sql: str) -> str:
        r = subprocess.run(
            ["docker", "exec", "-e", f"PGPASSWORD={self.password}", self.name, "psql", "-X", "-tA",
             "-h", "127.0.0.1", "-U", SU, "-d", db, "-c", sql], capture_output=True, text=True)
        return r.stdout.strip()

    def dsn(self, role: str, db: str) -> str:
        return f"postgresql://{role}:{role}@127.0.0.1:{self.port}/{db}"


def platform_migration(t: Throwaway, path: Path) -> None:
    """As platform_service.migrate: one transaction as platform_rw, recorded."""
    t.psql("platform", "SET search_path = core;\n"
           "CREATE TABLE IF NOT EXISTS core.schema_migration (name text PRIMARY KEY,"
           " applied_at timestamptz NOT NULL DEFAULT now());\nBEGIN;\n" + path.read_text()
           + f"\n;\nINSERT INTO core.schema_migration (name) VALUES ('{path.name}');\nCOMMIT;\n",
           role="platform_rw")
