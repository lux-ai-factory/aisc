"""Fixtures of the composer tests (report run 2026-09-23, stage 3; 02 section 5).

Database tests run on a throwaway postgres:15-alpine bed in the isolated layout
(scripts/lib/report_bed_isolated.py, isolation 2026-09-25): the core part of the seed (projects alpha,
beta, gamma, echo; members) in `platform`, and one database per project holding its versions in
project.system and the composer's schema. The composer connects as `report_composer_rw`. Never the
host's 5432.

The API the tests assume of `report_composer` (stage 5 implements it; isolation I8.1 adds the project DSN):

    report_composer.app.create_app(*, database_url, project_database_url, renderer, clock=None) -> FastAPI
        routes: /api/... (R4.3, the /report-composer prefix is stripped by Caddy) and /p/{slug}/... pages;
        migrations run at start (lifespan), so the TestClient is used as a context manager.
    renderer: an object with block_types(), choices(project_id, system_id, block_type), render(snapshot)
        raising report_composer.renderer_client.RendererUnavailable / RendererTimeout;
        report_composer.renderer_client.HttpRendererClient(base_url, token, timeout=120.0)
    report_composer.layouts: default_blocks, validate_layout, reset_invalid
    report_composer.reports.pdf_filename(slug, number, layout_name, when)
    report_composer.access: Access(role, admin), decide(method, access), same_origin(headers, origin)
    report_composer.forms.form_fields(options_schema, values, choices)
"""
from __future__ import annotations

import base64
import copy
import importlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]           # aisc-install
sys.path.insert(0, str(ROOT / "scripts/lib"))
import report_bed  # noqa: E402
import report_bed_isolated  # noqa: E402

IDS = report_bed.IDS


def pdb_of(key: str = "A") -> str:
    """The database of the seed's project `key` (isolation: a project's composer rows live there)."""
    return report_bed.project_db(IDS[key])
ISSUER = "http://keycloak:8080/realms/aisc"
ORIGIN = "http://localhost"
FIXED_NOW = datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc)
PDF = b"%PDF-1.7\n% fake pdf from the fake renderer\n%%EOF\n"


def need(module: str, name: str):
    try:
        mod = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name and (exc.name == module or module.startswith(exc.name + ".")):
            pytest.fail(f"missing feature: module {module}", pytrace=False)
        raise
    value = getattr(mod, name, None)
    if value is None:
        pytest.fail(f"missing feature: {module}.{name}", pytrace=False)
    return value


class Missing:
    """A fixture value while the code under test is missing: using it FAILS the test body."""

    def __init__(self, message):
        self._message = message

    def __getattr__(self, name):
        pytest.fail(self._message, pytrace=False)

    def __call__(self, *a, **k):
        pytest.fail(self._message, pytrace=False)


def lazily(make):
    try:
        return make()
    except pytest.fail.Exception as exc:
        return Missing(str(exc))


# ── the block types a fake renderer offers (shapes of the real ones, R5.4 /v1/block-types) ──

COMMON = {"title": {"type": "string", "minLength": 0, "maxLength": 200},
          "page_break_before": {"type": "boolean"}}


def _type(type_id, title, props, defaults, required=()):
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
              "properties": {**COMMON, **props}, "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    return {"type_id": type_id, "title": title, "contract_version": 1, "options_schema": schema,
            "default_options": {"title": "", "page_break_before": False, **defaults}}


BLOCK_TYPES = [
    _type("cover", "Cover", {"report_title": {"type": "string", "minLength": 1, "maxLength": 200},
                             "subtitle": {"type": "string", "maxLength": 300},
                             "show_logo": {"type": "boolean"}, "show_generated_by": {"type": "boolean"}},
          {"report_title": "AI system assessment report", "subtitle": "", "show_logo": True, "show_generated_by": True}),
    _type("ai_card", "AI card", {"show_components": {"type": "boolean"}, "show_tags": {"type": "boolean"},
                                 "show_graph_stats": {"type": "boolean"}},
          {"show_components": True, "show_tags": True, "show_graph_stats": False}),
    _type("risk_classification", "Risk classification",
          {"show_chains": {"type": "boolean"}, "show_impact_areas": {"type": "boolean"},
           "stated_risk_class": {"enum": ["not_determined", "prohibited", "high", "limited", "minimal"]}},
          {"show_chains": True, "show_impact_areas": True, "stated_risk_class": "not_determined"}),
    _type("control_objectives", "Control objectives",
          {"group_by": {"enum": ["objective", "risk"]}, "show_rationale": {"type": "boolean"},
           "show_quotes": {"type": "boolean"}, "show_status": {"type": "boolean"}},
          {"group_by": "objective", "show_rationale": True, "show_quotes": False, "show_status": True}),
    _type("test_results", "Test results",
          {"evaluations": {"x-aisc-reference": True,
                           "oneOf": [{"const": "all"}, {"type": "array", "items": {"type": "string"}}]},
           "tools": {"oneOf": [{"const": "all"},
                               {"type": "array", "items": {"type": "string", "x-aisc-prose": False}}]},
           "statuses": {"type": "array", "items": {"type": "string", "x-aisc-prose": False}},
           "show_measurements": {"type": "boolean"}, "show_artifacts": {"type": "boolean"}},
          {"evaluations": "all", "tools": "all", "statuses": ["Done"], "show_measurements": True, "show_artifacts": False}),
    _type("control_answers", "Control answers",
          {"checklists": {"x-aisc-reference": True,
                          "oneOf": [{"const": "all"}, {"type": "array", "items": {"type": "string"}}]},
           "show_unanswered": {"type": "boolean"}, "show_scores": {"type": "boolean"},
           "include_archived": {"type": "boolean"}},
          {"checklists": "all", "show_unanswered": True, "show_scores": True, "include_archived": False}),
    _type("dashboard_chart", "Dashboard chart",
          {"chart_id": {"type": "integer", "x-aisc-reference": True}, "show_comments": {"type": "boolean"},
           "include_replies": {"type": "boolean"}, "width": {"type": "integer", "minimum": 400, "maximum": 1600},
           "height": {"type": "integer", "minimum": 300, "maximum": 1200}},
          {"show_comments": True, "include_replies": True, "width": 1200, "height": 700}, required=("chart_id",)),
    _type("summary_coverage", "Summary / coverage",
          {"links": {"type": "array", "x-aisc-reference": True, "items": {
              "type": "object", "properties": {"objective_id": {"type": "string"},
                                               "tests": {"type": "array", "items": {"type": "string"}},
                                               "checklists": {"type": "array", "items": {"type": "string"}}}}},
           "show_uncovered_only": {"type": "boolean"}},
          {"links": [], "show_uncovered_only": False}),
    _type("free_text", "Free text", {"text": {"type": "string", "minLength": 1, "maxLength": 20000}}, {},
          required=("text",)),
]
DEFAULT_ORDER = ["cover", "ai_card", "risk_classification", "control_objectives", "test_results",
                 "control_answers", "summary_coverage"]

#: what the fake renderer offers as choices, per (system, block type): only Alpha v2 / v3 data
CHOICES = {
    (IDS["A_V2"], "test_results"): {"evaluations": [{"value": IDS["EVAL_A_V2"], "label": "2026-09-10"},
                                                    {"value": IDS["EVAL_A_V2_NOCONFIG"], "label": "2026-09-09"}]},
    (IDS["A_V3"], "test_results"): {"evaluations": [{"value": IDS["EVAL_A_V3"], "label": "2026-09-16"}]},
    (IDS["A_V2"], "dashboard_chart"): {"chart_id": [{"value": 33, "label": "Bias rate by version"},
                                                    {"value": 34, "label": "Checklist scores"}]},
    (IDS["A_V3"], "dashboard_chart"): {"chart_id": [{"value": 33, "label": "Bias rate by version"},
                                                    {"value": 34, "label": "Checklist scores"}]},
    (IDS["A_V2"], "control_answers"): {"checklists": [{"value": "cl-1", "label": "Transparency checklist"}]},
    (IDS["B_V1"], "test_results"): {"evaluations": [{"value": IDS["EVAL_B_V1"], "label": "2026-09-03"}]},
}


FONTS = [{"id": "inter", "label": "Inter"}, {"id": "liberation-serif", "label": "Liberation Serif (Times)"}]


class FakeRenderer:
    """The renderer from the composer's side (R7.4.1): records what it is sent."""

    def __init__(self):
        self.snapshots = []
        self.choice_calls = []
        self.fail = None             # an exception instance to raise from render
        self.error_blocks = set()    # instance ids rendered as status=error
        self.pdf = PDF

    def block_types(self):
        return copy.deepcopy(BLOCK_TYPES)

    def fonts(self):
        return copy.deepcopy(FONTS)

    def choices(self, project_id, system_id, block_type):
        self.choice_calls.append((str(project_id), str(system_id), block_type))
        return copy.deepcopy(CHOICES.get((str(system_id), block_type), {}))

    def render(self, snapshot):
        self.snapshots.append(copy.deepcopy(snapshot))
        if self.fail:
            raise self.fail
        known = {t["type_id"] for t in BLOCK_TYPES}
        statuses = [{"instance_id": b["instance_id"], "block_type": b["block_type"],
                     "status": "error" if (b["instance_id"] in self.error_blocks or b["block_type"] not in known) else "ok",
                     "notices": []} for b in snapshot["blocks"]]
        if snapshot["mode"] == "preview":
            html = "<!DOCTYPE html><html><body>" + "".join(
                f'<section id="block-{b["instance_id"]}">{b["block_type"]}</section>' for b in snapshot["blocks"]) + "</body></html>"
            return {"html": html, "block_statuses": statuses}
        import hashlib

        return {"pdf_base64": base64.b64encode(self.pdf).decode(), "sha256": hashlib.sha256(self.pdf).hexdigest(),
                "block_statuses": statuses}


# ── the bed ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def bed():
    report_bed.check_dsn_env()
    # isolation S-D13: the isolated layout; gamma gets a database too, as "another project alice edits"
    b = report_bed_isolated.build_isolated("composer", modules=False, no_database=frozenset())
    yield b
    b.stop()


@pytest.fixture
def fake_renderer():
    return FakeRenderer()


@pytest.fixture(scope="session")
def key():
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def token(key):
    import jwt

    def make(subject, roles=("primary-user",), username=None, email=None):
        claims = {"sub": subject, "iss": ISSUER, "exp": int(time.time()) + 300,
                  "realm_access": {"roles": list(roles)}}
        if username is not False:
            claims["preferred_username"] = username or subject
        claims["email"] = email or f"{subject}@localhost"
        return jwt.encode(claims, key, algorithm="RS256")

    return make


@pytest.fixture
def auth(token):
    """Headers for a caller as the gateway sends them, with the same-origin header (R4.4.6)."""
    def make(subject, roles=("primary-user",), origin=ORIGIN, **kw):
        h = {"Authorization": f"Bearer {token(subject, roles, **kw)}"}
        if origin:
            h["Origin"] = origin
        return h

    return make


@pytest.fixture
def make_client(bed, key, monkeypatch):
    """The composer app on the bed, authentication on, verifying against the test key."""
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_JWKS_URL", "http://keycloak:8080/unused-in-tests")
    monkeypatch.setenv("PLATFORM_ORIGIN", ORIGIN)
    monkeypatch.setenv("REPORT_COMPOSER_DATABASE_URL", bed.dsn("report_composer_rw", "platform"))
    monkeypatch.setenv("REPORT_COMPOSER_PROJECT_DATABASE_URL", bed.project_db_template("report_composer_rw"))
    monkeypatch.setenv("REPORT_SERVICE_TOKEN", "composer-test-token-0123456789")
    import aisc_identity.service

    monkeypatch.setattr(aisc_identity.service, "key_for_jwks", lambda url: (lambda _t: key.public_key()))
    opened = []

    def make(renderer, clock=lambda: FIXED_NOW):
        from fastapi.testclient import TestClient

        def build():
            app = need("report_composer.app", "create_app")(
                database_url=bed.dsn("report_composer_rw", "platform"),
                project_database_url=bed.project_db_template("report_composer_rw"), renderer=renderer, clock=clock)
            c = TestClient(app, base_url="http://localhost")
            c.__enter__()
            opened.append(c)
            return c

        return lazily(build)

    yield make
    for c in opened:
        c.__exit__(None, None, None)


@pytest.fixture
def client(make_client, fake_renderer):
    return make_client(fake_renderer)


@pytest.fixture
def clean_layouts(bed):
    """Every test starts with no layouts, templates or reports (the tables may not exist yet), in each
    project's database."""
    for k in ("A", "B", "C", "E"):
        bed.psql(pdb_of(k), "DO $$ BEGIN IF to_regclass('report_composer.layout') IS NOT NULL THEN "
                            "TRUNCATE report_composer.layout, report_composer.template CASCADE; END IF; END $$;",
                 check=False)
    yield


def error_code(response) -> str | None:
    try:
        return response.json()["error"]["code"]
    except Exception:
        return None


def new_template(client, auth, slug="alpha", who="alice", **body):
    body.setdefault("name", f"Look {time.monotonic_ns()}")
    body.setdefault("font", "inter")
    body.setdefault("font_size_pt", 10)
    body.setdefault("primary_color", "#000fdf")
    body.setdefault("accent_color", "#ff007e")
    r = client.post(f"/api/p/{slug}/templates", json=body, headers=auth(who))
    assert r.status_code == 201, (r.status_code, r.text[:500])
    return r.json()


def some_template(client, auth, slug="alpha", who="alice") -> str:
    """A template of this project to save layouts with: the first one, made when there is none."""
    r = client.get(f"/api/p/{slug}/templates", headers=auth(who))
    if r.status_code == 200 and r.json():
        return r.json()[0]["id"]
    return new_template(client, auth, slug=slug, who=who, name="House style")["id"]


def new_layout(client, auth, slug="alpha", who="alice", **body):
    body.setdefault("name", f"Layout {time.monotonic_ns()}")
    if "template_id" not in body:
        body["template_id"] = some_template(client, auth, slug=slug, who=who)
    r = client.post(f"/api/p/{slug}/layouts", json=body, headers=auth(who))
    assert r.status_code == 201, (r.status_code, r.text[:500])
    return r.json()


def put_layout(client, auth, layout, slug="alpha", who="alice", **changes):
    body = {"name": layout["name"], "description": layout.get("description") or "",
            "system_id": layout["system_id"], "revision": layout["revision"], "blocks": layout["blocks"],
            "template_id": layout.get("template_id")}
    body.update(changes)
    return client.put(f"/api/p/{slug}/layouts/{layout['id']}", json=body, headers=auth(who))


def blk(block_type, **options):
    import uuid

    return {"instance_id": str(uuid.uuid4()), "block_type": block_type, "options": options}
