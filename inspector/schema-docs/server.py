"""Schema diagrams on demand: SchemaSpy's pages for one database, made when asked.

GET /<database>/...  serves SchemaSpy's output for that database, generating it
first when there is none or it is older than MAX_AGE seconds. ?refresh=1 on the
database's own page forces a new run. Only the platform database and project
databases may be named; anything else is refused unread.

It runs behind Caddy's admin gate (:8100/inspect/schema, prefix stripped) and
connects as inspector_ro, which reads and never writes.
"""
from __future__ import annotations

import html
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
PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: What each schema holds, in words, for the landing page. A schema not listed here
#: is still shown, by its name alone.
PROJECT_SCHEMAS = {
    "controls": "Controls checklists, their questions, and the answers submitted for this project.",
    "llm": "LLM keys (stored encrypted, never readable) and the provider and model each agentic system uses.",
    "provision": "Bookkeeping: which template migrations this database has had.",
}
PLATFORM_SCHEMAS = {
    "core": "Projects, their members, and the versions of each project's AI system card.",
    "qualification": "EU AI Act qualification: forms, answers, risks and the AI card's knowledge graph.",
    "control_objectives": "Risk assessments and the control objectives mapped to each risk.",
    "engine": "The execution engine: systems, components, test plugins, evaluations and their results.",
    "catalogue": "The public catalogue of tests and controls.",
    "report_composer": "Report layouts, templates and the reports generated from them.",
}
SCHEMAS = "^(?!pg_|information_schema).*"
SCHEMASPY_JAR = "/usr/local/lib/schemaspy/schemaspy-app.jar"
SCHEMASPY_TIMEOUT = 300
#: How much of SchemaSpy's output to log when a run fails.
FAILURE_TAIL = 2000
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(database: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(database, threading.Lock())


def _index(database: str) -> Path:
    return OUTPUT / database / "index.html"


def _fresh(database: str) -> bool:
    index = _index(database)
    return index.is_file() and time.time() - index.stat().st_mtime < MAX_AGE


def _schemaspy_command(database: str, config: Path, site: Path) -> list[str]:
    return [
        "java", "-jar", SCHEMASPY_JAR,
        "-configFile", str(config),
        "-dp", "/drivers_inc/", "-t", "pgsql11",
        "-host", os.environ.get("PGHOST", "postgres"),
        "-port", os.environ.get("PGPORT", "5432"),
        "-db", database, "-u", "inspector_ro",
        "-all", "-schemaSpec", SCHEMAS,
        # structure only: row counts would tell a project member how much the others hold
        "-norows",
        "-o", str(site),
    ]


def _swap_in(site: Path, database: str) -> None:
    """Replace the database's published site with `site`, keeping the old one
    aside until the new one is in place."""
    target = OUTPUT / database
    old = OUTPUT / (database + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    site.rename(target)
    shutil.rmtree(old, ignore_errors=True)


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
            _schemaspy_command(database, config, site),
            check=True, capture_output=True, timeout=SCHEMASPY_TIMEOUT,
        )
        _swap_in(site, database)
    finally:
        shutil.rmtree(work, ignore_errors=True)


STYLE = """
body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1d2330}
main{max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:24px;margin:0 0 4px} h2{font-size:18px;margin:28px 0 4px}
.lede,.note{color:#556} .note{font-size:13px}
.schema{background:#fff;border:1px solid #dde1e8;border-radius:8px;padding:12px 14px;margin:10px 0}
.schema h3{font-size:15px;margin:0} .schema p{margin:4px 0 8px;color:#445}
.links a{margin-right:14px} summary{cursor:pointer;color:#445;font-size:13px}
.tables{columns:3 180px;margin:6px 0 0;padding-left:18px;font-size:13px}
"""


def _schemas_of(database: str, known: dict[str, str]) -> list[str]:
    """The schemas SchemaSpy made pages for, or the known ones before its first run."""
    site = OUTPUT / database
    made = sorted(p.name for p in site.iterdir() if (p / "index.html").is_file()) if site.is_dir() else []
    return made or list(known)


def _section(title: str, database: str, known: dict[str, str], intro: str) -> str:
    e = html.escape
    parts = [f"<h2>{e(title)}</h2>", f'<p class="lede">{e(intro)} '
             f'<a href="{e(database)}/">Overview of every table</a></p>']
    if not _index(database).is_file():
        parts.append('<p class="note">The first time a database is opened, its diagrams are built: '
                     "allow up to a minute.</p>")
    for schema in _schemas_of(database, known):
        base = f"{database}/{schema}"
        tables = sorted(p.stem for p in (OUTPUT / base / "tables").glob("*.html"))
        listing = ""
        if tables:
            items = "".join(f'<li><a href="{e(base)}/tables/{e(t)}.html">{e(t)}</a></li>' for t in tables)
            listing = f"<details><summary>{len(tables)} tables</summary><ul class=tables>{items}</ul></details>"
        parts.append(
            f'<div class="schema"><h3>{e(schema)}</h3><p>{e(known.get(schema, ""))}</p>'
            f'<div class="links"><a href="{e(base)}/index.html">Tables and columns</a>'
            f'<a href="{e(base)}/relationships.html">Relationship diagram</a></div>{listing}</div>')
    return "".join(parts)


def landing_page(project: str | None) -> str:
    """One page for the diagrams a project member may explore: the project's own
    database first, then the shared one. Structure only, never rows."""
    body = ['<h1>Database diagrams</h1><p class="lede">How the data is organised: tables, columns and '
            "how they link. No data is shown here.</p>"]
    if project:
        body.append(_section("This project", "project_" + project.replace("-", ""), PROJECT_SCHEMAS,
                             "What is kept in this project's own database."))
    body.append(_section("Shared platform", "platform", PLATFORM_SCHEMAS,
                         "Modules that are not per project yet keep their data here, for every project together."))
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>Database diagrams</title><style>{STYLE}</style></head><body><main>"
            + "".join(body) + "</main></body></html>")


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
        if parts.path in ("", "/"):
            project = parse_qs(parts.query).get("project", [""])[0]
            page = landing_page(project if PID.fullmatch(project) else None).encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
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
                    tail = (exc.stdout or b"")[-FAILURE_TAIL:].decode(errors="replace")
                    self.log_error("schemaspy failed for %s: %s", database, tail)
                    if not _index(database).is_file():
                        self.send_error(HTTPStatus.BAD_GATEWAY, "SchemaSpy could not read this database")
                        return
        super().do_GET()


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
