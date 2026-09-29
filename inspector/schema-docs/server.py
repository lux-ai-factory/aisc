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

#: What each schema holds, for the landing page: a title a person reads, then a sentence.
#: A schema not listed here is still shown, under its own name.
PROJECT_SCHEMAS = {
    "project": ("AI card versions", "Every saved version of this project's AI system card, numbered; only the latest changes."),
    "qualification": ("Qualification", "EU AI Act qualification: forms, answers, risks and the AI card's knowledge graph."),
    "controls": ("Controls", "Controls checklists, their questions, and the answers submitted for this project."),
    "control_objectives": ("Control objectives", "Risk assessments and the control objectives mapped to each risk."),
    "engine": ("Execution engine", "Systems, components, test plugins, evaluations and their results."),
    "report_composer": ("Reports", "Report layouts, templates and the reports generated from them."),
    "llm": ("LLM keys and models", "LLM keys (stored encrypted, never readable) and the provider and model each agentic system uses."),
    "connection": ("Connections", "The systems this project assesses over the network, and their keys (stored encrypted, never readable)."),
    "provision": ("Provisioning", "Bookkeeping: which template migrations this database has had."),
}
PLATFORM_SCHEMAS = {
    "core": ("Projects and their members", "Every project, and who may work in it with which role."),
    "catalogue": ("Catalogue", "The public catalogue of tests and controls."),
    "report_library": ("Report presets", "Shared report presets, which hold no project data."),
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


#: The launcher's look (homepage/project.html): Inter and IBM Plex Mono, electric blue with a
#: hot-pink accent, square corners, hairlines, a faint blueprint grid, oversized numerals.
STYLE = """
:root{--bg:#fbfbfd;--panel:#fff;--text:#000;--muted:#474c60;--faint:#6b7288;--primary:#000fdf;
--accent:#ff007e;--border:#d3d8e6;--border-strong:#a9b0c6;
--mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box} html,body{margin:0}
body{position:relative;min-height:100vh;background:var(--bg);color:var(--text);
font:15px/1.5 "Inter",ui-sans-serif,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
background-image:linear-gradient(to right,rgba(0,15,223,.065) 1px,transparent 1px),
linear-gradient(to bottom,rgba(0,15,223,.065) 1px,transparent 1px);background-size:40px 40px;
-webkit-mask-image:radial-gradient(ellipse 90% 70% at 50% 30%,#000 35%,transparent 100%);
mask-image:radial-gradient(ellipse 90% 70% at 50% 30%,#000 35%,transparent 100%)}
body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:0;
background:radial-gradient(900px 420px at 8% -8%,rgba(0,15,223,.07),transparent 70%),
radial-gradient(700px 360px at 104% 108%,rgba(255,0,126,.06),transparent 70%)}
.topbar{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:22px;padding:16px 32px;
border-bottom:1px solid var(--border);background:rgba(255,255,255,.82);backdrop-filter:blur(8px)}
.topbar img{height:32px;display:block}
.topbar .rule{width:1px;height:28px;background:var(--border-strong)}
.topbar .name{margin:0;font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.14em}
.btn{font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--primary);
text-decoration:none;border:1px solid var(--border-strong);padding:7px 11px;white-space:nowrap;background:var(--panel)}
.btn:hover{background:var(--primary);color:#fff;border-color:var(--primary)}
main{position:relative;z-index:1;max-width:1240px;margin:0 auto;padding:44px 32px 64px}
.kicker{font-family:var(--mono);font-size:11px;font-weight:500;letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}
h1{margin:10px 0 8px;font-size:34px;font-weight:600;letter-spacing:-.022em;line-height:1.15}
.lede{margin:0;color:var(--muted);max-width:62ch}
section{margin-top:48px}
.head{display:flex;align-items:flex-end;gap:18px;padding-bottom:14px;border-bottom:1px solid var(--border-strong)}
.head .no{font-family:var(--mono);font-weight:600;font-size:13px;color:var(--primary)}
.head h2{margin:0;font-size:22px;font-weight:600;letter-spacing:-.018em}
.head p{margin:0 0 2px;color:var(--muted);font-size:14px;flex:1}
.shared .head .no{color:var(--accent)}
.shared .btn{color:var(--accent)} .shared .btn:hover{background:var(--accent);border-color:var(--accent);color:#fff}
.note{margin:14px 0 0;font-family:var(--mono);font-size:11.5px;color:var(--faint)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:18px;margin-top:20px}
.card{position:relative;overflow:hidden;display:flex;flex-direction:column;padding:24px 26px 20px;
background:var(--panel);border:1px solid var(--border);animation:rise .5s cubic-bezier(.22,.61,.36,1) both;
transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease}
.card::before{content:"";position:absolute;top:0;left:0;right:0;height:3px;background:var(--primary);
transform:scaleX(0);transform-origin:left;transition:transform .22s cubic-bezier(.22,.61,.36,1)}
.shared .card::before{background:var(--accent)}
.card:hover{border-color:var(--primary);box-shadow:0 10px 28px rgba(12,18,60,.09);transform:translateY(-3px)}
.shared .card:hover{border-color:var(--accent)}
.card:hover::before{transform:scaleX(1)}
.count{position:absolute;top:6px;right:16px;font-family:var(--mono);font-weight:600;font-size:76px;line-height:1;
color:rgba(0,15,223,.16);font-variant-numeric:tabular-nums;pointer-events:none;user-select:none}
.shared .count{color:rgba(255,0,126,.16)}
.tag{font-family:var(--mono);font-size:11px;font-weight:500;letter-spacing:.1em;text-transform:uppercase;color:var(--faint)}
.card h3{margin:18px 0 6px;font-size:18px;font-weight:600;letter-spacing:-.014em;line-height:1.25;max-width:80%}
.card p{margin:0;color:var(--muted);font-size:14px}
.go{display:flex;gap:20px;margin-top:auto;padding-top:18px}
.go a{display:inline-flex;align-items:center;gap:7px;font-family:var(--mono);font-size:10.5px;font-weight:500;
letter-spacing:.12em;text-transform:uppercase;color:var(--primary);text-decoration:none}
.shared .go a{color:var(--accent)}
.go a span{transition:transform .16s ease} .go a:hover span{transform:translateX(4px)}
.go a:hover{text-decoration:underline;text-underline-offset:3px}
details{margin-top:14px;border-top:1px solid var(--border);padding-top:10px}
summary{cursor:pointer;font-family:var(--mono);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint)}
summary:hover{color:var(--text)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0 2px;padding:0;list-style:none}
.chips a{display:block;font-family:var(--mono);font-size:12px;color:var(--text);text-decoration:none;
padding:3px 8px;border:1px solid var(--border)}
.chips a:hover{border-color:var(--primary);color:var(--primary)}
.shared .chips a:hover{border-color:var(--accent);color:var(--accent)}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.card{animation:none;transition:none}}
@media (max-width:640px){.topbar{padding:12px 16px;gap:12px}.topbar .name,.topbar .rule{display:none}
main{padding:28px 16px 48px}.head{flex-wrap:wrap;align-items:baseline;gap:10px 14px}
.head p{flex-basis:100%;order:3}.head .btn{margin-left:auto}.grid{grid-template-columns:1fr}}
"""


def _schemas_of(database: str, known: dict) -> list[str]:
    """The schemas SchemaSpy made pages for, or the known ones before its first run."""
    site = OUTPUT / database
    made = sorted(p.name for p in site.iterdir() if (p / "index.html").is_file()) if site.is_dir() else []
    return made or list(known)


def _card(database: str, schema: str, known: dict, delay: int) -> str:
    e = html.escape
    title, sentence = known.get(schema, (schema.replace("_", " ").capitalize(), ""))
    base = f"{database}/{schema}"
    tables = sorted(p.stem for p in (OUTPUT / base / "tables").glob("*.html"))
    count = f'<span class="count" aria-hidden="true">{len(tables)}</span>' if tables else ""
    listing = ""
    if tables:
        noun = "table" if len(tables) == 1 else "tables"
        chips = "".join(f'<li><a href="{e(base)}/tables/{e(t)}.html">{e(t)}</a></li>' for t in tables)
        listing = f'<details><summary>Show {len(tables)} {noun}</summary><ul class="chips">{chips}</ul></details>'
    return (f'<div class="card" style="animation-delay:{delay}ms">{count}'
            f'<span class="tag">{e(schema)}</span><h3>{e(title)}</h3><p>{e(sentence)}</p>'
            f'<div class="go"><a href="{e(base)}/index.html">Tables <span>&rarr;</span></a>'
            f'<a href="{e(base)}/relationships.html">Diagram <span>&rarr;</span></a></div>{listing}</div>')


def _section(number: str, title: str, database: str, known: dict, intro: str, css: str, start: int) -> str:
    e = html.escape
    note = ("" if _index(database).is_file() else
            '<p class="note">The first time a database is opened, its diagrams are built: allow up to a minute.</p>')
    cards = "".join(_card(database, schema, known, start + 60 * i)
                    for i, schema in enumerate(_schemas_of(database, known)))
    return (f'<section class="{css}"><div class="head"><span class="no">{number}</span><h2>{e(title)}</h2>'
            f'<p>{e(intro)}</p><a class="btn" href="{e(database)}/">Every table</a></div>'
            f'{note}<div class="grid">{cards}</div></section>')


def landing_page(project: str | None) -> str:
    """One page for the diagrams a project member may explore: the project's own
    database first, then the shared one. Structure only, never rows."""
    back = (f'<a class="btn" href="/p/{html.escape(project)}">&larr; Project</a>' if project
            else '<a class="btn" href="/">&larr; Projects</a>')
    sections = []
    if project:
        sections.append(_section("01", "This project", "project_" + project.replace("-", ""), PROJECT_SCHEMAS,
                                 "What is kept in this project's own database.", "own", 0))
    sections.append(_section("02" if project else "01", "Shared platform", "platform", PLATFORM_SCHEMAS,
                             "What every project shares: the list of projects and their members, the catalogue and the two libraries.",
                             "shared", 180))
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            "<title>Database diagrams</title><link rel=icon href=/assets/laif-logo.svg>"
            "<link rel=preconnect href=https://fonts.googleapis.com>"
            "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&amp;"
            "family=IBM+Plex+Mono:wght@400;500;600&amp;display=swap' rel=stylesheet>"
            f"<style>{STYLE}</style></head><body>"
            f'<div class="topbar">{back}<img src="/assets/laif-logo.svg" alt="Luxembourg AI Factory">'
            '<span class="rule"></span><p class="name">AI Assessment Sandbox Configurator</p></div>'
            '<main><span class="kicker">Inspect database</span><h1>Database diagrams</h1>'
            '<p class="lede">How the data is organised: tables, columns and how they link. No data is shown here.</p>'
            + "".join(sections) + "</main></body></html>")


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
