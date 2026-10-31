"""A project's database: its name, and its address from a service's template.

The database is the project, so its name is derived from the pid alone: `project_` and the pid's 32
lowercase hex digits. Only a pid in its canonical form names one (any case, nothing around it), so a
slug or a pid spelt another way cannot reach a database it does not own.

A template is a URL with `{database}` as its path, its credentials percent-encoded as in any URL.
dsn() drops only the options that are Prisma's own (schema, connection_limit, pool_timeout), which
libpq refuses, and keeps every libpq option (sslmode and the rest). shared/access-ts/projectDb.mjs is
the JavaScript twin; both run projectdb-cases.json.
"""
from __future__ import annotations

import re
from urllib.parse import quote, unquote
from uuid import UUID

PLACEHOLDER = "{database}"
PRISMA_OPTIONS = frozenset({"schema", "connection_limit", "pool_timeout"})
MAINTENANCE_DATABASE = "postgres"

_PID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
_NAME = re.compile(r"project_([0-9a-f]{32})")
_DATABASE = re.compile(r"[a-z_][a-z0-9_]*")
_URL = re.compile(r"(?P<scheme>postgres(?:ql)?)(?:\+[a-z0-9]+)?://(?:(?P<userinfo>[^@/?#]*)@)?"
                  r"(?P<host>[^/?#]*)/(?P<path>[^?#]*)(?:\?(?P<query>[^#]*))?")
_LONE_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")


class NotAPid(ValueError):
    """Only a project id may name a database: anything else is refused unread."""


def database_name(pid: str | UUID) -> str:
    text = str(pid) if isinstance(pid, UUID) else pid
    if not isinstance(text, str) or not _PID.fullmatch(text):
        raise NotAPid(f"not a project id: {pid!r}")
    return "project_" + text.lower().replace("-", "")


def pid_of(name: str) -> str | None:
    """The pid a database name was made from, or None for a database that is no project's."""
    found = _NAME.fullmatch(name or "")
    if found is None:
        return None
    return str(UUID(found.group(1)))


def dsn(template: str, database: str, *, driver: str | None = None) -> str:
    """The template's address of `database`. `driver` names the SQLAlchemy dialect's driver
    (postgresql+psycopg); without one the scheme is plain postgresql, which libpq reads."""
    found = _URL.fullmatch(template or "")
    if found is None or found["path"] != PLACEHOLDER:
        raise ValueError(f"a database template is a postgresql:// URL whose path is {PLACEHOLDER}")
    if not _DATABASE.fullmatch(database or ""):
        raise ValueError(f"not a database name: {database!r}")
    scheme = f"postgresql+{driver}" if driver else "postgresql"
    userinfo = found["userinfo"]
    credentials = "" if userinfo is None else ":".join(_quoted(part) for part in userinfo.split(":", 1)) + "@"
    options = [part for part in (found["query"] or "").split("&")
               if part and unquote(part.split("=", 1)[0]) not in PRISMA_OPTIONS]
    query = "?" + "&".join(options) if options else ""
    return f"{scheme}://{credentials}{found['host']}/{database}{query}"


def maintenance_dsn(template: str, *, driver: str | None = None) -> str:
    """The template's address of the server's maintenance database, where databases are made and dropped."""
    return dsn(template, MAINTENANCE_DATABASE, driver=driver)


def _quoted(part: str) -> str:
    """A user name or password percent-encoded once: an encoded one stays as it is, a raw `{` or `%` is encoded."""
    return quote(unquote(_LONE_PERCENT.sub("%25", part)), safe="!'()*")
