"""Cross-project isolation of every composer route that addresses an object by id (isolation 2026-09-25,
01-specs.md I16.5, I8.1, I8.3; section 23 risk 3).

On the isolated bed (isolation_fixtures.py) alice is an editor of alpha AND beta, so a refusal is not the
membership's: a layout, template or report of alpha lives only in alpha's database, and opened under beta it
is 404, every route, every method. Alpha's objects are intact afterwards. Ids of alpha named in a body under
beta (template_id, system_id) are 422 `*_not_in_project`.

Route inventory (report_composer/api.py, pages.py, 2026-09-25), every route with an object id in its path:
  layouts/{id}: GET, PUT, DELETE; /validate POST; /preview GET and POST; /outline POST; /duplicate POST;
  /export GET; /reports GET and POST (the /preset route and the preset library are gone, report modules 2026-09-28)
  reports/{id}: /pdf GET; /download GET
  templates/{id}: PUT, DELETE; /export GET; /logo GET
  page: GET /p/{ref}/layouts/{id}
"""
from __future__ import annotations

import base64

import pytest

from conftest import error_code, new_layout, new_template, put_layout
from isolation_fixtures import IDS, iso_bed, iso_clean, iso_make_client, pdb, unique  # noqa: F401
from v2_fakes import FakeRendererV2, v2blk

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("iso_clean")]

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode("ascii")
LOGO = {"mime": "image/png", "data_base64": PNG}


@pytest.fixture
def iso_client(iso_make_client):
    return iso_make_client(FakeRendererV2())


@pytest.fixture
def alphas(iso_client, auth):
    """A template with a logo, a layout on it and a generated PDF, all of alpha: made in the test body, so a
    missing feature fails the test instead of erroring its setup (the conftest's Missing rule)."""
    return lambda: _make_alphas(iso_client, auth)


def _make_alphas(iso_client, auth):
    t = new_template(iso_client, auth, slug="alpha", name=unique("Look"), logo=LOGO)
    lay = new_layout(iso_client, auth, slug="alpha", template_id=t["id"], system_id=IDS["A_V2"],
                     blocks=[v2blk("cover"), v2blk("free_text", text="alpha text")])
    r = iso_client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code in (200, 201), r.text[:300]
    rid = r.json().get("id") or r.json().get("report", {}).get("id")
    assert rid, r.json()
    return {"template": t, "layout": lay, "report": rid}


def _look(name):
    return {"name": name, "font": "inter", "font_size_pt": 10, "primary_color": "#000fdf", "accent_color": "#ff007e"}


def _layout_body(lay):
    return {"name": lay["name"], "description": "", "revision": lay["revision"],
            "blocks": lay["blocks"], "template_id": lay.get("template_id")}


# (method, path under /api/p/{slug} or a page, body maker)
ROUTES = [
    ("get", "/api/p/{slug}/layouts/{lid}", None),
    ("put", "/api/p/{slug}/layouts/{lid}", lambda w: _layout_body(w["layout"])),
    ("delete", "/api/p/{slug}/layouts/{lid}", None),
    ("post", "/api/p/{slug}/layouts/{lid}/validate", lambda w: {}),
    ("get", "/api/p/{slug}/layouts/{lid}/preview", None),
    ("post", "/api/p/{slug}/layouts/{lid}/preview", lambda w: _layout_body(w["layout"])),
    ("post", "/api/p/{slug}/layouts/{lid}/outline", lambda w: {"blocks": w["layout"]["blocks"]}),
    ("post", "/api/p/{slug}/layouts/{lid}/duplicate", lambda w: {}),
    ("get", "/api/p/{slug}/layouts/{lid}/export", None),
    ("get", "/api/p/{slug}/layouts/{lid}/reports", None),
    ("post", "/api/p/{slug}/layouts/{lid}/reports", lambda w: {}),
    ("get", "/api/p/{slug}/reports/{rid}/pdf", None),
    ("get", "/api/p/{slug}/reports/{rid}/download", None),
    ("put", "/api/p/{slug}/templates/{tid}", lambda w: _look(unique("Stolen look"))),
    ("delete", "/api/p/{slug}/templates/{tid}", None),
    ("get", "/api/p/{slug}/templates/{tid}/export", None),
    ("get", "/api/p/{slug}/templates/{tid}/logo", None),
    ("get", "/p/{slug}/layouts/{lid}", None),
]


def _call(client, auth, method, path, body, world, slug):
    url = path.format(slug=slug, lid=world["layout"]["id"], rid=world["report"], tid=world["template"]["id"])
    kw = {"json": body(world)} if body else {}
    return getattr(client, method)(url, headers=auth("alice"), **kw)


@pytest.mark.parametrize("method,path,body", ROUTES, ids=[f"{m} {p}" for m, p, _ in ROUTES])
def test_i16_5_an_alpha_object_opened_under_beta_is_404(iso_client, iso_bed, auth, alphas, method, path, body):
    """I16.5, I8.1: alpha's id under beta's project is 404 (it is not in beta's database), and alpha's rows
    are untouched afterwards."""
    alphas = alphas()
    r = _call(iso_client, auth, method, path, body, alphas, "beta")
    assert r.status_code == 404, (method, path, r.status_code, r.text[:300])
    a = pdb(IDS["A"])
    assert iso_bed.scalar(a, f"SELECT count(*) FROM report_composer.layout WHERE id = '{alphas['layout']['id']}'") == "1"
    assert iso_bed.scalar(a, f"SELECT count(*) FROM report_composer.template WHERE id = '{alphas['template']['id']}'"
                             " AND logo IS NOT NULL") == "1"
    assert iso_bed.scalar(a, "SELECT count(*) FROM report_composer.generated_report"
                             f" WHERE id = '{alphas['report']}'") == "1"
    b = pdb(IDS["B"])
    for table in ("layout", "template", "generated_report"):
        assert iso_bed.scalar(b, f"SELECT count(*) FROM report_composer.{table}") == "0", table


SAFE = [(m, p, b) for m, p, b in ROUTES if m == "get"]


@pytest.mark.parametrize("method,path,body", SAFE, ids=[f"{m} {p}" for m, p, _ in SAFE])
def test_i16_5_the_same_id_under_its_own_project_answers(iso_client, auth, alphas, method, path, body):
    """I16.5 counterpart: the 404 above is about the project, the ids are real under alpha."""
    alphas = alphas()
    r = _call(iso_client, auth, method, path, body, alphas, "alpha")
    assert r.status_code == 200, (method, path, r.status_code, r.text[:300])


def test_i8_3_alphas_template_named_in_a_beta_layout_is_422(iso_client, auth, alphas):
    """I8.3 with R-U6.1: a template id of alpha in beta's body is template_not_in_project."""
    alphas = alphas()
    r = iso_client.post("/api/p/beta/layouts", json={"name": unique("L"), "template_id": alphas["template"]["id"],
                                                     "system_id": IDS["B_V1"]}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "template_not_in_project", r.text[:300]
    own = new_layout(iso_client, auth, slug="beta", system_id=IDS["B_V1"])
    r = put_layout(iso_client, auth, own, slug="beta", template_id=alphas["template"]["id"])
    assert r.status_code == 422 and error_code(r) == "template_not_in_project", r.text[:300]


def test_i8_3_alphas_version_named_in_a_beta_report_is_422(iso_client, auth):
    """I8.3: a version of alpha chosen for a beta report is system_not_in_project (a layout holds no
    version since report modules 2026-09-28; the report does)."""
    own = new_layout(iso_client, auth, slug="beta", blocks=[v2blk("cover")])
    r = iso_client.post(f"/api/p/beta/layouts/{own['id']}/reports", json={"system_id": IDS["A_V2"]},
                        headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "system_not_in_project", r.text[:300]


def test_i16_5_beta_lists_nothing_of_alpha(iso_client, auth, alphas):
    """I16.5: beta's lists show none of alpha's layouts, templates or versions."""
    alphas = alphas()
    lays = iso_client.get("/api/p/beta/layouts", headers=auth("alice"))
    looks = iso_client.get("/api/p/beta/templates", headers=auth("alice"))
    systems = iso_client.get("/api/p/beta/systems", headers=auth("alice"))
    assert lays.status_code == looks.status_code == systems.status_code == 200
    assert alphas["layout"]["id"] not in {x["id"] for x in lays.json()}
    assert alphas["template"]["id"] not in {x["id"] for x in looks.json()}
    assert {s["pid"] for s in systems.json()} == {IDS["B_V1"]}
