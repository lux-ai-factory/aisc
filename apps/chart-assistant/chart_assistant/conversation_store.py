"""Where conversation states are kept, so a conversation goes on after the assistant restarts: in memory (the tests), or
in the assistant's own database `assistant_state`, made with the role that makes the mock databases. Never a project
database: the assistant holds no credential of one. A state holds what the model was sent (labels, never rows)."""
from __future__ import annotations

import threading
import time
from typing import Callable

import psycopg
from psycopg.types.json import Jsonb

DATABASE = "assistant_state"
#: its own schema: the role is NOINHERIT (init/chart-assistant-role.sql), so owning the database does not give it the
#: rights pg_database_owner holds on public; it may create schemas in a database it owns, as the mock databases do
TABLE = """CREATE SCHEMA IF NOT EXISTS assistant;
CREATE TABLE IF NOT EXISTS assistant.conversation (
    id text PRIMARY KEY,
    pid uuid NOT NULL,
    description jsonb NOT NULL,
    state jsonb NOT NULL,
    used_at timestamptz NOT NULL DEFAULT now())"""


class MemoryStore:
    def __init__(self, clock: Callable[[], float] | None = None):
        self._clock = clock or (lambda: time.monotonic())     # read late: a test may replace time.monotonic
        self._kept: dict[str, tuple[str, dict, dict, float]] = {}
        self._lock = threading.Lock()

    def _idle(self, used: float, max_idle_seconds: int) -> bool:
        return self._clock() - used >= max_idle_seconds

    def save(self, cid: str, pid: str, description: dict, state: dict) -> None:
        with self._lock:
            self._kept[cid] = (pid, description, state, self._clock())

    def load(self, cid: str, max_idle_seconds: int) -> tuple[str, dict, dict] | None:
        with self._lock:
            kept = self._kept.get(cid)
        if kept is None or self._idle(kept[3], max_idle_seconds):
            return None
        return kept[0], kept[1], kept[2]

    def drop_idle(self, max_idle_seconds: int) -> None:
        with self._lock:
            for cid in [c for c, kept in self._kept.items() if self._idle(kept[3], max_idle_seconds)]:
                del self._kept[cid]


class DatabaseStore:
    def __init__(self, admin_url: str):
        self.admin_url = admin_url
        self._url = admin_url.rsplit("/", 1)[0] + "/" + DATABASE
        self._made = False
        self._lock = threading.Lock()

    def _connect(self):
        with self._lock:
            if not self._made:
                with psycopg.connect(self.admin_url, autocommit=True) as admin:
                    if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)).fetchone():
                        admin.execute(f'CREATE DATABASE "{DATABASE}"')
                with psycopg.connect(self._url, autocommit=True) as conn:
                    conn.execute(TABLE)
                self._made = True
        return psycopg.connect(self._url, autocommit=True)

    def save(self, cid: str, pid: str, description: dict, state: dict) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO assistant.conversation (id, pid, description, state) VALUES (%s, %s, %s, %s) "
                         "ON CONFLICT (id) DO UPDATE SET pid = EXCLUDED.pid, description = EXCLUDED.description, "
                         "state = EXCLUDED.state, used_at = now()",
                         (cid, pid, Jsonb(description), Jsonb(state)))

    def load(self, cid: str, max_idle_seconds: int) -> tuple[str, dict, dict] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT pid::text, description, state FROM assistant.conversation "
                               "WHERE id = %s AND now() - used_at < make_interval(secs => %s)",
                               (cid, max_idle_seconds)).fetchone()
        return (row[0], row[1], row[2]) if row else None

    def drop_idle(self, max_idle_seconds: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM assistant.conversation WHERE now() - used_at >= make_interval(secs => %s)",
                         (max_idle_seconds,))
