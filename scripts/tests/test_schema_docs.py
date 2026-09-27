"""The database diagrams: one landing page for a project's database and the shared one (2026-09-25).

inspector/schema-docs/server.py is loaded from its file with its output in a temporary
folder and served on a free port. SchemaSpy itself is never run: a generated site is
faked by writing the files SchemaSpy would.
"""
import html
import importlib.util
import threading
import urllib.error
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "inspector" / "schema-docs" / "server.py"
PID = str(uuid.uuid4())
DB = "project_" + PID.replace("-", "")


@pytest.fixture
def docs(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEMA_DOCS_OUTPUT", str(tmp_path / "out"))
    spec = importlib.util.spec_from_file_location("schema_docs_server", SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUTPUT.mkdir(parents=True)
    module.WORK.mkdir(parents=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    module.base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield module
    httpd.shutdown()


def fake_site(module, database, tables):
    """What SchemaSpy leaves: <db>/index.html, <db>/<schema>/index.html and tables/<t>.html."""
    (module.OUTPUT / database).mkdir()
    (module.OUTPUT / database / "index.html").write_text("site")
    for schema, names in tables.items():
        folder = module.OUTPUT / database / schema / "tables"
        folder.mkdir(parents=True)
        (module.OUTPUT / database / schema / "index.html").write_text(schema)
        for name in names:
            (folder / f"{name}.html").write_text(name)


def get(module, path):
    try:
        with urllib.request.urlopen(module.base + path, timeout=5) as res:
            return res.status, res.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_schemaspy_never_counts_rows():
    """Row counts would tell a member how much the other projects hold."""
    text = SERVER.read_text()
    assert '"-norows"' in text


def test_the_landing_page_shows_the_project_and_the_shared_platform(docs):
    status, body = get(docs, f"/?project={PID}")
    assert status == 200
    assert "Database diagrams" in body
    assert f'href="{DB}/"' in body
    assert 'href="platform/"' in body
    assert "This project" in body and "Shared platform" in body


def test_each_schema_is_explained_and_linked_to_its_tables_and_diagram(docs):
    fake_site(docs, DB, {"controls": ["checklist", "submission"], "llm": ["provider"]})
    fake_site(docs, "platform", {"core": ["project"], "qualification": ["qualification"]})
    _, body = get(docs, f"/?project={PID}")
    for db, schema in ((DB, "controls"), (DB, "llm"), ("platform", "core"), ("platform", "qualification")):
        assert f'href="{db}/{schema}/index.html"' in body, schema
        assert f'href="{db}/{schema}/relationships.html"' in body, schema
    assert f'href="{DB}/controls/tables/checklist.html"' in body
    assert 'href="platform/core/tables/project.html"' in body
    assert "LLM keys" in body          # a sentence a person can read, not only the schema name
    assert "encrypted" in body


def test_a_database_not_generated_yet_says_opening_it_builds_it(docs):
    _, body = get(docs, f"/?project={PID}")
    assert "first time" in body.lower()


def test_without_a_project_only_the_shared_platform_is_offered(docs):
    for query in ("", "?project=", "?project=not-a-uuid", '?project="><script>'):
        status, body = get(docs, "/" + query)
        assert status == 200
        assert "project_" not in body.replace("project_member", "")
        assert "<script>" not in body
        assert 'href="platform/"' in body


def test_what_the_page_prints_is_escaped(docs):
    fake_site(docs, "platform", {"core": ['x"><img src=y>']})
    _, body = get(docs, "/")
    assert '"><img' not in body
    assert html.escape('x"><img src=y>', quote=True) in body or "img src" not in body


def test_the_other_routes_are_unchanged(docs):
    assert get(docs, "/health")[0] == 204
    assert get(docs, "/keycloak/")[0] == 404


# ── the Manage menu on the project page ─────────────────────────────────────

import re  # noqa: E402

PAGE = ROOT / "homepage" / "project.html"


def menu_and_script():
    text = PAGE.read_text()
    menu = re.search(r'<details[^>]*id="manage".*?</details>', text, re.S).group(0)
    script = text[text.index("<script>"):]
    return menu, script


def test_one_entry_for_the_diagrams_and_it_opens_the_landing_page_on_this_project():
    menu, script = menu_and_script()
    assert menu.count("/inspect/schema") == 0, "the menu links no database directly any more"
    links = re.findall(r'<a\b[^>]*id="inspect-schema"[^>]*>(.*?)</a>', menu, re.S)
    assert links == ["Database diagrams"]
    assert re.search(r"getElementById\('inspect-schema'\)\.href\s*=\s*'/inspect/schema/\?project='\s*\+\s*"
                     r"encodeURIComponent\(p\.pid\)", script)
    assert "Schema diagrams" not in menu


def test_pgadmin_and_the_other_admin_tools_stay_admin_only():
    menu, script = menu_and_script()
    for element_id in ("inspect-pgadmin", "llm-settings", "delete-open"):
        tag = re.search(rf'<(a|button)\b[^>]*id="{element_id}"[^>]*>', menu).group(0)
        assert "admin-only" in tag and "hidden" in tag, element_id
    assert 'href="/inspect/pgadmin/"' in menu
    member_gate = script.index("getElementById('inspect-schema').href")
    admin_gate = script.index("if (!a.admin) return;")
    assert member_gate < admin_gate < script.index(".admin-only"), "admin tools are revealed after the admin check"


def test_a_member_sees_the_menu_and_a_stranger_does_not():
    _, script = menu_and_script()
    assert "if (!a || !(a.role || a.admin)) return;" in script
    assert script.index("if (!a || !(a.role || a.admin)) return;") < script.index("getElementById('manage').hidden = false")


def test_hidden_menu_items_really_are_hidden():
    """.panel a sets display, which would override the hidden attribute."""
    assert re.search(r"\.manage\s+\.panel\s+\[hidden\]\s*\{\s*display\s*:\s*none", PAGE.read_text())


# ── Caddy asks the platform which diagrams a caller may see ─────────────────


def caddy_block(prefix):
    text = (ROOT / "Caddyfile").read_text()
    start = text.index(prefix)
    return text[start:text.index("\n    }", start)]


def test_the_diagrams_ask_the_schema_gate_not_the_admin_gate():
    block = caddy_block("handle_path /inspect/schema*")
    assert "import protect" in block and "import schema_gate" in block
    assert "admin_only" not in block
    snippet = (ROOT / "Caddyfile").read_text()
    gate = snippet[snippet.index("(schema_gate) {"):]
    assert "forward_auth platform:8000" in gate[:200] and "uri /authz/schema" in gate[:200]


def test_pgadmin_still_asks_the_admin_gate():
    block = caddy_block("handle /inspect/pgadmin*")
    assert "import protect" in block and "import admin_only" in block
