"""Every app wears the brand theme in shared/theme/brand.json.

The theme is "brand, without the background grid": one palette, three fonts (MuseoModerno for
headings, Raleway for text, IBM Plex Mono for ids, labels and code). Each app keeps its own layout
and sets in its :root only the variables it uses; this test holds each of those to brand.json:
- every variable an app's :root sets that brand.json names has brand.json's value;
- no Inter is left in the app's font stacks, Google Fonts links or font imports;
- no launcher page draws the blueprint grid (the body::before hairline grid).
The root's own pages (the launcher and the report composer) are also held to load the new fonts
and to colour their headings with --heading.
"""
import json
import re

import pytest

from conftest import ROOT

BRAND = json.loads((ROOT / "shared/theme/brand.json").read_text())
VARIABLES = BRAND["variables"]

LAUNCHER = sorted((ROOT / "homepage").glob("*.html"))
COMPOSER = ROOT / "apps/report-composer/report_composer"

# Each app's stylesheet (the file whose :root carries its palette), and the files where the
# same app links or imports its fonts.
APPS = {
    **{f"homepage/{p.name}": (p, [p]) for p in LAUNCHER},
    "qualification": (
        ROOT / "apps/qualification/src/app/globals.css",
        [ROOT / "apps/qualification/src/app/globals.css",
         ROOT / "apps/qualification/src/app/layout.tsx",
         ROOT / "apps/qualification/package.json"],
    ),
    "controls": (
        ROOT / "apps/controls/src/app/globals.css",
        [ROOT / "apps/controls/src/app/globals.css",
         ROOT / "apps/controls/src/app/layout.tsx"],
    ),
    "control-objectives": (
        ROOT / "apps/control-objectives/src/aisc_control_objectives/templates/_base.html.j2",
        [ROOT / "apps/control-objectives/src/aisc_control_objectives/templates/_base.html.j2"],
    ),
    "report-composer": (
        COMPOSER / "static/composer.css",
        [COMPOSER / "static/composer.css", COMPOSER / "templates/base.html.j2"],
    ),
}

# Inter, wherever a font is named: a quoted family in a font stack, an unquoted one after
# font-family:, a Google Fonts family=, an npm @fontsource(-variable)/inter import.
INTER = [
    re.compile(r"""["']Inter["']"""),
    re.compile(r"font-family\s*:\s*Inter\b", re.I),
    re.compile(r"family=Inter\b", re.I),
    re.compile(r"@fontsource(-variable)?/inter\b", re.I),
]


def root_variables(text: str) -> dict[str, str]:
    """The custom properties set in every :root { ... } block of a stylesheet (later wins)."""
    found = {}
    for block in re.findall(r":root\s*\{([^}]*)\}", text):
        for name, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);?", block):
            found[name] = value.strip()
    return found


def rules(text: str, selector_part: str) -> list[str]:
    """The bodies of the CSS rules whose selector contains selector_part."""
    return [body for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text) if selector_part in sel]


@pytest.mark.parametrize("app", sorted(APPS))
def test_the_root_variables_have_the_brand_values(app):
    sheet, _ = APPS[app]
    assert sheet.exists(), f"{app}: {sheet.relative_to(ROOT)} is missing"
    found = root_variables(sheet.read_text())
    assert found, f"{app}: no :root variables in {sheet.relative_to(ROOT)}"
    wrong = {name: (found[name], want) for name, want in VARIABLES.items()
             if name in found and found[name].lower() != want}
    assert not wrong, f"{app}: :root values that differ from brand.json (found, wanted): {wrong}"


@pytest.mark.parametrize("app", sorted(APPS))
def test_no_inter_font_is_left(app):
    _, files = APPS[app]
    left = [f"{f.relative_to(ROOT)}: {m.group(0)}"
            for f in files if f.exists()
            for pattern in INTER for m in pattern.finditer(f.read_text())]
    assert not left, f"{app} still names Inter: {left}"


@pytest.mark.parametrize("page", LAUNCHER, ids=lambda p: p.name)
def test_no_launcher_page_draws_the_blueprint_grid(page):
    text = page.read_text()
    grids = [b for b in rules(text, "body::before") if "linear-gradient" in b or "background-size" in b]
    assert not grids, f"{page.name} still draws the blueprint grid: {grids}"


# ---- the root's own pages: the new fonts are loaded and used, headings take --heading ----

GOOGLE_FONTS = re.compile(r"https://fonts\.googleapis\.com/css2\?[^\"']+")


def font_link(text: str) -> str:
    links = GOOGLE_FONTS.findall(text)
    assert len(links) == 1, f"expected one Google Fonts link, found {links}"
    return links[0]


@pytest.mark.parametrize("page", LAUNCHER + [COMPOSER / "templates/base.html.j2"], ids=lambda p: p.name)
def test_the_page_loads_the_brand_fonts(page):
    link = font_link(page.read_text())
    for family in ("family=MuseoModerno:", "family=Raleway:", "family=IBM+Plex+Mono:"):
        assert family in link, f"{page.name}: {family} missing from {link}"


@pytest.mark.parametrize("sheet", LAUNCHER + [COMPOSER / "static/composer.css"], ids=lambda p: p.name)
def test_text_is_raleway_and_headings_are_museomoderno_in_the_heading_colour(sheet):
    text = sheet.read_text()
    assert root_variables(text).get("--heading") == VARIABLES["--heading"]
    assert re.search(r'font-family\s*:\s*"Raleway"', text), f"{sheet.name}: text is not set in Raleway"
    headings = [b for sel, b in re.findall(r"([^{}]+)\{([^{}]*)\}", text)
                if re.fullmatch(r"\s*h1\s*,\s*h2\s*,\s*h3\s*,\s*h4\s*", sel)]
    assert headings, f"{sheet.name}: no h1, h2, h3, h4 rule"
    assert any('"MuseoModerno"' in b and "color:var(--heading)" in b.replace(" ", "") for b in headings), \
        f"{sheet.name}: h1-h4 are not MuseoModerno in var(--heading): {headings}"


# ---- every app's top header and logo the same size (brand.json "header") ----

HEADER = BRAND["header"]

# Per app: the sheet, the rule that draws the bottom border, the rule that sets the padding,
# the logo's rule, and the product title's rule (None: the app shows no title, as controls).
_LAUNCHER_HEADER = (".topbar", ".topbar", ".topbar img", ".topbar h1")
_SITE_HEADER = (".site-header", ".site-header .inner", ".site-header .brand img", ".site-header .brand")
HEADERS = {
    **{f"homepage/{p.name}": (p, *_LAUNCHER_HEADER) for p in LAUNCHER},
    "qualification": (APPS["qualification"][0], *_SITE_HEADER),
    "controls": (APPS["controls"][0], *_SITE_HEADER[:3], None),
    "control-objectives": (APPS["control-objectives"][0], *_SITE_HEADER),
    "report-composer": (APPS["report-composer"][0], *_SITE_HEADER),
}


def stylesheet(path) -> str:
    """The CSS of a file: a page's or template's <style> blocks, or the whole of a .css file."""
    text = path.read_text()
    if path.suffix == ".css":
        return text
    return "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S))


def top_level_rules(css: str) -> list[tuple[list[str], str]]:
    """(selectors, body) of each rule outside any @-block: a responsive @media rule that shrinks
    the header on narrow screens may stay, so it is not read here."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, depth, start, sel = [], 0, 0, ""
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                sel, start = css[start:i].strip(), i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                if not sel.startswith("@"):
                    out.append(([" ".join(s.split()) for s in sel.split(",")], css[start:i]))
                start = i + 1
    return out


def declarations(css: str, selector: str) -> dict[str, str]:
    """The properties the top-level rules for exactly this selector set (later wins)."""
    found = {}
    for selectors, body in top_level_rules(css):
        if selector in selectors:
            for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
                found[prop.strip().lower()] = " ".join(value.split())
    return found


def px(value: str) -> list[float]:
    return [float(v) for v in re.findall(r"(-?[\d.]+)px", value)]


def padding(decl: dict[str, str]) -> tuple[float, float, float, float]:
    """(top, right, bottom, left) in px from the padding shorthand and longhands."""
    vals = px(decl.get("padding", "0px"))
    vals = {1: vals * 4, 2: vals * 2, 3: vals + vals[1:2], 4: vals}.get(len(vals), [0.0] * 4)
    top, right, bottom, left = vals
    for side, i in (("top", 0), ("right", 1), ("bottom", 2), ("left", 3)):
        if f"padding-{side}" in decl:
            vals[i] = px(decl[f"padding-{side}"])[0]
    return tuple(vals)


@pytest.mark.parametrize("app", sorted(HEADERS))
def test_the_header_has_the_brand_padding_and_border(app):
    sheet, box, inner, _, _ = HEADERS[app]
    css = stylesheet(sheet)
    pad = padding(declarations(css, inner))
    want = (HEADER["padding_block_px"], HEADER["padding_inline_px"]) * 2
    assert pad == want, f"{app}: {inner} padding {pad}, wanted {want}"
    border = declarations(css, box).get("border-bottom")
    assert border == HEADER["border_bottom"], f"{app}: {box} border-bottom {border!r}"
    # 20 + 48 + 20 + 1 = 89: nothing in the header sets its own height
    for sel in {box, inner}:
        fixed = {k: v for k, v in declarations(css, sel).items() if k in ("height", "min-height", "max-height")}
        assert not fixed, f"{app}: {sel} fixes its height: {fixed}"
    assert 2 * HEADER["padding_block_px"] + HEADER["logo_height_px"] + 1 == HEADER["height_px"]


@pytest.mark.parametrize("app", sorted(HEADERS))
def test_the_logo_is_the_brand_height(app):
    sheet, _, _, logo, _ = HEADERS[app]
    height = declarations(stylesheet(sheet), logo).get("height", "")
    assert px(height) == [HEADER["logo_height_px"]], f"{app}: {logo} height {height!r}"


@pytest.mark.parametrize("app", sorted(a for a in HEADERS if HEADERS[a][4]))
def test_the_product_title_is_19px_museomoderno_700_in_sentence_case(app):
    sheet, _, _, _, title = HEADERS[app]
    css = stylesheet(sheet)
    # a title that is a heading starts from the sheet's h1-h4 rule
    decl = declarations(css, title.split()[-1]) if re.fullmatch(r"h[1-4]", title.split()[-1]) else {}
    decl = {**decl, **declarations(css, title)}
    family = decl.get("font-family", "")
    for name, value in root_variables(css).items():
        family = family.replace(f"var({name})", value)
    assert HEADER["title_font"] in family, f"{app}: {title} font-family {family!r}"
    assert px(decl.get("font-size", "")) == [HEADER["title_size_px"]], \
        f"{app}: {title} font-size {decl.get('font-size')!r}"
    assert decl.get("font-weight") == str(HEADER["title_weight"]), \
        f"{app}: {title} font-weight {decl.get('font-weight')!r}"
    assert decl.get("text-transform", "none") == HEADER["title_transform"], \
        f"{app}: {title} text-transform {decl.get('text-transform')!r}"
    assert decl.get("letter-spacing", "normal") in ("normal", "0", "0px", "0em"), \
        f"{app}: {title} letter-spacing {decl.get('letter-spacing')!r}"
