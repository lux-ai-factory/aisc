"""The renderer's logo limits applied when a template is saved: the renderer
(report_renderer/style.py logo_problem) refuses a raster logo over 16,000,000 pixels or one it cannot
read, and an SVG by its declared size, which the Word export rasterises at twice that size. Saving such
a logo was accepted, and every preview and generation of a layout using it then failed. Now the save
answers 422 invalid_template, naming the logo."""
import pytest

from conftest import FONTS, need
from logo_images import b64, jpeg_head, png, svg

BASE = {"name": "Look", "font": "inter", "font_size_pt": 10, "primary_color": "#000000", "accent_color": "#ffffff"}


def checked(mime, data):
    return need("report_composer.templates", "checked")({**BASE, "logo": {"mime": mime, "data_base64": b64(data)}},
                                                        FONTS)


def refused(mime, data) -> str:
    from report_composer.errors import ApiError

    with pytest.raises(ApiError) as caught:
        checked(mime, data)
    assert caught.value.status == 422 and caught.value.code == "invalid_template"
    [problem] = caught.value.details
    assert problem["pointer"] == "/logo/data_base64"
    return problem["message"]


def test_a_png_over_the_pixel_cap_is_refused():
    assert "16000000 pixels" in refused("image/png", png(5000, 5000))


def test_a_png_at_the_pixel_cap_is_kept():
    _, logo = checked("image/png", png(4000, 4000))
    assert logo[0] == "image/png"


def test_a_png_with_no_header_is_refused():
    assert "PNG" in refused("image/png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)


def test_a_jpeg_over_the_pixel_cap_is_refused():
    assert "16000000 pixels" in refused("image/jpeg", jpeg_head(8000, 2001))


def test_a_jpeg_of_a_usual_size_is_kept():
    _, logo = checked("image/jpeg", jpeg_head(800, 300))
    assert logo[0] == "image/jpeg"


def test_a_jpeg_with_no_frame_header_is_refused():
    assert "JPEG" in refused("image/jpeg", b"\xff\xd8\xff\xd9")


@pytest.mark.parametrize("attributes", [
    'width="16000" height="16000"',                       # A 101-byte SVG
    'width="2001" height="2000"',                         # x2 when rasterised: just over the cap
    'width="25in" height="25in"',                         # 2400 px a side at 96 dpi
    'viewBox="0 0 16000 16000"',                          # no size: the viewBox is the size
    'width="100%" height="100%" viewBox="0 0 9000 9000"',  # relative size: the viewBox again
    'width="1e400" height="10"',                          # not finite
    # one side and a viewBox: cairosvg takes the other side from the viewBox as it is, not in proportion,
    # so this is drawn 4000 x 3000 (8000 x 6000 rasterised), not 4000 x 3
    'width="4000" viewBox="0 0 4000000 3000"',
])
def test_an_svg_drawn_over_the_pixel_cap_is_refused(attributes):
    assert "16000000 pixels" in refused("image/svg+xml", svg(attributes))


@pytest.mark.parametrize("attributes", [
    'width="200" height="80"',
    'width="2000" height="2000"',
    'viewBox="0 0 200 80"',
    'stroke-width="99999" width="200" height="80"',
    'width="200" viewBox="0 0 400 80"',                    # one side, the other from the viewBox
])
def test_an_svg_of_a_usual_size_is_kept(attributes):
    _, logo = checked("image/svg+xml", svg(attributes))
    assert logo[0] == "image/svg+xml"


@pytest.mark.parametrize("attributes", [
    "",                                                   # no declared size at all
    'width="100"',                                        # one side and no viewBox: the other is 100%,
    'height="100"',                                       # which counts as 0 with nothing around it
    'width="100%" height="100%"',                         # relative only
    'width="0" height="0"',
])
def test_an_svg_with_no_usable_size_is_refused_as_the_renderer_refuses_it(attributes):
    """The renderer (style.logo_problem) refuses an SVG logo with no usable width and height
    (nor viewBox), so every preview and generation of a layout using it failed; the save took it."""
    assert "no usable width and height" in refused("image/svg+xml", svg(attributes))


def _svg_with(inner: str) -> bytes:
    return ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="200" height="100">{inner}</svg>').encode()


@pytest.mark.parametrize("inner", [
    '<image xlink:href="data:image/png;base64,iVBORw0KGgo=" width="200" height="100"/>',
    '<image href="data:image/png;base64,iVBORw0KGgo=" width="200" height="100"/>',
    '<filter id="f"><feImage href="#r"/></filter><rect id="r" width="1" height="1"/>',
    '<defs><rect id="r" width="1" height="1"/></defs><use xlink:href="#r"/>',
    '<a href="https://example.test/"><rect width="1" height="1"/></a>',
])
def test_an_svg_that_embeds_an_image_or_a_link_is_refused(inner):
    """An SVG of a small declared size can hold an <image> of a 12000 x 12000 raster, which the
    renderer decodes in full (cairosvg 719 MB, WeasyPrint 1.3 GB). A logo needs no image, filter image or
    link, so the save refuses any <image, <feImage, href or xlink:href, as the renderer does."""
    assert "image or a link" in refused("image/svg+xml", _svg_with(inner))


def test_an_svg_without_image_or_link_is_kept():
    _, logo = checked("image/svg+xml", _svg_with('<rect width="10" height="10" fill="#123456"/><text>href</text>'))
    assert logo[0] == "image/svg+xml"
