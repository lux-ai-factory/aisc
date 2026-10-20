"""A report's look: checking a template, sending it to the renderer, and its export file.

A template is font, base font size, primary and accent colour, an optional logo, header text,
footer text, a confidentiality marking and whether the document id is printed. The
fonts are the renderer's (GET /v1/fonts), because only those can be drawn in the PDF.
"""
from __future__ import annotations

import base64
import binascii
import math
import re
import struct

from .errors import ApiError, refuse_lone_surrogate

EXPORT_FORMAT = "aisc-report-template"
EXPORT_VERSION = 2
MARKINGS = ("none", "public", "internal", "confidential", "strictly_confidential")
TEXT_MAX = 120
LOGO_MIMES = ("image/png", "image/jpeg", "image/svg+xml")
LOGO_MAX_BYTES = 1_048_576
#: the renderer's cap (report_renderer/style.py LOGO_MAX_PIXELS)
LOGO_MAX_PIXELS = 16_000_000
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _bad(pointer: str, message: str):
    raise ApiError(422, "invalid_template", message, [{"pointer": pointer, "message": message}])


def checked(body: dict, fonts: list[dict]) -> tuple[dict, tuple[str, bytes] | None]:
    """The template's fields and its logo as (mime, bytes), or a 422 naming what is wrong."""
    if not isinstance(body, dict):
        _bad("", "A look is an object.")
    refuse_lone_surrogate(body, "invalid_template")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        _bad("/name", "The name must be 1 to 120 characters.")
    font = body.get("font")
    if font not in {f["id"] for f in fonts}:
        _bad("/font", "Choose one of the offered fonts.")
    size = body.get("font_size_pt")
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not 8 <= size <= 16:
        _bad("/font_size_pt", "The font size is 8 to 16 points.")
    colours = {}
    for key in ("primary_color", "accent_color"):
        value = body.get(key)
        if not isinstance(value, str) or not _HEX.match(value):
            _bad(f"/{key}", "A colour is written #rrggbb.")
        colours[key] = value.lower()
    look = {"name": name.strip(), "font": font, "font_size_pt": float(size), **colours}
    for key in ("header_text", "footer_text"):
        value = body.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > TEXT_MAX):
            _bad(f"/{key}", f"The {key.split('_')[0]} text is at most {TEXT_MAX} characters.")
        look[key] = value if value else None
    marking = body.get("marking", "none")
    if marking is None:
        marking = "none"
    if marking not in MARKINGS:
        _bad("/marking", "The marking is one of " + ", ".join(MARKINGS) + ".")
    look["marking"] = marking
    show_id = body.get("show_document_id", False)
    if show_id is None:
        show_id = False
    if not isinstance(show_id, bool):
        _bad("/show_document_id", "show_document_id is true or false.")
    look["show_document_id"] = show_id
    return look, _logo(body.get("logo"))


def _logo(logo) -> tuple[str, bytes] | None:
    if logo is None:
        return None
    if not isinstance(logo, dict) or logo.get("mime") not in LOGO_MIMES:
        _bad("/logo/mime", "The logo is a PNG, JPEG or SVG image.")
    try:
        raw = base64.b64decode(logo.get("data_base64") or "", validate=True)
    except (binascii.Error, ValueError, TypeError):
        _bad("/logo/data_base64", "The logo could not be read.")
    if not raw:
        _bad("/logo/data_base64", "The logo is empty.")
    if len(raw) > LOGO_MAX_BYTES:
        _bad("/logo/data_base64", "The logo is at most 1 MB.")
    # The content is the declared type: the renderer's image library reads other formats whatever the
    # declared one (PSD, EPS, JPEG 2000...), so a file is refused here, and checked in full there.
    if not _looks_like(logo["mime"], raw):
        _bad("/logo/data_base64", "The logo's content is not the image type it is saved as.")
    problem = _size_problem(logo["mime"], raw)
    if problem:
        _bad("/logo/data_base64", problem)
    return logo["mime"], raw


def _looks_like(mime: str, raw: bytes) -> bool:
    if mime == "image/png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return raw.startswith(b"\xff\xd8\xff")
    head = raw[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<") and b"<svg" in raw[:65536].lower()


def _size_problem(mime: str, raw: bytes) -> str | None:
    """The renderer's size limits (report_renderer/style.py logo_problem): a raster
    logo has at most LOGO_MAX_PIXELS and a size in its header; an SVG, which the Word export rasterises
    at twice its declared size, at most LOGO_MAX_PIXELS once drawn so."""
    if mime == "image/png":
        size = _png_size(raw)
        if size is None:
            return "The logo is not a readable PNG image."
    elif mime == "image/jpeg":
        size = _jpeg_size(raw)
        if size is None:
            return "The logo is not a readable JPEG image."
    else:
        if _SVG_EMBEDS.search(raw):                           # An embedded raster is decoded in full
            return "The logo embeds an image or a link (<image>, <feImage>, href), which a logo does not need."
        size = _svg_size(raw)
        if size is None:                                      # The renderer refuses it
            return "The logo declares no usable width and height (nor viewBox)."
        size = (2 * size[0], 2 * size[1])
    width, height = size
    if not (math.isfinite(width) and math.isfinite(height)) or width * height > LOGO_MAX_PIXELS:
        return f"The logo has more than {LOGO_MAX_PIXELS} pixels."
    return None


def _png_size(raw: bytes) -> tuple[int, int] | None:
    """Width and height from the IHDR chunk, which a PNG starts with."""
    if raw[8:16] != b"\x00\x00\x00\rIHDR" or len(raw) < 24:
        return None
    width, height = struct.unpack(">II", raw[16:24])
    return (width, height) if width and height else None


#: the JPEG frame headers (SOF0..SOF15 but DHT, JPG and DAC), where the image's size is
_SOF = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_size(raw: bytes) -> tuple[int, int] | None:
    """Width and height from the first frame header, walking the segments before the scan."""
    i = 2
    while i + 4 <= len(raw):
        if raw[i] != 0xFF:
            return None
        marker = raw[i + 1]
        if marker == 0xFF:                                    # a fill byte
            i += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:          # standalone markers have no length
            i += 2
            continue
        if marker in (0xD9, 0xDA):                            # end of image or start of scan: no frame
            return None
        length = struct.unpack(">H", raw[i + 2:i + 4])[0]
        if marker in _SOF:
            if i + 9 > len(raw):
                return None
            height, width = struct.unpack(">HH", raw[i + 5:i + 9])
            return (width, height) if width and height else None
        i += 2 + length
    return None


#: what lets an SVG draw something it does not hold as vector shapes: an <image> or <feImage> (whose raster,
#: of any size, the renderer decodes whatever size the SVG declares) or any reference (href, xlink:href)
_SVG_EMBEDS = re.compile(rb"<(?:[A-Za-z_][\w.-]*:)?(?:image|feimage)\b|href\s*=", re.IGNORECASE)
_SVG_ROOT = re.compile(rb"<svg\b([^>]*)>", re.IGNORECASE)
_LENGTH = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*(px|pt|pc|mm|cm|in|em|ex)?\s*$")
#: CSS units in px at 96 dpi; em and ex for a 16 px (12 pt) font
_UNITS = {None: 1.0, "px": 1.0, "pt": 96 / 72, "pc": 16.0, "mm": 96 / 25.4, "cm": 96 / 2.54, "in": 96.0,
          "em": 16.0, "ex": 8.0}


def _svg_attribute(tag: str, name: str) -> str | None:
    found = re.search(r"(?:^|\s)" + name + r"\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", tag)
    return None if found is None else (found.group(1) if found.group(1) is not None else found.group(2))


def _svg_length(value: str | None) -> float | None:
    """An absolute length in px, or None (missing, relative or not a length)."""
    found = _LENGTH.match(value or "")
    return None if found is None else float(found.group(1)) * _UNITS[found.group(2)]


def _svg_size(raw: bytes) -> tuple[float, float] | None:
    """The size the root element declares, in px, as cairosvg reads it (report_renderer/style.py
    svg_size): its width and height, the viewBox's width or height for a side that has none (as it is,
    not in proportion), or None when a side is still missing or not positive. A missing or relative
    side is 100% of nothing around it, so 0."""
    root = _SVG_ROOT.search(raw[:65536])
    if root is None:
        return None
    tag = root.group(1).decode("utf-8", "replace")
    width, height = _svg_length(_svg_attribute(tag, "width")), _svg_length(_svg_attribute(tag, "height"))
    box = (_svg_attribute(tag, "viewBox") or "").replace(",", " ").split()
    if len(box) == 4:
        try:
            box_width, box_height = float(box[2]), float(box[3])
        except ValueError:
            box_width, box_height = None, None
        width, height = width or box_width, height or box_height
    if width is None or height is None or not width > 0 or not height > 0:
        return None
    return width, height


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


def view(t: dict) -> dict:
    """A template as the API shows it: no image, only whether it has one."""
    return {"id": t["id"], "name": t["name"], "font": t["font"], "font_size_pt": _number(t["font_size_pt"]),
            "primary_color": t["primary_color"], "accent_color": t["accent_color"], "has_logo": bool(t["has_logo"]),
            "updated_at": t.get("updated_at"), "header_text": t.get("header_text"),
            "footer_text": t.get("footer_text"), "marking": t.get("marking") or "none",
            "show_document_id": bool(t.get("show_document_id"))}


def _logo_json(t: dict) -> dict | None:
    if not t.get("logo"):
        return None
    return {"mime": t["logo_mime"], "data_base64": base64.b64encode(bytes(t["logo"])).decode("ascii")}


def style(t: dict) -> dict:
    """What the renderer is sent as the snapshot's `style` (a template read with its logo)."""
    s = {"font": t["font"], "font_size_pt": _number(t["font_size_pt"]), "primary_color": t["primary_color"],
         "accent_color": t["accent_color"]}
    logo = _logo_json(t)
    if logo:
        s["logo"] = logo
    # the optional fields only when set, so a template that leaves them out sends the plain style
    for key in ("header_text", "footer_text"):
        if t.get(key) is not None:
            s[key] = t[key]
    if (t.get("marking") or "none") != "none":
        s["marking"] = t["marking"]
    if t.get("show_document_id"):
        s["show_document_id"] = True
    return s


def export_doc(t: dict) -> dict:
    """The file a template is carried to another project in (read with its logo)."""
    look = {k: v for k, v in style(t).items() if k in ("font", "font_size_pt", "primary_color", "accent_color")}
    return {"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "name": t["name"], **look, "logo": _logo_json(t),
            "header_text": t.get("header_text"), "footer_text": t.get("footer_text"),
            "marking": t.get("marking") or "none", "show_document_id": bool(t.get("show_document_id"))}


def from_export(doc) -> dict:
    """The template fields of an export file, or a 422 when it is not one."""
    if not isinstance(doc, dict) or doc.get("format") != EXPORT_FORMAT or doc.get("version") not in (1, 2):
        raise ApiError(422, "not_a_template", "This file is not an exported report template.")
    fields = {k: doc.get(k) for k in ("name", "font", "font_size_pt", "primary_color", "accent_color", "logo")}
    if doc.get("version") == 2:
        fields.update({k: doc.get(k) for k in ("header_text", "footer_text", "marking", "show_document_id")})
    return fields


def free_name(name: str, taken: set[str]) -> str:
    """The name, or "name (2)", "name (3)" ... when the project already has it, at most 120 characters:
    the name is shortened before the suffix, and the candidate checked is the one returned."""
    if name not in taken:
        return name
    n = 2
    while True:
        suffix = f" ({n})"
        candidate = name[:120 - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


def filename(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "template"
    return f"report-template-{slug[:60]}.json"
