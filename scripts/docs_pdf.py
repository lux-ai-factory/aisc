"""Build one PDF of the documentation from the Markdown it is written in.

    uv run --no-project --with pypandoc_binary --with python-docx scripts/docs_pdf.py <template.docx>

writes build/AISC-documentation.docx and build/AISC-documentation.pdf. The Markdown in README.md and docs/
stays the only source: the PDF is a snapshot of it, made again whenever one is needed, never edited.

On the way into one document, links between pages become jumps within it, links to other files of the repo
point at them on GitHub, Mermaid diagrams become pictures (the Mermaid command line through npx, with the
Chrome it finds), and badges are left out. The look comes from the Word template given, such as the Luxembourg
AI Factory's Request for Comments: it is not kept in the repository (a binary, and others' logos), only its
styles are used, and each page of the documentation starts a new page of the PDF. LibreOffice turns the Word
file into the PDF, after filling in its table of contents (scripts/lib/docs-pdf-contents.xba).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

REPO = "https://github.com/lux-ai-factory/aisc"
NAME = "AISC-documentation"
FENCE = re.compile(r"^(```|~~~)")
BADGE = re.compile(r"^\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)\s*$")
LINK = re.compile(r"(!?)\[([^\]]*)\]\((<[^>]+>|[^)\s]+)\)")
MERMAID = re.compile(r"^```mermaid\n(.*?)^```\n?", re.S | re.M)
MERMAID_CLI = "@mermaid-js/mermaid-cli@11.4.2"
CODE_FONT = "DejaVu Sans Mono"
CHARACTER_WIDTH = 110  # twips: an average character of the body text, bold included, with a cell's margins


def title(path: Path) -> str:
    """A page's title: its first `# ` heading outside code."""
    fenced = False
    for line in path.read_text().splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and line.startswith("# "):
            return line[2:].strip()
    raise ValueError(f"{path} has no title")


def documents(root: Path) -> list[Path]:
    """The pages in reading order: the overview, how it works, the guide, the appendices by their number,
    the runbooks; any other page of docs/ before the runbooks."""
    docs = root / "docs"
    first = [root / "README.md", docs / "architecture.md", docs / "guide.md"]
    appendices = sorted((docs / "appendices").glob("*.md"), key=lambda p: int(title(p).split()[1].rstrip(":")))
    runbooks = sorted((docs / "runbooks").glob("*.md"))
    rest = [p for p in sorted(docs.rglob("*.md")) if p not in {*first, *appendices, *runbooks}]
    return [*first, *appendices, *rest, *runbooks]


def anchor(heading: str) -> str:
    """The id GitHub gives a heading, which pandoc's gfm reader gives it too."""
    kept = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return kept.replace(" ", "-")


def heading_anchors(text: str) -> set[str]:
    """The ids of every heading outside code; a repeated one gets -1, -2, as GitHub and pandoc do."""
    times: dict[str, int] = {}
    found: set[str] = set()
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced and re.match(r"^#{1,6} ", line):
            base = anchor(line.lstrip("#"))
            found.add(f"{base}-{times[base]}" if base in times else base)
            times[base] = times.get(base, 0) + 1
    return found


def diagrams(text: str) -> list[str]:
    return MERMAID.findall(text)


def diagram_file(source: str, build: Path) -> Path:
    return build / "diagrams" / f"{hashlib.sha256(source.encode()).hexdigest()[:16]}.png"


def link_target(target: str, page: Path, root: Path, included: list[Path], branch: str) -> str:
    if re.match(r"^[a-z]+:", target) or target.startswith("#"):
        return target
    path, _, fragment = target.strip("<>").partition("#")
    found = (page.parent / path).resolve()
    if found in included:
        return f"#{fragment or anchor(title(found))}"
    if not found.is_relative_to(root.resolve()):
        return target  # outside the repository: no page on GitHub to send it to
    where = found.relative_to(root.resolve())
    kind = "tree" if found.is_dir() else "blob"
    return f"{REPO}/{kind}/{branch}/{quote(str(where))}" + (f"#{fragment}" if fragment else "")


def ambiguous_jumps(pages: list[Path], root: Path) -> list[str]:
    """The links to a section of another page whose heading more than one page has: in the single document the
    fragment alone no longer says which page, pandoc names the later heading -1, and the jump lands on the first.
    Each as "<page>: <link>", the page relative to root."""
    pages = [p.resolve() for p in pages]
    texts = {p: p.read_text() for p in pages}
    holders: dict[str, int] = {}
    for text in texts.values():
        for found in heading_anchors(text):
            holders[found] = holders.get(found, 0) + 1
    wrong = []
    for page, text in texts.items():
        fenced = False
        for line in text.splitlines():
            if FENCE.match(line):
                fenced = not fenced
                continue
            if fenced:
                continue
            for m in LINK.finditer(line):
                target = m.group(3).strip("<>")
                if m.group(1) or re.match(r"^[a-z]+:", target) or target.startswith("#") or "#" not in target:
                    continue
                path, _, fragment = target.partition("#")
                if (page.parent / path).resolve() in texts and holders.get(fragment, 0) > 1:
                    wrong.append(f"{page.relative_to(root.resolve())}: {target}")
    return wrong


def prepare(text: str, page: Path, root: Path, included: list[Path], branch: str) -> str:
    """One page's Markdown, made to work inside the single document."""
    build = root / "build"
    text = MERMAID.sub(lambda m: f"![]({diagram_file(m.group(1), build)})\n", text)
    included = [p.resolve() for p in included]

    def relink(m: re.Match) -> str:
        bang, label, target = m.groups()
        if bang:
            if re.match(r"^[a-z]+:", target) or target.startswith("/"):
                return m.group(0)
            return f"![{label}]({(page.parent / target).resolve()})"
        return f"[{label}]({link_target(target, page, root, included, branch)})"

    out, fenced = [], False
    for line in text.split("\n"):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            if BADGE.match(line):
                continue
            line = LINK.sub(relink, line)
        out.append(line)
    return "\n".join(out)


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def render_diagrams(sources: list[str], build: Path) -> None:
    """Each Mermaid diagram as a PNG, kept between builds: a diagram that did not change is not drawn again."""
    missing = [s for s in sources if not diagram_file(s, build).exists()]
    if not missing:
        return
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chrome:
        sys.exit("Drawing the diagrams needs Chrome or Chromium.")
    (build / "diagrams").mkdir(parents=True, exist_ok=True)
    browser = build / "diagrams" / "browser.json"
    browser.write_text(json.dumps({"executablePath": chrome, "args": ["--no-sandbox"]}))
    for source in missing:
        target = diagram_file(source, build)
        given = target.with_suffix(".mmd")
        given.write_text(source)
        subprocess.run(["npx", "-y", "-p", MERMAID_CLI, "mmdc", "-i", str(given), "-o", str(target), "-s", "3",
                        "-b", "white", "-p", str(browser)], check=True, capture_output=True, timeout=300)
        given.unlink()


def style(styles, name: str, kind):
    try:
        return styles[name]
    except KeyError:
        return styles.add_style(name, kind)


def table_borders(table_style, color: str = "B4C6E7") -> None:
    """Thin lines around and between the cells; python-docx has no call for a table style's borders."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    properties = table_style.element.find(qn("w:tblPr"))
    if properties is None:
        properties = OxmlElement("w:tblPr")
        table_style.element.append(properties)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        line = OxmlElement(f"w:{edge}")
        line.set(qn("w:val"), "single")
        line.set(qn("w:sz"), "4")
        line.set(qn("w:color"), color)
        borders.append(line)
    properties.append(borders)


def reference_docx(given: Path, build: Path) -> Path:
    """The template, with every chapter on a new page and the styles pandoc writes code, short lists and
    tables with: the Request for Comments template has none of them, and justified body text in its font
    would run code lines together."""
    import docx
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    template = docx.Document(str(given))
    styles = template.styles
    styles["Heading 1"].paragraph_format.page_break_before = True

    verbatim = style(styles, "Verbatim Char", WD_STYLE_TYPE.CHARACTER)
    verbatim.font.name, verbatim.font.size = CODE_FONT, Pt(8.5)
    verbatim.font.color.rgb = RGBColor(0x1F, 0x2A, 0x44)
    code = style(styles, "Source Code", WD_STYLE_TYPE.PARAGRAPH)
    code.base_style = styles["Normal"]
    code.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
    code.paragraph_format.space_before, code.paragraph_format.space_after = Pt(4), Pt(8)
    code.paragraph_format.left_indent = Pt(10)
    code.font.name, code.font.size = CODE_FONT, Pt(8.5)

    for name in ("Compact", "First Paragraph", "Body Text"):
        paragraph = style(styles, name, WD_STYLE_TYPE.PARAGRAPH)
        paragraph.base_style = styles["Normal"]
    styles["Compact"].paragraph_format.space_before = Pt(0)
    styles["Compact"].paragraph_format.space_after = Pt(2)
    styles["Compact"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT

    table = style(styles, "Table", WD_STYLE_TYPE.TABLE)
    table_borders(table)

    build.mkdir(parents=True, exist_ok=True)
    target = build / "reference.docx"
    template.save(str(target))
    return target


def column_widths(rows: list[list[str]], text_width: int) -> list[int]:
    """Widths in twips that fill the text width. Each column first gets room for its longest word (a word, or
    a name in code, cannot break), up to a third of the width; the rest is shared after how much the column
    holds, its cells' average length between 6 and 60 characters, so a paragraph column does not take it all."""
    columns = list(zip(*rows))
    least = [min(max((len(w) for c in cells for w in c.split()), default=1) * CHARACTER_WIDTH, text_width // 3)
             for cells in columns]
    if sum(least) > text_width:
        least = [w * text_width // sum(least) for w in least]
    shares = [min(max(sum(len(c) for c in cells) / len(cells), 6), 60) for cells in columns]
    rest = text_width - sum(least)
    widths = [w + int(rest * s / sum(shares)) for w, s in zip(least, shares)]
    widths[-1] += text_width - sum(widths)
    return widths


def full_width_tables(word: Path) -> None:
    """Every table as wide as the text: pandoc gives short pipe tables equal columns over two thirds of it,
    which makes the long ones (the configuration settings) run over many pages of narrow columns."""
    import docx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    def setting(parent, tag: str):
        found = parent.find(qn(tag))
        if found is None:
            found = OxmlElement(tag)
            parent.append(found)
        return found

    document = docx.Document(str(word))
    section = document.sections[0]
    text_width = (section.page_width - section.left_margin - section.right_margin) // 635
    for table in document.tables:
        columns = len(table.columns)
        widths = column_widths([[c.text for c in row.cells[:columns]] for row in table.rows], text_width)
        width = setting(table._tbl.tblPr, "w:tblW")
        width.set(qn("w:type"), "dxa")
        width.set(qn("w:w"), str(text_width))
        table._tbl.tblPr.get_or_add_tblLayout().set(qn("w:type"), "fixed")
        for column, w in zip(table._tbl.tblGrid.findall(qn("w:gridCol")), widths):
            column.set(qn("w:w"), str(w))
        for row in table._tbl.tr_lst:
            for cell, w in zip(row.tc_lst, widths):
                cell_width = cell.get_or_add_tcPr().get_or_add_tcW()
                cell_width.set(qn("w:type"), "dxa")
                cell_width.set(qn("w:w"), str(w))
    document.save(str(word))


def to_pdf(word: Path, root: Path, build: Path) -> Path:
    """The PDF through LibreOffice, with the table of contents filled in first, in a throwaway profile."""
    profile = build / "libreoffice-profile"
    module = profile / "user" / "basic" / "Standard" / "Module1.xba"
    office = ["libreoffice", "--headless", f"-env:UserInstallation=file://{profile}"]
    if not module.parent.exists():
        subprocess.run([*office, "--terminate_after_init"], check=True, capture_output=True, timeout=180)
    module.write_text((root / "scripts/lib/docs-pdf-contents.xba").read_text())
    pdf = word.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    subprocess.run([*office, f'macro:///Standard.Module1.DocxToPdf("{word}")'], capture_output=True, timeout=600)
    if not pdf.exists():
        sys.exit("LibreOffice did not write the PDF (is it installed?)")
    return pdf


def build(root: Path, template: Path) -> Path:
    import pypandoc

    out = root / "build"
    out.mkdir(exist_ok=True)
    pages = documents(root)
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    ambiguous = ambiguous_jumps(pages, root)
    if ambiguous:
        sys.exit("These links name a section whose heading another page has too, so in the PDF they could land on "
                 "the wrong page; rename one of the headings:\n  " + "\n  ".join(ambiguous))
    texts = [p.read_text() for p in pages]
    render_diagrams([d for t in texts for d in diagrams(t)], out)
    body = "\n\n".join(prepare(t, p, root, pages, branch) for t, p in zip(texts, pages))

    commit = git(root, "log", "-1", "--format=%h, %cs")
    changed = " with local changes" if git(root, "status", "--porcelain", "--", "README.md", "docs") else ""
    word = out / f"{NAME}.docx"
    pypandoc.convert_text(body, "docx", format="gfm", outputfile=str(word), extra_args=[
        f"--reference-doc={reference_docx(template, out)}", "--toc", "--toc-depth=2",
        "--metadata=title:AI Assessment Sandbox Configurator",
        "--metadata=subtitle:Documentation",
        f"--metadata=date:Branch {branch} at {commit}{changed}",
        "--metadata=toc-title:Contents",
    ])
    full_width_tables(word)
    return to_pdf(word, root, out)


if __name__ == "__main__":
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        sys.exit("Give the Word template to take the look from: scripts/docs_pdf.py <template.docx>")
    print("wrote", build(Path(__file__).resolve().parent.parent, Path(sys.argv[1]).resolve()))
