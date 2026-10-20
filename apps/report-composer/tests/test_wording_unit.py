"""The words the composer's pages use: step 4's Report, report layouts and looks, sections, checklists.
Static checks of the templates and the script, no database."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "report_composer"


def source(name: str) -> str:
    return (ROOT / name).read_text()


def test_the_layouts_page_is_step_4s_report_layouts():
    page = source("templates/layouts.html.j2")
    assert '<p class="rc-eyebrow">Step 4: Report</p>' in page and "Step 7" not in page
    assert "<h1>Report layouts of {{ project.name }}</h1>" in page and "Reports of {{" not in page
    assert "{% block title %}Report layouts: {{ project.name }}{% endblock %}" in page
    assert "<th>Look</th>" in page and "<th>Template</th>" not in page
    assert page.count("Platform look") == 2 and "Platform default" not in page
    assert ">Create layout</a>" in page and "New layout" not in page and "make your own" not in page


def test_the_editor_speaks_of_sections_looks_and_the_table_of_contents():
    page = source("templates/editor.html.j2")
    assert "<h2>Add a section</h2>" in page and "Add a module" not in page and "module" not in page
    assert "<h2>Sections, in order</h2>" in page and "Blocks, in order" not in page
    assert 'class="type"' not in page                                   # no grey type id tags
    assert "<label>Look <select" in page and ">Platform look</option>" in page
    assert "> Table of contents</label>" in page and "> Number the sections</label>" in page
    assert "> Index</label>" not in page and "> Numbering</label>" not in page
    assert "Generate and download &#9662;" in page and "Download report" not in page
    assert "&larr; Report layouts</a>" in page and "All layouts of" not in page
    assert "tests and checklists give evidence" in page and "tests and controls" not in page
    assert "Make a template" not in page and "make a template" not in page
    assert "Unknown section: {{ b.block_type }}" in page


def test_the_looks_page_speaks_of_looks():
    page = source("templates/templates.html.j2")
    assert '<p class="rc-eyebrow">Step 4: Report</p>' in page and "Step 7" not in page
    assert "<h1>Report looks of {{ project.name }}</h1>" in page
    for old in ("Templates of", "New template", "Create template", "Editing template", "Delete template",
                "No templates yet", "the template {{"):
        assert old not in page, old


def test_the_generate_page_says_checklist_answers_and_sections():
    page = source("templates/generate.html.j2")
    assert "control answers" not in page and "checklist answers" in page
    assert "Changes since section" in page and "module" not in page


def test_the_script_says_look():
    assert '"This file is not a look file."' in source("static/composer.js")
    assert '"This file is not a template."' not in source("static/composer.js")


def test_the_messages_name_looks_and_sections():
    records, api, looks = source("records.py"), source("api.py"), source("templates.py")
    layouts, presets = source("layouts.py"), source("presets.py")
    assert 'NO_TEMPLATE = "No such look."' in records
    assert '"The look is not one of this project\'s."' in api and '"A look of this project already has this name."' in api
    assert '"This look has no logo."' in api and '"A look is an object."' in looks
    assert 'f"a layout holds at most {MAX_BLOCKS} sections"' in layouts
    assert 'f"A layout holds at most {layouts.MAX_BLOCKS} sections."' in api
    assert 'f"the section type {b.get(\'block_type\')!r} is not available"' in layouts
    assert '"This file uses sections this installation does not offer: "' in presets
    assert 'f"A preset holds at most {MAX_BLOCKS} sections."' in presets
