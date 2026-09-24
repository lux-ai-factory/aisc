"""Schema diagrams on demand: SchemaSpy's pages for one database, made when asked.

GET /<database>/...  serves SchemaSpy's output for that database, generating it
first when there is none or it is older than MAX_AGE seconds. ?refresh=1 on the
database's own page forces a new run. Only the platform database and project
databases may be named; anything else is refused unread.

It runs behind Caddy's admin gate (:8100/inspect/schema, prefix stripped) and
connects as inspector_ro, which reads and never writes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

OUTPUT = Path(os.environ.get("SCHEMA_DOCS_OUTPUT", "/srv/schema-docs"))
#: Beside OUTPUT, never under it: the run's properties file holds the password.
WORK = OUTPUT.parent / (OUTPUT.name + "-work")
MAX_AGE = int(os.environ.get("SCHEMA_DOCS_MAX_AGE", "600"))
DATABASE = re.compile(r"^(platform|project_[0-9a-f]{32})$")
SCHEMAS = "^(?!pg_|information_schema).*"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(database: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(database, threading.Lock())


def _fresh(database: str) -> bool:
    index = OUTPUT / database / "index.html"
    return index.is_file() and time.time() - index.stat().st_mtime < MAX_AGE


def generate(database: str) -> None:
    """Run SchemaSpy into a scratch folder and swap it in, so a reader never
    sees half a site. The password goes in a properties file, not argv."""
    work = Path(tempfile.mkdtemp(prefix=database + ".", dir=WORK))
    config = work / "schemaspy.properties"
    config.write_text(f"schemaspy.p={os.environ['INSPECTOR_PASSWORD']}\n")
    config.chmod(0o600)
    site = work / "site"
    try:
        subprocess.run(
            [
                "java", "-jar", "/usr/local/lib/schemaspy/schemaspy-app.jar",
                "-configFile", str(config),
                "-dp", "/drivers_inc/", "-t", "pgsql11",
                "-host", os.environ.get("PGHOST", "postgres"),
                "-port", os.environ.get("PGPORT", "5432"),
                "-db", database, "-u", "inspector_ro",
                "-all", "-schemaSpec", SCHEMAS,
                "-o", str(site),
            ],
            check=True, capture_output=True, timeout=300,
        )
        target = OUTPUT / database
        old = OUTPUT / (database + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        site.rename(target)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(OUTPUT), **kwargs)

    def do_GET(self):  # noqa: N802 (http.server's name)
        parts = urlsplit(self.path)
        database = parts.path.strip("/").split("/", 1)[0]
        if parts.path == "/health":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return
        if not DATABASE.fullmatch(database) or ".." in parts.path.split("/"):
            self.send_error(HTTPStatus.NOT_FOUND, "Not a database this shows")
            return
        if parts.path == "/" + database:
            # SchemaSpy's links are relative: its index must be read as a folder.
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            self.send_header("Location", database + "/" + ("?" + parts.query if parts.query else ""))
            self.end_headers()
            return
        refresh = "1" in parse_qs(parts.query).get("refresh", [])
        with _lock(database):
            if refresh or not _fresh(database):
                try:
                    generate(database)
                except subprocess.CalledProcessError as exc:
                    tail = (exc.stdout or b"")[-2000:].decode(errors="replace")
                    self.log_error("schemaspy failed for %s: %s", database, tail)
                    if not (OUTPUT / database / "index.html").is_file():
                        self.send_error(HTTPStatus.BAD_GATEWAY, "SchemaSpy could not read this database")
                        return
        super().do_GET()


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
