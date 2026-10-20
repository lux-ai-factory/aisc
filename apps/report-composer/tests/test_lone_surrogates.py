"""A lone surrogate ("\\ud800") is valid JSON but has no UTF-8 form: psycopg cannot send it as text and
Postgres refuses it in jsonb, so a layout or template carrying one ended in a 500. It is
refused as a 422 with a pointer, as the renderer does (snapshot.py _surrogate_problem). Database
tests, fake renderer."""
import json

import pytest

from conftest import blk, error_code, new_layout


pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

LONE = "Q3 \ud800 review"
LOOK = {"font": "inter", "font_size_pt": 10, "primary_color": "#000000", "accent_color": "#ffffff"}


def send(client, method, path, body, headers):
    """The body as a browser's JSON.stringify sends it: the surrogate written as the escape \\ud800."""
    return client.request(method, path, content=json.dumps(body),
                          headers={**headers, "Content-Type": "application/json"})


def pointers(r):
    return [d.get("pointer") for d in r.json()["error"]["details"]]


@pytest.mark.parametrize("body,pointer", [
    ({"name": LONE}, "/name"),
    ({"name": "Fine", "description": LONE}, "/description"),
    ({"name": "Fine", "blocks": [blk("free_text", text=LONE)]}, "/blocks/0/options/text"),
])
def test_a_new_layout_with_a_lone_surrogate_is_422(client, auth, body, pointer):
    r = send(client, "POST", "/api/p/alpha/layouts", body, auth("alice"))
    assert r.status_code == 422 and error_code(r) == "invalid_request"
    assert pointer in pointers(r)


def test_a_saved_layout_with_a_lone_surrogate_is_422(client, auth):
    lay = new_layout(client, auth, blocks=[blk("free_text", text="one")])
    body = {"name": lay["name"], "revision": lay["revision"], "template_id": lay.get("template_id"),
            "blocks": [blk("free_text", text=LONE)]}
    r = send(client, "PUT", f"/api/p/alpha/layouts/{lay['id']}", body, auth("alice"))
    assert r.status_code == 422 and "/blocks/0/options/text" in pointers(r)


@pytest.mark.parametrize("field", ["name", "header_text", "footer_text"])
def test_a_template_with_a_lone_surrogate_is_422(client, auth, field):
    body = {"name": "Fine look", **LOOK, field: LONE}
    r = send(client, "POST", "/api/p/alpha/templates", body, auth("alice"))
    assert r.status_code == 422 and error_code(r) == "invalid_template"
    assert f"/{field}" in pointers(r)


@pytest.mark.parametrize("doc,pointer", [
    ({"blocks": [{"block_type": "free_text", "options": {"text": LONE}}]}, "/file/blocks/0/options/text"),
    ({"name": LONE, "blocks": []}, "/file/name"),
])
def test_a_layout_file_with_a_lone_surrogate_is_422(client, auth, doc, pointer):
    """The blocks of an imported layout file went to the database unchecked (500)."""
    body = {"file": {"format": "aisc-report-preset", "version": 1, "name": "Carried", "description": "",
                     "toc": "auto", "numbering": False, **doc}}
    r = send(client, "POST", "/api/p/alpha/layouts", body, auth("alice"))
    assert r.status_code == 422 and error_code(r) == "invalid_request"
    assert pointer in pointers(r)
