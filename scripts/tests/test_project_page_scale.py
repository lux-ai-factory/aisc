"""The project page (homepage/project.html) at 1.2x (2026-09-28, the user: "make all boxes in the
main page of aisc bigger, including the font, the manage menu, the top bar"). Hairlines stay 1px."""
import re
from pathlib import Path

CSS = re.sub(r"/\*.*?\*/", "", re.search(r"<style>(.*?)</style>", (Path(__file__).resolve().parents[2] / "homepage" / "project.html").read_text(), re.S).group(1), flags=re.S)


def rule(selector: str) -> str:
    m = re.search(r"(?:^|\})\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, selector
    return m.group(1)


def px(selector: str, prop: str) -> str:
    m = re.search(r"(?:^|;|\s)" + re.escape(prop) + r"\s*:\s*([^;]+)", rule(selector))
    assert m, (selector, prop)
    return m.group(1).strip()


def test_text_is_bigger():
    assert px("body", "font-size") == "18px"
    assert px(".card h2", "font-size") == "26.4px"
    assert px(".card p", "font-size") == "17.4px"
    # the step numbers went with the two blocks (2026-10-03, test_project_page_sandbox.py)


def test_boxes_are_bigger():
    assert px(".card", "padding") == "36px 40.8px 31.2px"
    assert px("a.sub", "padding") == "14.4px 16.8px 13.2px"
    assert px("main", "max-width") == "1632px"


def test_the_top_bar_is_bigger():
    assert px(".topbar", "padding") == "19.2px 38.4px"
    assert px(".topbar img", "height") == "38.4px"
    assert px(".topbar h1", "font-size") == "14.4px"
    assert px(".session", "font-size") == "13.8px"


def test_the_manage_menu_is_bigger():
    assert px(".menu summary", "font-size") == "13.2px"
    assert px(".menu .panel a", "font-size") == "13.8px"
    assert px(".menu .panel", "min-width") == "261.6px"


def test_hairlines_stay_hairlines():
    assert "1px solid var(--border)" in rule(".card")
    assert "1px solid var(--border)" in rule(".topbar")
