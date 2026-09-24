"""Credentials of the systems we connect to: encrypted at rest, never read back (spec D7).

Only the executor calls plain(). Every other caller gets the masked form.
"""
from __future__ import annotations

import uuid

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from aisc_connectors import db
from aisc_connectors.settings import settings

SECRET_NAMES = frozenset(
    {"api_key", "token", "password", "client_secret", "client_cert", "client_key", "ca_bundle"}
)

_UNREADABLE = "a stored secret cannot be decrypted with CONNECTOR_SECRETS_KEY (was a key removed?)"


class VaultMisconfigured(RuntimeError):
    """No usable CONNECTOR_SECRETS_KEY."""


class SecretUnreadable(VaultMisconfigured):
    """A stored secret does not decrypt under any configured key."""


class UnknownSecretName(ValueError):
    pass


def _fernet() -> MultiFernet:
    keys = [k.strip() for k in settings().secrets_key.split(",") if k.strip()]
    if not keys:
        raise VaultMisconfigured("CONNECTOR_SECRETS_KEY is not set")
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except ValueError as exc:
        raise VaultMisconfigured("CONNECTOR_SECRETS_KEY is not a list of Fernet keys") from exc


def mask(value: str) -> str:
    return "****" if len(value) <= 8 else f"{value[:2]}****{value[-2:]}"


def put(connector_pid: uuid.UUID, name: str, value: str) -> dict:
    if name not in SECRET_NAMES:
        raise UnknownSecretName(f"{name!r} is not one of {sorted(SECRET_NAMES)}")
    ciphertext = _fernet().encrypt(value.encode()).decode()
    with db.pool().connection() as conn:
        return conn.execute(
            "INSERT INTO connector.secret (connector_pid, name, ciphertext, masked)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (connector_pid, name) DO UPDATE"
            "   SET ciphertext = excluded.ciphertext, masked = excluded.masked, updated_at = now()"
            " RETURNING name, masked, updated_at",
            (connector_pid, name, ciphertext, mask(value)),
        ).fetchone()


def describe(connector_pid: uuid.UUID) -> list[dict]:
    with db.pool().connection() as conn:
        return conn.execute(
            "SELECT name, masked, updated_at FROM connector.secret WHERE connector_pid = %s ORDER BY name",
            (connector_pid,),
        ).fetchall()


def delete(connector_pid: uuid.UUID, name: str) -> bool:
    with db.pool().connection() as conn:
        return conn.execute(
            "DELETE FROM connector.secret WHERE connector_pid = %s AND name = %s", (connector_pid, name)
        ).rowcount == 1


def plain(connector_pid: uuid.UUID, name: str) -> str | None:
    with db.pool().connection() as conn:
        row = conn.execute(
            "SELECT ciphertext FROM connector.secret WHERE connector_pid = %s AND name = %s",
            (connector_pid, name),
        ).fetchone()
    if row is None:
        return None
    try:
        return _fernet().decrypt(row["ciphertext"].encode()).decode()
    except InvalidToken as exc:
        raise SecretUnreadable(_UNREADABLE) from exc


def rotate() -> int:
    fernet = _fernet()
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT connector_pid, name, ciphertext FROM connector.secret").fetchall()
        for row in rows:
            try:
                rotated = fernet.rotate(row["ciphertext"].encode())
            except InvalidToken as exc:
                raise SecretUnreadable(_UNREADABLE) from exc
            conn.execute(
                "UPDATE connector.secret SET ciphertext = %s WHERE connector_pid = %s AND name = %s",
                (rotated.decode(), row["connector_pid"], row["name"]),
            )
    return len(rows)
