"""The stylesheet and the script are linked with a hash of their content (?v=), so a browser that kept an older copy
fetches the new one after a deploy instead of drawing the new page with the old styles."""
import hashlib
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "report_composer"


def digest(name):
    return hashlib.sha256((PACKAGE / "static" / name).read_bytes()).hexdigest()[:12]


def test_an_asset_link_carries_the_hash_of_its_content():
    from report_composer.jinja_env import env

    assert env.globals["asset"]("composer.css") == f"/static/composer.css?v={digest('composer.css')}"
    assert env.globals["asset"]("composer.js") == f"/static/composer.js?v={digest('composer.js')}"


def test_the_base_page_links_the_stylesheet_with_its_hash():
    from report_composer.jinja_env import env

    html = env.get_template("base.html.j2").render(root="/report-composer")
    assert f'href="/report-composer/static/composer.css?v={digest("composer.css")}"' in html


def test_no_template_links_an_asset_without_its_hash():
    bare = [f.name for f in (PACKAGE / "templates").glob("*.j2")
            if re.search(r"static/composer\.(css|js)[\"']", f.read_text())]
    assert bare == []
