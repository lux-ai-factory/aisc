"""Generated reports: the PDF's filename and the generation itself (report run 2026-09-23, R4.3.3 to R4.3.5)."""
from __future__ import annotations

import re
import unicodedata

MAX_PDF_BYTES = 25 * 1024 * 1024


def _slugify(value: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_).strip("-") or "report"


def pdf_filename(slug, number, layout_name, when) -> str:
    return f"{slug}-v{number}-{_slugify(layout_name)}-{when:%Y%m%d-%H%M}.pdf"
