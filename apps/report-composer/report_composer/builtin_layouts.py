"""The five built-in layouts (report modules spec 2026-09-28, section 4.1): read-only, shared by every
project, opened to inspect and duplicated to adapt. They are the files of presets/; nothing is stored
for them. Their instance ids are derived from the file, so a built-in reads the same every time."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from . import presets

DIRECTORY = Path(__file__).resolve().parent / "presets"
ORDER = ("summary", "management-overview", "assessment-report", "eu-ai-act", "technical-dossier")
PREFIX = "builtin-"


def _view(slug: str, block_types) -> dict:
    doc = json.loads((DIRECTORY / f"{slug}.json").read_text(encoding="utf-8"))
    blocks = [{"instance_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"aisc-builtin/{slug}/{i}")),
               "block_type": b["block_type"], "options": presets.with_defaults(b, block_types)}
              for i, b in enumerate(doc["blocks"])]
    return {"id": PREFIX + slug, "name": doc["name"], "description": doc.get("description", ""), "built_in": True,
            "revision": 0, "template_id": None, "show_index": doc.get("show_index", True),
            "numbering": doc.get("numbering", False), "coverage": [], "blocks": blocks}


def all_layouts(block_types) -> list[dict]:
    return [_view(s, block_types) for s in ORDER]


def get(layout_id: str, block_types) -> dict | None:
    slug = layout_id[len(PREFIX):] if isinstance(layout_id, str) and layout_id.startswith(PREFIX) else None
    return _view(slug, block_types) if slug in ORDER else None
