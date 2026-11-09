"""The documentation PDF: which Markdown goes in, in what order, and how its links and pictures survive the move
from many files on GitHub to one document."""
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import docs_pdf  # noqa: E402

REPO = "https://github.com/lux-ai-factory/aisc"


def names(paths):
    return [str(p.relative_to(ROOT)) for p in paths]


def test_every_page_of_the_documentation_is_in_once():
    found = names(docs_pdf.documents(ROOT))
    on_disk = ["README.md", *names(sorted((ROOT / "docs").rglob("*.md")))]
    assert sorted(found) == sorted(on_disk)
    assert len(found) == len(set(found))


def test_the_overview_comes_first_then_the_appendices_by_number_then_the_runbooks():
    found = names(docs_pdf.documents(ROOT))
    assert found[:3] == ["README.md", "docs/architecture.md", "docs/guide.md"]
    appendices = [docs_pdf.title(ROOT / f) for f in found if f.startswith("docs/appendices/")]
    assert appendices == sorted(appendices, key=lambda t: int(t.split()[1].rstrip(":")))
    assert all(f.startswith("docs/runbooks/") for f in found[-2:])


def test_a_heading_becomes_the_anchor_github_gives_it():
    assert docs_pdf.anchor("Appendix 9: Security") == "appendix-9-security"
    assert docs_pdf.anchor("AISC in detail") == "aisc-in-detail"
    assert docs_pdf.anchor("Runbook: the ledger after an immudb restore") == "runbook-the-ledger-after-an-immudb-restore"


def prepared(text, at="docs/guide.md"):
    included = docs_pdf.documents(ROOT)
    return docs_pdf.prepare(text, ROOT / at, ROOT, included, "pilot")


def test_a_link_to_another_page_of_the_pdf_jumps_to_its_title():
    assert prepared("See [security](appendices/security.md).") == "See [security](#appendix-9-security)."


def test_a_link_to_a_section_of_another_page_jumps_to_that_section():
    assert prepared("[logs](manage.md#logs)", at="docs/appendices/flows.md") == "[logs](#logs)"


def test_a_link_to_a_file_outside_the_pdf_goes_to_github():
    assert prepared("[composer](../apps/report-composer/README.md)") == (
        f"[composer]({REPO}/blob/pilot/apps/report-composer/README.md)")
    assert prepared("[plugin manager](../shared/plugin-manager)") == (
        f"[plugin manager]({REPO}/tree/pilot/shared/plugin-manager)")


def test_a_link_that_leaves_the_repository_stays_as_written():
    """A relative link to a sibling checkout has no page on GitHub to go to; it must not stop the build."""
    assert prepared("[sib](../../other-repo/README.md)") == "[sib](../../other-repo/README.md)"


def test_a_file_name_with_spaces_and_brackets_still_goes_to_github():
    text = "([individuals](<AISC ICLA (Individuals).txt>), [entities](<AISC CCLA (Entities).txt>))"
    assert prepared(text, at="README.md") == (
        f"([individuals]({REPO}/blob/pilot/AISC%20ICLA%20%28Individuals%29.txt), "
        f"[entities]({REPO}/blob/pilot/AISC%20CCLA%20%28Entities%29.txt))")


def test_web_links_and_links_within_the_page_stay_as_they_are():
    text = "[arXiv](https://arxiv.org/abs/2509.25256) and [below](#the-ledger)"
    assert prepared(text) == text


def test_a_picture_is_found_wherever_the_build_runs():
    assert prepared("![A project](docs/images/project-page.png)", at="README.md") == (
        f"![A project]({ROOT}/docs/images/project-page.png)")


def test_every_jump_within_the_pdf_lands_on_a_heading():
    pages = docs_pdf.documents(ROOT)
    body = "\n\n".join(docs_pdf.prepare(p.read_text(), p, ROOT, pages, "pilot") for p in pages)
    headings = docs_pdf.heading_anchors(body)
    jumps = {m.group(3)[1:] for m in docs_pdf.LINK.finditer(body) if m.group(3).startswith("#")}
    assert jumps and sorted(jumps - headings) == []
    assert docs_pdf.ambiguous_jumps(pages, ROOT) == []


def test_a_link_to_a_section_whose_heading_another_page_has_too_is_named(tmp_path):
    """In one document a fragment no longer says which page it is on: two pages with a heading of the same name
    give the same jump, and pandoc names the later heading -1, so the link could land on the wrong page."""
    (tmp_path / "manage.md").write_text("# Manage\n\n## Logs\n")
    (tmp_path / "security.md").write_text("# Security\n\n## Logs\n")
    (tmp_path / "flows.md").write_text("# Flows\n\n[x](manage.md#logs) [y](security.md#logs) [z](#flows)\n"
                                       "```\n[c](manage.md#logs)\n```\n")
    pages = [tmp_path / n for n in ("flows.md", "manage.md", "security.md")]
    assert docs_pdf.ambiguous_jumps(pages, tmp_path) == ["flows.md: manage.md#logs", "flows.md: security.md#logs"]


def test_badges_are_left_out():
    text = "# AISC\n\n[![CI](https://x/badge.svg)](https://x)\n[![License](https://y.svg)](LICENSE.md)\n\nText\n"
    assert prepared(text, at="README.md") == "# AISC\n\n\nText\n"


def test_code_blocks_are_left_alone():
    text = "```bash\necho '[x](appendices/security.md)'\n```"
    assert prepared(text) == text


def test_the_template_gets_the_styles_pandoc_writes_code_lists_and_tables_with(tmp_path):
    docx = __import__("pytest").importorskip("docx")
    template = tmp_path / "template.docx"
    docx.Document().save(str(template))
    styles = docx.Document(str(docs_pdf.reference_docx(template, tmp_path / "build"))).styles
    code = styles["Source Code"]
    assert code.paragraph_format.alignment == docx.enum.text.WD_ALIGN_PARAGRAPH.LEFT
    assert styles["Verbatim Char"].font.name == docs_pdf.CODE_FONT
    assert styles["Compact"].paragraph_format.space_after == docx.shared.Pt(2)
    assert styles["Compact"].paragraph_format.alignment == docx.enum.text.WD_ALIGN_PARAGRAPH.LEFT
    assert styles["Table"].type == docx.enum.style.WD_STYLE_TYPE.TABLE
    assert styles["Heading 1"].paragraph_format.page_break_before


def test_tables_fill_the_text_width_with_wider_columns_for_longer_text(tmp_path):
    docx = __import__("pytest").importorskip("docx")
    from docx.oxml.ns import qn
    word = tmp_path / "t.docx"
    made = docx.Document()
    table = made.add_table(rows=2, cols=2)
    for row in table.rows:
        row.cells[0].text = "caddy"
        row.cells[1].text = "The gateway and the only published entry: the launcher on 8100, the step applications"
    made.save(str(word))
    docs_pdf.full_width_tables(word)
    done = docx.Document(str(word))
    section = done.sections[0]
    text_width = (section.page_width - section.left_margin - section.right_margin) // 635
    grid = [int(c.get(qn("w:w"))) for c in done.tables[0]._tbl.tblGrid.findall(qn("w:gridCol"))]
    assert abs(sum(grid) - text_width) <= len(grid)
    assert grid[1] > 2 * grid[0]
    cells = [int(c.find(qn("w:tcPr")).find(qn("w:tcW")).get(qn("w:w"))) for c in done.tables[0]._tbl.tr_lst[0].tc_lst]
    assert cells == grid


def test_a_column_is_never_narrower_than_its_longest_word():
    rows = [["Database", "Schemas and what they hold"],
            ["keycloak", "accounts, passwords, sessions, and a good deal more text than the first column"]]
    first, second = docs_pdf.column_widths(rows, 10000)
    assert first >= 10000 * len("Database") / (len("Database") + 60)
    assert first + second == 10000


def test_a_short_column_next_to_long_ones_still_holds_its_longest_word():
    long = "a sentence of text that goes on for well over sixty characters in this one cell"
    rows = [["Step", "Question", "What you do", "What it produces", "Who uses"],
            ["2. Set control objectives", long, long, long, long]]
    widths = docs_pdf.column_widths(rows, 9922)
    assert widths[0] >= len("objectives") * docs_pdf.CHARACTER_WIDTH
    assert sum(widths) == 9922


def test_no_template_is_kept_in_the_repository():
    assert list(ROOT.glob("docs/**/*.docx")) == []


def test_a_diagram_becomes_a_picture_named_after_its_source():
    text = "Before\n\n```mermaid\nflowchart LR\n  A --> B\n```\n\nAfter"
    found = docs_pdf.diagrams(text)
    assert found == ["flowchart LR\n  A --> B\n"]
    picture = docs_pdf.diagram_file(found[0], ROOT / "build")
    assert prepared(text) == f"Before\n\n![]({picture})\n\nAfter"
    assert picture.parent == ROOT / "build" / "diagrams" and picture.suffix == ".png"
