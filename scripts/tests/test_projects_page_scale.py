"""The sizes of the projects page (homepage/index.html).

The top bar uses the project page's values so the two bars match; the project cards are large and
sit centred as one wrapped row. Hairlines stay 1px."""
import re
from pathlib import Path

HOMEPAGE = Path(__file__).resolve().parents[2] / "homepage"


def css(page: str) -> str:
    style = re.search(r"<style>(.*?)</style>", (HOMEPAGE / page).read_text(), re.S).group(1)
    return re.sub(r"/\*.*?\*/", "", style, flags=re.S)


def rule(selector: str, page: str = "index.html") -> str:
    m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", css(page))
    assert m, selector
    return m.group(1)


def px(selector: str, prop: str, page: str = "index.html") -> str:
    m = re.search(r"(?:^|;|\s)" + re.escape(prop) + r"\s*:\s*([^;]+)", rule(selector, page))
    assert m, (selector, prop)
    return m.group(1).strip()


def test_the_top_bar_matches_the_project_page():
    for selector, prop in [
        (".topbar", "padding"),
        (".topbar img", "height"),
        (".topbar h1", "font-size"),
        (".session", "font-size"),
        (".menu summary", "font-size"),
        (".menu .panel a", "font-size"),
        (".menu .panel", "min-width"),
    ]:
        assert px(selector, prop) == px(selector, prop, "project.html"), (selector, prop)


def test_the_project_cards_are_bigger():
    assert px("a.project", "width") == "440px"
    assert px("a.project", "padding") == "34px"
    assert px("a.project h3", "font-size") == "26px"
    assert px("a.project .slug", "font-size") == "14px"
    assert px("a.project p", "font-size") == "17px"
    assert px("a.project time", "font-size") == "14px"


def test_the_heading_and_button_are_bigger():
    assert px(".head h2", "font-size") == "16px"
    assert px(".newbtn", "font-size") == "14px"
    assert px(".newbtn", "padding") == "13px 20px"


def test_the_projects_sit_in_the_middle():
    assert px(".projects", "display") == "flex"
    assert px(".projects", "flex-wrap") == "wrap"
    assert px(".projects", "justify-content") == "center"
    # the heading spans the cards, not the whole page, and the block is centred
    assert px(".stage", "width") == "fit-content"
    assert px(".stage", "margin") == "0 auto"
    assert px("a.project", "max-width") == "100%"


def test_hairlines_stay_hairlines():
    assert "1px solid var(--border)" in rule("a.project")
    assert "1px solid var(--border)" in rule(".topbar")
