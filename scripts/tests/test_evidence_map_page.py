"""The Evidence map page: step 2's objectives against the installed tests and checklists, with each link's note,
the map's review and each objective's coverage. The platform decides everything (what may be linked, coverage,
who may review); the page shows it and sends the links. Static checks of the page source, like
test_evidence_page.py."""
import re

from conftest import ROOT

PAGE = ROOT / "homepage/evidence-map.html"
EVIDENCE = ROOT / "homepage/evidence.html"


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def markup_of(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


def test_it_has_step_4s_look_and_its_own_title():
    html, reference = read(PAGE), read(EVIDENCE)
    for var in re.findall(r"(--[a-z0-9-]+)\s*:", re.search(r":root\s*\{(.*?)\}", reference, re.S).group(1)):
        assert re.search(re.escape(var) + r"\s*:", html), var
    assert 'class="session"' in html and 'id="who"' in html
    assert re.search(r"<title>Evidence map\b", html)
    assert "[hidden]{display:none !important}" in html


def test_it_reads_and_writes_the_platforms_evidence_routes():
    script = script_of(read(PAGE))
    assert "'/api/projects/' + enc(slug) + '/evidence'" in script
    assert "'/evidence/links'" in script and "method: 'PUT'" in script
    assert "'/evidence/review'" in script and "method: 'POST'" in script
    assert "params.get('version')" in script


def test_the_grid_has_a_row_per_objective_and_a_column_per_test_and_checklist():
    script = script_of(read(PAGE))
    assert "data.objectives" in script and "data.tests" in script and "data.controls" in script
    assert "o.risks" in script and "o.priority" in script and "o.expects" in script


def test_a_cell_is_a_link_a_possible_link_or_out_of_the_objectives_dimension():
    script = script_of(read(PAGE))
    assert "'\\u2713'" in script and "'\\u2610'" in script and "'\\u00b7'" in script
    assert "item.dimensions" in script and "o.dimension" in script


def test_linked_and_evidence_columns_come_from_the_platform():
    script = script_of(read(PAGE))
    assert "o.linked" in script and "o.evidence" in script
    for status in ("not covered", "no evidence", "evidence", "attention"):
        assert f"'{status}'" in script, status
    assert "'Evidence (v' + data.version.number + ')'" in script


def test_gaps_only_and_priority_only_narrow_the_rows():
    html = read(PAGE)
    assert 'id="gaps-only"' in html and 'id="priority-only"' in html
    assert "Gaps only" in html and "Priority only" in html


def test_a_link_opens_with_its_note_who_made_it_and_unlink():
    script = script_of(read(PAGE))
    assert "link.note" in script and "link.created_by" in script
    assert "'Unlink'" in script and "'Save note'" in script
    assert "maxLength = 1000" in script


def test_mark_reviewed_only_when_the_platform_says_the_caller_may():
    script = script_of(read(PAGE))
    assert "data.can_review" in script and "'Mark reviewed'" in script
    assert "data.review" in script and "reviewed_by_name" in script


def test_a_new_version_offers_to_copy_the_earlier_map():
    script = script_of(read(PAGE))
    assert "data.carried_from" in script and "'Copy the v' + data.carried_from + ' map'" in script


def test_an_older_version_or_a_viewer_reads_only():
    script = script_of(read(PAGE))
    assert "data.can_edit" in script


def test_the_breadcrumb_leads_back_to_collect_evidence():
    script = script_of(read(PAGE))
    assert re.search(r"'/evidence\.html\?project=' \+ enc\(slug\)", script)


def test_the_page_builds_its_nodes_without_markup_strings_or_inline_handlers():
    html = read(PAGE)
    assert "innerHTML" not in script_of(html) and "insertAdjacentHTML" not in script_of(html)
    assert not re.search(r"\son[a-z]+\s*=", markup_of(html))


def test_no_em_dash_in_the_page():
    assert "—" not in read(PAGE) and "&mdash;" not in read(PAGE)


# ── Collect evidence leads to it ────────────────────────────────────────────

def test_collect_evidence_has_the_evidence_map_button_and_its_coverage_line():
    html = read(EVIDENCE)
    script = script_of(html)
    assert 'id="evidence-map"' in markup_of(html) and ">Evidence map<" in markup_of(html)
    assert "'/evidence-map.html?project=' + enc(slug)" in script
    assert "data.coverage" in script
    assert "' objectives linked \\u00b7 '" in script and "' gaps'" in script
