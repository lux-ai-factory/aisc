"""The Targets and endpoints page (homepage/connections.html) and its Manage entry. Static checks of
the page source, like test_llm_keys.py does for "Models and API keys"."""
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


# the Manage entry

def test_h1_the_manage_menu_links_the_page_for_owners_and_admins():
    # an owner manages the project's allowed internal hosts there, so the link shows for owners too;
    # managing the connections themselves is for platform admins
    html = read(PROJECT_PAGE)
    manage = re.search(r'<details[^>]*id="manage".*?</details>', html, re.S).group(0)
    link = re.search(r'<a\b[^>]*id="connections-settings"[^>]*>(.*?)</a>', manage, re.S)
    assert link and link.group(1).strip() == "Targets and endpoints"
    tag = re.search(r'<a\b[^>]*id="connections-settings"[^>]*>', manage).group(0)
    assert "owner-only" in tag and "hidden" in tag, tag
    script = script_of(html)
    gate = re.search(r"if \(a\.admin \|\| a\.role === 'owner'\)", script)
    wiring = re.search(r"getElementById\('connections-settings'\)\.href\s*=\s*'/connections\.html\?project='\s*\+\s*"
                       r"encodeURIComponent\(slug\)", script)
    assert gate and wiring and wiring.start() > gate.start(), "the href is not set inside the owner block"
    assert script.find("if (!a.admin) return;") > wiring.start(), "the link must not wait for the admin-only part"


# what the page does

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
    # there is no engine link: evaluations pick the target
    for needle in ("'PUT'", "'DELETE'", "/test'"):
        assert needle in script, needle
    for field in ("label", "kind", "base_url", "method", "path", "headers", "secret_header", "body_template",
                  "response_path", "refusal", "model", "timeout_s"):
        assert field in script, field
    assert "'openai'" in script and "'rest'" in script


def test_h2_connections_are_no_engine_components_any_more_so_the_page_offers_no_engine_link():
    # evaluations pick the target, never a connection
    html = read(PAGE)
    assert "engine_linked" not in script_of(html)
    assert "Link to the engine" not in html and "not linked to the engine" not in html


def test_h2_it_shows_an_answer_a_refusal_or_the_error_of_a_test():
    script = script_of(read(PAGE))
    assert ".answer" in script and ".refused" in script and ".refusal_reason" in script and ".error" in script


def test_h2_json_fields_are_parsed_on_the_page_and_a_bad_one_is_said_before_sending():
    script = script_of(read(PAGE))
    assert "JSON.parse" in script and "is not valid JSON" in script


# the key stays write-only; the page is CSP- and injection-safe

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


# the a2a and oip kinds

def test_h4_the_kind_menu_offers_a2a_and_oip():
    html = read(PAGE)
    kinds = re.search(r'<select id="f-kind">(.*?)</select>', html, re.S).group(1)
    assert set(re.findall(r'value="([a-z0-9]+)"', kinds)) == {"rest", "openai", "a2a", "oip"}


def test_h4_an_a2a_connection_sends_its_path_and_protocol_version_and_oip_its_model():
    html = read(PAGE)
    script = script_of(html)
    assert re.search(r'<select id="f-version">.*value="1\.0".*value="0\.3".*</select>', html, re.S)
    assert "protocol_version" in script and "'a2a'" in script and "'oip'" in script
    assert re.search(r"kind === 'openai' \|\| kind === 'oip'", script), "oip sends the model like openai"


def test_h4_the_list_says_what_an_a2a_or_oip_connection_is():
    script = script_of(read(PAGE))
    assert "A2A agent" in script and "Open Inference Protocol" in script


# the layout: hidden rows really hide; the key row reads as one control

def style_of(html):
    return "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", html, re.S | re.I))


def test_h5_a_hidden_row_is_hidden_even_when_its_class_sets_display():
    # .fields sets display:flex, which beats the browser's [hidden] rule: without the override a hidden
    # kind's row stays in the two-column grid and shifts every later label and field by one cell
    css = style_of(read(PAGE))
    assert re.search(r"form#editor \[hidden\]\s*\{\s*display:\s*none\s*!important", css)


def test_h5_the_key_row_is_the_field_and_its_remove_box_side_by_side():
    html = read(PAGE)
    css = style_of(html)
    row = re.search(r'<label for="f-secret">Key</label>\s*<div class="([^"]*)">(.*?)</div>', html, re.S)
    assert row and "fields" in row.group(1).split()
    assert re.search(r'<label class="check">\s*<input id="f-secret-remove" type="checkbox"', row.group(2))
    assert re.search(r'input\[type="?checkbox"?\]\s*\{[^}]*min-width:\s*0', css)
    check = re.search(r"form#editor label\.check\s*\{([^}]*)\}", css)
    assert check and "text-transform:none" in check.group(1).replace(" ", "")


# the allowed internal hosts

def test_h6_the_page_has_an_allowlist_section_outside_the_admins_part():
    html = markup_of(read(PAGE))
    section = re.search(r'<section id="allowlist" hidden>.*?</section>', html, re.S)
    assert section, "no allowlist section"
    settings = re.search(r'<div id="settings" hidden>.*?</div>\s*(?=<section id="allowlist")', html, re.S)
    assert settings, "the allowlist section must sit outside the admins' part, so owners see it"
    assert "Allowed internal hosts" in section.group(0)
    for needed in ('id="f-allow-host"', 'id="f-allow-note"', 'id="allow-add"', 'id="allow-rows"', 'id="allow-msg"'):
        assert needed in section.group(0), needed


def test_h6_an_owner_gets_the_allowlist_and_an_admin_gets_everything():
    script = script_of(read(PAGE))
    assert re.search(r"a\.admin\s*\|\|\s*a\.role === 'owner'", script)
    assert "show('allowlist')" in script and "show('settings')" in script
    assert script.index("show('settings')") > script.index("if (a.admin)")


def test_h6_it_lists_adds_and_removes_through_the_platform():
    script = script_of(read(PAGE))
    assert "'/api/projects/' + enc(slug) + '/allowed-hosts'" in script
    assert re.search(r"allowBase\(\) \+ '/' \+ enc\(host\)", script), "the entry must be URL-encoded"
    assert "'PUT'" in script and "'DELETE'" in script


def test_h6_the_deployments_entries_are_shown_read_only_and_denials_are_said():
    html = read(PAGE)
    script = script_of(html)
    assert ".floor" in script and "set by the deployment" in html
    assert ".denied" in script
    assert "never" in html.lower() and "loopback" in html


# targets and their endpoints

def test_h8_the_page_is_named_targets_and_endpoints():
    html = read(PAGE)
    assert "<title>Targets and endpoints" in html
    assert re.search(r'<section id="targets" hidden>.*?<h2>Targets</h2>', markup_of(html), re.S)


def test_h8_it_lists_the_targets_and_refreshes_them_from_the_card():
    html = read(PAGE)
    script = script_of(html)
    assert "'/api/projects/' + enc(slug) + '/targets'" in script
    assert "'/targets/sync'" in script and "Refresh from the card" in html
    for field in (".status", ".first_card_number", ".last_card_number", ".endpoint", ".component_kind", ".reason"):
        assert field in script, field
    assert "not in card v" in script and "no endpoint" in script


def test_h8_the_targets_are_shown_to_owners_and_admins_alike():
    script = script_of(read(PAGE))
    gate = script.index("if (!a || !(a.admin || a.role === 'owner'))")
    assert script.index("show('targets')") > gate
    assert script.index("show('targets')") < script.index("if (a.admin) {")


def test_h8_a_new_connection_names_its_target_and_a_taken_one_is_not_offered():
    html = read(PAGE)
    script = script_of(html)
    assert re.search(r'<select id="f-target"[^>]*required', html)
    assert "body.target" in script and ".disabled = true" in script
    assert "Endpoint of" in html


def test_h8_each_connection_says_what_it_is_the_endpoint_of():
    script = script_of(read(PAGE))
    assert "c.target" in script and "no target" in script


# importing an endpoint from a file (the workshop's endpoint files)

def test_an_endpoint_file_is_imported_into_the_editor_not_saved():
    html = read(PAGE)
    markup, script = markup_of(html), script_of(html)
    assert re.search(r'<button[^>]*id="import"[^>]*>Import from file</button>', markup)
    assert re.search(r'<input[^>]*id="import-file"[^>]*type="file"[^>]*accept="[^"]*json', markup) or \
        re.search(r'<input[^>]*type="file"[^>]*id="import-file"[^>]*accept="[^"]*json', markup)
    imp = re.search(r"function importFile\(.*?\n  \}\n", script, re.S)
    assert imp, "no importFile()"
    body = imp.group(0)
    assert "openEditor(null)" in body and "JSON.parse" in body
    assert "write(" not in body and "fetch(" not in body and "api(" not in body, "an import must not save by itself"
    for field in ("f-name", "f-label", "f-kind", "f-base", "f-method", "f-path", "f-body", "f-answer", "f-refusal",
                  "f-headers", "f-secret-header", "f-timeout"):
        assert field in body, field


def test_the_import_picks_the_target_by_its_label_since_keys_differ_per_project():
    body = re.search(r"function importFile\(.*?\n  \}\n", script_of(read(PAGE)), re.S).group(0)
    assert "target_label" in body


def test_a_json_test_input_is_sent_as_an_object_for_a_structured_system():
    probe = re.search(r"function probeIt\(.*?\n  \}\n", script_of(read(PAGE)), re.S).group(0)
    assert "JSON.parse" in probe


def test_a_ping_that_only_shows_the_system_is_reached_says_so():
    probe = re.search(r"function probeIt\(.*?\n  \}\n", script_of(read(PAGE)), re.S).group(0)
    assert "d.reachable_only" in probe and "d.detail" in probe
