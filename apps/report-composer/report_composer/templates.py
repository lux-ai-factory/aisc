"""A report's look: checking a template, sending it to the renderer, and its export file.

A template is font, base font size, primary and accent colour, an optional logo, header text,
footer text, a confidentiality marking and whether the document id is printed. The
fonts are the renderer's (GET /v1/fonts), because only those can be drawn in the PDF.
"""
from __future__ import annotations

import base64
import binascii
import re

from .errors import ApiError

EXPORT_FORMAT = "aisc-report-template"
EXPORT_VERSION = 2
MARKINGS = ("none", "public", "internal", "confidential", "strictly_confidential")
TEXT_MAX = 120
LOGO_MIMES = ("image/png", "image/jpeg", "image/svg+xml")
LOGO_MAX_BYTES = 1_048_576
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _bad(pointer: str, message: str):
    raise ApiError(422, "invalid_template", message, [{"pointer": pointer, "message": message}])


def checked(body: dict, fonts: list[dict]) -> tuple[dict, tuple[str, bytes] | None]:
    """The template's fields and its logo as (mime, bytes), or a 422 naming what is wrong."""
    if not isinstance(body, dict):
        _bad("", "A template is an object.")
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
    return logo["mime"], raw


def _looks_like(mime: str, raw: bytes) -> bool:
    if mime == "image/png":
        return raw.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return raw.startswith(b"\xff\xd8\xff")
    head = raw[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<") and b"<svg" in raw[:65536].lower()


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
    """The name, or "name (2)", "name (3)" ... when the project already has it."""
    if name not in taken:
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    return f"{name} ({n})"[:120]


def filename(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "template"
    return f"report-template-{slug[:60]}.json"
