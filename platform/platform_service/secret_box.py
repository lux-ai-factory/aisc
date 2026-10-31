"""The platform's encrypted secrets: the LLM keys, the helper models' keys and the connections' keys and secret
headers, all in the projects' own databases.

Each is a Fernet token. `PLATFORM_SECRETS_KEY` is a comma list of Fernet keys, newest first: the newest
encrypts, any of them decrypts. `ENCRYPTED_COLUMNS` names every column that holds one, and rotation walks it.

Rotation, from `platform/`:

    python -m platform_service.llm_store rotate

re-encrypts every stored token of every project under the newest key and prints counts only. It exits 1
while a token could not be read or a project could not be reached: those may still be under the old key,
so the old key stays in PLATFORM_SECRETS_KEY until a run exits 0.

A stored key belongs to the address it was entered for: `kept_key` lets a save keep it only when the
address keeps its origin (scheme, host, port), so an edit cannot send a stored key to another host.
"""
from __future__ import annotations

import os
import sys
from urllib.parse import urlsplit

import psycopg
from cryptography.fernet import Fernet, InvalidToken, MultiFernet  # noqa: F401  (InvalidToken: for the stores)
from fastapi import HTTPException
from psycopg.conninfo import make_conninfo

#: "leave this column as it is", for the stores' save functions
KEEP = object()

#: (table, the column naming the row, the column holding a token), for every token the platform stores.
ENCRYPTED_COLUMNS = (
    ("llm.provider", "provider", "ciphertext"),
    ("helper.model", "name", "ciphertext"),
    ("connection.endpoint", "name", "secret_ciphertext"),
    ("connection.endpoint", "name", "secret_headers_ciphertext"),
)

ENTER_THE_KEY_AGAIN = ("the address now points to another host than the one the stored key was entered for;"
                       " enter the key again")


class SecretsKeyError(RuntimeError):
    """PLATFORM_SECRETS_KEY is missing or malformed; str() is the 503 detail."""


class KeyUnreadable(RuntimeError):
    """No configured Fernet key decrypts the stored key."""

    def __init__(self, provider: str):
        super().__init__(f"the stored key for {provider} cannot be decrypted; enter it again")


def fernet() -> MultiFernet:
    raw = (os.environ.get("PLATFORM_SECRETS_KEY") or "").strip()
    if not raw:
        raise SecretsKeyError("PLATFORM_SECRETS_KEY is not set")
    keys = [part.strip() for part in raw.split(",") if part.strip()]
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except (ValueError, TypeError):
        raise SecretsKeyError("PLATFORM_SECRETS_KEY is not a list of Fernet keys") from None


def seal(plaintext: str) -> str:
    return fernet().encrypt(plaintext.encode()).decode()


def open(owner: str, token: str) -> str:  # noqa: A001  (the opposite of seal)
    """The plaintext of a token; KeyUnreadable names `owner` when no configured key decrypts it."""
    multi = fernet()
    try:
        return multi.decrypt(token.encode()).decode()
    except InvalidToken:
        raise KeyUnreadable(owner) from None


# the address a key belongs to

_DEFAULT_PORTS = {"http": 80, "https": 443}


def origin(url: str | None) -> tuple[str, str, int | None] | None:
    """(scheme, host, port) of an address, the way a client reaches it: the host lower case, without a
    trailing dot and in its IDNA form, the port its default when none is written. None without an address."""
    if not url:
        return None
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").rstrip(".")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        pass                                              # not a name IDNA takes: compared as written
    try:
        port = parts.port
    except ValueError:
        port = None
    return scheme, host.lower(), port if port is not None else _DEFAULT_PORTS.get(scheme)


def kept_key(before_url: str | None, new_url: str | None, has_stored_key: bool):
    """KEEP when a save that does not send the key may keep the stored one: there is none, or the address
    keeps its origin. Otherwise 422: the key was entered for another host, so it has to be typed again."""
    if not has_stored_key or origin(before_url) == origin(new_url):
        return KEEP
    raise HTTPException(status_code=422, detail=ENTER_THE_KEY_AGAIN)


# rotation

def rotate_column(conn: psycopg.Connection, multi, table: str, key_column: str, column: str) -> tuple[int, int, int]:
    """(rotated, unreadable, changed_meanwhile) for one column of one project's database, on an open
    connection; (0, 0, 0) where the table or the column is not there yet (an older template).

    A token is written back only if it is still the one read: one saved meanwhile was made under the newest
    key already and is left as it is (counted as changed meanwhile)."""
    schema, name = table.split(".")
    if conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = %s AND table_name = %s"
                    " AND column_name = %s", (schema, name, column)).fetchone() is None:
        return 0, 0, 0
    rotated = unreadable = meanwhile = 0
    for row_name, token in conn.execute(f"SELECT {key_column}, {column} FROM {table}"
                                        f" WHERE {column} IS NOT NULL").fetchall():
        try:
            fresh = multi.rotate(token.encode()).decode()
        except InvalidToken:
            unreadable += 1
            continue
        if conn.execute(f"UPDATE {table} SET {column} = %s WHERE {key_column} = %s AND {column} = %s",
                        (fresh, row_name, token)).rowcount:
            rotated += 1
        else:
            meanwhile += 1
    return rotated, unreadable, meanwhile


def rotate_all(base_dsn: str) -> dict[str, int]:
    """Re-encrypt every token of every project (ENCRYPTED_COLUMNS) under the newest Fernet key.

    Never aborts: a project that cannot be reached, one without the llm tables and a token no configured
    Fernet key decrypts are counted and skipped."""
    from platform_service import projectdb

    multi = fernet()
    counts = {"rotated": 0, "projects": 0, "unreadable": 0, "without_llm": 0, "unreachable": 0,
              "changed_meanwhile": 0}
    # a plain connection, not db.pool(): the pool would migrate and provision
    with psycopg.connect(base_dsn) as conn:
        pids = [r[0] for r in conn.execute("SELECT pid FROM core.project ORDER BY created_at").fetchall()]
    for pid in pids:
        try:
            conn = psycopg.connect(make_conninfo(base_dsn, dbname=projectdb.database_name(pid)))
        except psycopg.Error:
            counts["unreachable"] += 1
            continue
        rotated_here = 0
        with conn:
            if conn.execute("SELECT to_regclass('llm.provider')").fetchone()[0] is None:
                counts["without_llm"] += 1
            for table, key_column, column in ENCRYPTED_COLUMNS:
                rotated, unreadable, meanwhile = rotate_column(conn, multi, table, key_column, column)
                rotated_here += rotated
                counts["unreadable"] += unreadable
                counts["changed_meanwhile"] += meanwhile
            conn.commit()
        counts["rotated"] += rotated_here
        if rotated_here:
            counts["projects"] += 1
    return counts


def main(argv: list[str]) -> int:
    if argv != ["rotate"]:
        print("usage: python -m platform_service.llm_store rotate", file=sys.stderr)
        return 2
    try:
        fernet()
    except SecretsKeyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    from platform_service import db

    c = rotate_all(db.dsn())
    print(f"rotated {c['rotated']} keys in {c['projects']} projects ({c['unreadable']} unreadable,"
          f" {c['without_llm']} without llm tables, {c['unreachable']} unreachable,"
          f" {c['changed_meanwhile']} changed meanwhile)")
    if c["unreadable"] or c["unreachable"]:
        print("some keys may still be under an old key: do not remove the old key yet", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
