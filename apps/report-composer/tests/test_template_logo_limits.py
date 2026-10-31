"""A template's logo is checked by the renderer, which owns the rule (report_renderer/style.py logo_problem,
behind POST /v1/style/check): a raster logo over 16,000,000 pixels or one it cannot read as its declared
type, an SVG drawn too large, with no usable size, or with an embedded or linked resource (<image>,
<feImage>, <foreignObject>, href). The composer keeps only the upload's own limits (type named, base64,
not empty, at most 1 MB) and asks the renderer for the rest before saving, so the two can no longer
disagree: a logo the renderer refuses is a 422 invalid_template naming the logo, in the renderer's words.
When the renderer does not answer in time, the logo is taken and the render reports it later."""
import base64

import pytest

from conftest import FONTS, need
from logo_images import PNG_1x1, b64, svg

BASE = {"name": "Look", "font": "inter", "font_size_pt": 10, "primary_color": "#000000", "accent_color": "#ffffff"}
FOREIGN = (b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
           b'<foreignObject width="200" height="100"><div xmlns="http://www.w3.org/1999/xhtml">x</div>'
           b'</foreignObject></svg>')
#: what the renderer answers for it (style.logo_problem)
FOREIGN_PROBLEM = "has an embedded or linked resource (<image>, <feImage>, <foreignObject> or href)"


class Renderer:
    """POST /v1/style/check as the composer sees it: the style sent, the problem answered."""

    def __init__(self, problem=None):
        self.problem, self.sent = problem, []

    def __call__(self, style):
        self.sent.append(style)
        return self.problem


def checked(logo, renderer):
    return need("report_composer.templates", "checked")({**BASE, "logo": logo}, FONTS, logo_check=renderer)


def refused(logo, renderer, pointer="/logo/data_base64") -> str:
    from report_composer.errors import ApiError

    with pytest.raises(ApiError) as caught:
        checked(logo, renderer)
    assert caught.value.status == 422 and caught.value.code == "invalid_template"
    [problem] = caught.value.details
    assert problem["pointer"] == pointer
    return problem["message"]


def test_the_logo_is_sent_to_the_renderer_as_the_snapshots_style():
    renderer = Renderer()
    logo = {"mime": "image/svg+xml", "data_base64": b64(svg('width="200" height="80"'))}
    _, kept = checked(logo, renderer)
    assert kept == ("image/svg+xml", svg('width="200" height="80"'))
    assert renderer.sent == [{"logo": logo}]


def test_a_foreign_object_logo_is_refused_in_the_renderers_words():
    """<foreignObject> was the gap: the composer's own copy of the rule let it through, the renderer did not."""
    renderer = Renderer(FOREIGN_PROBLEM)
    message = refused({"mime": "image/svg+xml", "data_base64": b64(FOREIGN)}, renderer)
    assert message == "The logo " + FOREIGN_PROBLEM + "."
    assert base64.b64decode(renderer.sent[0]["logo"]["data_base64"]) == FOREIGN


def test_any_problem_the_renderer_names_refuses_the_save():
    message = refused({"mime": "image/png", "data_base64": PNG_1x1},
                      Renderer("has more than 16000000 pixels"))
    assert message == "The logo has more than 16000000 pixels."


@pytest.mark.parametrize("logo, pointer, words", [
    ({"mime": "application/pdf", "data_base64": PNG_1x1}, "/logo/mime", "PNG, JPEG or SVG"),
    ({"mime": "image/png", "data_base64": "not base64!"}, "/logo/data_base64", "could not be read"),
    ({"mime": "image/png", "data_base64": ""}, "/logo/data_base64", "empty"),
    ({"mime": "image/png", "data_base64": b64(b"x" * 1_100_000)}, "/logo/data_base64", "at most 1 MB"),
])
def test_the_uploads_own_limits_are_checked_here_without_asking(logo, pointer, words):
    renderer = Renderer()
    assert words in refused(logo, renderer, pointer)
    assert renderer.sent == []


def test_no_logo_asks_nothing():
    renderer = Renderer()
    _, logo = need("report_composer.templates", "checked")(BASE, FONTS, logo_check=renderer)
    assert logo is None and renderer.sent == []


def test_the_composer_keeps_no_copy_of_the_renderers_rule():
    import report_composer.templates as templates

    for gone in ("_SVG_EMBEDS", "_svg_size", "_png_size", "_jpeg_size", "_looks_like", "_size_problem"):
        assert not hasattr(templates, gone), gone


# ── the call itself: POST /v1/style/check within the quick deadline ──

@pytest.fixture
def answer(monkeypatch):
    seen = []

    def install(status, body):
        import httpx

        def stream(self, method, url, **kw):
            seen.append((method, url, kw.get("json"), self.timeout.read))
            response = httpx.Response(status, json=body, request=httpx.Request(method, url))

            class Streamed:
                def __enter__(self):
                    return response

                def __exit__(self, *exc):
                    return False

            return Streamed()

        monkeypatch.setattr(httpx.Client, "stream", stream)
        return seen

    return install


def client():
    return need("report_composer.renderer_client", "HttpRendererClient")("http://renderer:8001", token="t" * 32,
                                                                         quick_timeout=2.0)


def test_the_client_posts_the_style_and_reads_the_problem(answer):
    seen = answer(200, {"problem": FOREIGN_PROBLEM})
    style = {"logo": {"mime": "image/svg+xml", "data_base64": b64(FOREIGN)}}
    assert client().style_check_quick(style) == FOREIGN_PROBLEM
    assert seen == [("POST", "http://renderer:8001/v1/style/check", style, 2.0)]


def test_a_usable_logo_is_no_problem(answer):
    answer(200, {"problem": None})
    assert client().style_check_quick({"logo": {"mime": "image/png", "data_base64": PNG_1x1}}) is None
