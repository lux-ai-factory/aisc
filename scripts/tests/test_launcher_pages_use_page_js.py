"""Every launcher page calls the platform and reads its project through homepage/assets/page.js (aisc.call and
aisc.project), so a refusal, an outage and a malformed address are said the same way on every page. No page keeps
a fetch or a project parser of its own.

Read-only: the pages as text. page.js itself is held by test_launcher_page_js.py.
"""

import re

from conftest import ROOT

PAGES = sorted((ROOT / "homepage").glob("*.html"))
LOADS_PAGE_JS = re.compile(r'<script\s+src="/?assets/page\.js"')
OWN_PROJECT = re.compile(r"""\.get\(\s*['"]project['"]\s*\)""")


def test_every_page_loads_page_js():
    assert PAGES
    assert [p.name for p in PAGES if not LOADS_PAGE_JS.search(p.read_text())] == []


def test_no_page_calls_the_platform_on_its_own():
    assert sorted(p.name for p in PAGES if re.search(r"\bfetch\(", p.read_text())) == []


def test_no_page_reads_its_project_on_its_own():
    assert sorted(p.name for p in PAGES if OWN_PROJECT.search(p.read_text())) == []
