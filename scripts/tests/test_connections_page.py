"""The Connections page and its Manage entry (connections plan 2026-09-29, H1 to H3). Static checks
of the page source, like test_llm_keys.py does for "Models and API keys"."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/connections.html"
PROJECT_PAGE = ROOT / "homepage/project.html"


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def markup_of(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


# ── H1 the Manage entry ─────────────────────────────────────────────────────

def test_h1_the_manage_menu_links_the_page_for_admins_only():
    html = read(PROJECT_PAGE)
    manage = re.search(r'<details[^>]*id="manage".*?</details>', html, re.S).group(0)
    link = re.search(r'<a\b[^>]*id="connections-settings"[^>]*>(.*?)</a>', manage, re.S)
    assert link and link.group(1).strip() == "Connections"
    tag = re.search(r'<a\b[^>]*id="connections-settings"[^>]*>', manage).group(0)
    assert "admin-only" in tag and "hidden" in tag, tag
    script = script_of(html)
    gate = script.find("a.admin")
    wiring = re.search(r"getElementById\('connections-settings'\)\.href\s*=\s*'/connections\.html\?project='\s*\+\s*"
                       r"encodeURIComponent\(slug\)", script)
    assert wiring and gate != -1 and wiring.start() > gate, "the href is not set inside the admin-only block"


# ── H2 what the page does ───────────────────────────────────────────────────

def test_h2_the_page_has_the_launchers_look_and_one_inline_script():
    html, reference = read(PAGE), read(PROJECT_PAGE)
    for var in re.findall(r"(--[a-z0-9-]+)\s*:", re.search(r":root\s*\{(.*?)\}", reference, re.S).group(1)):
        assert re.search(re.escape(var) + r"\s*:", html), var
    assert 'class="session"' in html and 'id="who"' in html
    scripts = re.findall(r"<script\b([^>]*)>", html, re.I)
    assert len(scripts) == 1 and "src" not in scripts[0].lower()


def test_h2_non_admins_are_told_and_nothing_is_asked_before_the_role_is_known():
    html = read(PAGE)
    script = script_of(html)
    assert "Only a platform admin manages connections." in html
    first = script.find("/connections")
    assert first == -1 or script.find("/api/authz/projects/") < first


def test_h2_it_lists_saves_tests_links_and_deletes_through_the_platform():
    script = script_of(read(PAGE))
    assert "'/api/projects/' + enc(slug) + '/connections'" in script
    for needle in ("'PUT'", "'DELETE'", "/test'", "/link'"):
        assert needle in script, needle
    for field in ("label", "kind", "base_url", "method", "path", "headers", "secret_header", "body_template",
                  "response_path", "refusal", "model", "timeout_s"):
        assert field in script, field
    assert "'openai'" in script and "'rest'" in script


def test_h2_it_shows_the_engine_link_and_offers_the_retry():
    html = read(PAGE)
    assert "engine_linked" in script_of(html)
    assert "Link to the engine" in html and "not linked to the engine" in html


def test_h2_it_shows_an_answer_a_refusal_or_the_error_of_a_test():
    script = script_of(read(PAGE))
    assert ".answer" in script and ".refused" in script and ".refusal_reason" in script and ".error" in script


def test_h2_json_fields_are_parsed_on_the_page_and_a_bad_one_is_said_before_sending():
    script = script_of(read(PAGE))
    assert "JSON.parse" in script and "is not valid JSON" in script


# ── H3 the key stays write-only; the page is CSP- and injection-safe ────────

def test_h3_the_key_field_is_a_write_only_password_input():
    html = read(PAGE)
    assert re.search(r"""\.type\s*=\s*["']password["']""", html) and "new-password" in html
    for tag in re.findall(r"<input\b[^>]*password[^>]*>", markup_of(html), re.I):
        assert not re.search(r"\bvalue\s*=", tag), tag
    assert "key stored" in html and "no key" in html


def test_h3_the_page_never_fills_a_key_field_nor_reads_a_key_back():
    script = script_of(read(PAGE))
    for target, value in re.findall(r"([\w.\[\]'\"]*[sS]ecret[\w.\[\]'\"]*)\.value\s*=\s*([^;\n]+)", script):
        assert value.strip() in {"''", '""'}, f"{target}.value = {value}"
    assert not re.search(r"\b[a-z]\.secret\b(?!_header)", script), "the page reads a key from a response"


def test_h3_csp_and_injection_safe():
    html = read(PAGE)
    script = script_of(html)
    assert not re.search(r"<[a-z][^>]*\son[a-z]+\s*=", markup_of(html), re.I)
    assert "addEventListener" in script and not re.search(r"\.on[a-z]+\s*=", script)
    assert "innerHTML" not in html and "outerHTML" not in html and "insertAdjacentHTML" not in html
    assert "document.write" not in script and "eval(" not in script
    calls = re.findall(r"fetch\(\s*([^,)]+)", script)
    assert calls and all(not re.search(r"https?:", a) for a in calls)
    assert script.count("credentials: 'same-origin'") >= len(calls)
