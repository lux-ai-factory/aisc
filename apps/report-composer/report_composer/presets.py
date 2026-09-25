"""Presets: report structures without project data (report run v2, R-V1.1 to R-V1.12).

A preset is an ordered list of {block_type, options} plus the document settings language, toc and
numbering. Built-in presets are the JSON files of report_composer/presets/; saved presets sit in
report_composer.preset and are seen by every signed-in user; a preset file carries a structure to
another project or platform. A layout made from a preset keeps no link to it.
"""
from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import layouts
from .errors import ApiError

DIRECTORY = Path(__file__).resolve().parent / "presets"
BUILT_IN_ORDER = ("full-assessment", "eu-ai-act", "internal-audit", "executive-summary")
FILE_FORMAT = "aisc-report-preset"
FILE_VERSION = 1
MAX_BLOCKS = 50
NAME_MAX = 120
PLACEHOLDER = "Write this section."


@dataclass
class Preset:
    id: str | None
    name: str
    description: str = ""
    language: str | None = None
    toc: str | None = None
    numbering: bool | None = None
    blocks: list = field(default_factory=list)
    built_in: bool = False
    created_by: str | None = None

    @property
    def block_types(self) -> list[str]:
        return [b["block_type"] for b in self.blocks]


def _preset_of(doc: dict, *, built_in: bool, preset_id=None, created_by=None) -> Preset:
    return Preset(id=preset_id if preset_id is not None else doc.get("id"), name=doc.get("name") or "",
                  description=doc.get("description") or "", language=doc.get("language"), toc=doc.get("toc"),
                  numbering=doc.get("numbering"),
                  blocks=[{"block_type": b["block_type"], "options": dict(b.get("options") or {})}
                          for b in doc.get("blocks") or []],
                  built_in=built_in, created_by=created_by)


def built_in() -> list[Preset]:
    """The four built-in presets, in their fixed order."""
    return [_preset_of(json.loads((DIRECTORY / f"{pid}.json").read_text(encoding="utf-8")), built_in=True)
            for pid in BUILT_IN_ORDER]


def built_in_by_id(preset_id) -> Preset | None:
    return next((p for p in built_in() if p.id == preset_id), None)


def from_row(row: dict) -> Preset:
    return _preset_of(row, built_in=False, preset_id=row["id"], created_by=row.get("created_by"))


def summary(p: Preset) -> dict:
    """A preset as GET /api/presets lists it."""
    return {"id": p.id, "name": p.name, "description": p.description, "built_in": p.built_in,
            "block_types": p.block_types}


def _types(block_types) -> dict:
    return {t["type_id"]: t for t in block_types}


def unknown_types_problem(blocks, block_types) -> None:
    """422 unknown_block_type naming every block type the renderer does not offer (R-V1.5)."""
    types = _types(block_types)
    unknown = []
    for b in blocks:
        name = b.get("block_type") if isinstance(b, dict) else None
        if name not in types and name not in unknown:
            unknown.append(name)
    if unknown:
        raise ApiError(422, "unknown_block_type",
                       "This preset uses block types the report renderer does not offer: "
                       + ", ".join(str(u) for u in unknown) + ".",
                       [{"pointer": "/blocks", "block_type": u, "message": f"the block type {u!r} is not available"}
                        for u in unknown])


def _without_references(options: dict, block_type: dict) -> dict:
    """Options with every data reference set to its type default, or left out (R-V1.4)."""
    out = copy.deepcopy(options)
    defaults = block_type.get("default_options") or {}
    for name in layouts.reference_options(block_type):
        if name in defaults:
            out[name] = copy.deepcopy(defaults[name])
        else:
            out.pop(name, None)
    return out


def from_file(doc, block_types) -> Preset:
    """A preset file checked (R-V1.10): 422 not_a_preset, unknown_block_type, invalid_options or duplicate_cover."""
    if not isinstance(doc, dict) or doc.get("format") != FILE_FORMAT or doc.get("version") != FILE_VERSION:
        raise ApiError(422, "not_a_preset", "This file is not a report preset.")
    blocks = doc.get("blocks")
    if not isinstance(blocks, list) or not all(isinstance(b, dict) and isinstance(b.get("options", {}), dict)
                                               for b in blocks):
        raise ApiError(422, "not_a_preset", "This file is not a report preset.",
                       [{"pointer": "/blocks", "message": "must be a list of blocks"}])
    if len(blocks) > MAX_BLOCKS:
        raise ApiError(422, "too_many_blocks", f"A preset holds at most {MAX_BLOCKS} blocks.",
                       [{"pointer": "/blocks", "message": f"holds at most {MAX_BLOCKS} blocks"}])
    unknown_types_problem(blocks, block_types)
    types = _types(block_types)
    problems = []
    for i, b in enumerate(blocks):
        t = types[b["block_type"]]
        merged = {**copy.deepcopy(t.get("default_options") or {}), **(b.get("options") or {})}
        refs = layouts.reference_options(t)
        merged = {k: v for k, v in merged.items() if k not in refs}
        for p in layouts._option_problems(t["options_schema"], merged, None, set(refs), refs):
            problems.append({**p, "pointer": f"/blocks/{i}{p['pointer']}"})
    if problems:
        raise ApiError(422, "invalid_options", problems[0]["message"], problems)
    whole = layouts._layout_problems([{"instance_id": None, **b} for b in blocks])
    if whole:
        raise ApiError(422, whole[0]["code"], whole[0]["message"], whole)
    name = doc.get("name")
    if not isinstance(name, str) or not name.strip():
        name = "Imported preset"
    settings = {}
    if isinstance(doc.get("language"), str):
        settings["language"] = doc["language"]
    if doc.get("toc") in ("auto", "on", "off"):
        settings["toc"] = doc["toc"]
    if isinstance(doc.get("numbering"), bool):
        settings["numbering"] = doc["numbering"]
    description = doc.get("description") if isinstance(doc.get("description"), str) else ""
    return Preset(id=None, name=name.strip()[:NAME_MAX], description=description[:2000],
                  blocks=[{"block_type": b["block_type"], "options": dict(b.get("options") or {})} for b in blocks],
                  **settings)


def blocks_for_layout(preset: Preset, block_types) -> list[dict]:
    """The layout blocks of a preset: new instance ids, default options merged, references reset."""
    unknown_types_problem(preset.blocks, block_types)
    types = _types(block_types)
    out = []
    for b in preset.blocks:
        t = types[b["block_type"]]
        options = {**copy.deepcopy(t.get("default_options") or {}), **copy.deepcopy(b.get("options") or {})}
        out.append({"instance_id": str(uuid.uuid4()), "block_type": b["block_type"],
                    "options": _without_references(options, t)})
    return out


# Free text of the built-in blocks, used when the renderer does not describe a block type.
KNOWN_FREE_TEXT = {"free_text": (("text", True),), "chapter": (("intro", False),)}
# A text option longer than this is prose written for one project (text, intro, commentary), not a title.
TITLE_MAX = 300


def _free_text_options(type_id: str, block_type: dict | None) -> list[tuple[str, bool]]:
    """(option name, needs a value) for every free-text option of a block type (fix round 1, finding 4):
    every string option whose maxLength is above TITLE_MAX, plus the common commentary."""
    found = {"commentary": False}
    for name, required in KNOWN_FREE_TEXT.get(type_id, ()):
        found[name] = required
    schema = (block_type or {}).get("options_schema") or {}
    for name, prop in (schema.get("properties") or {}).items():
        if isinstance(prop, dict) and prop.get("type") == "string" and (prop.get("maxLength") or 0) > TITLE_MAX:
            found[name] = (prop.get("minLength") or 0) > 0
    return list(found.items())


def from_layout(layout: dict, block_types, keep_text: bool = False) -> Preset:
    """A layout's structure as a preset (R-V1.7, R-V1.9): references stripped, every free text (free text,
    chapter intro, commentary, any long text option of a plugin block) becomes the placeholder or empty
    unless kept, the coverage map left behind. Titles, cover title and subtitle stay."""
    types = _types(block_types)
    blocks = []
    for b in layout["blocks"]:
        options = copy.deepcopy(b.get("options") or {})
        t = types.get(b["block_type"])
        if t is not None:
            options = _without_references(options, t)
        if not keep_text:
            for name, required in _free_text_options(b["block_type"], t):
                if name in options:
                    options[name] = PLACEHOLDER if required else ""
        blocks.append({"block_type": b["block_type"], "options": options})
    return Preset(id=None, name=layout["name"], description=layout.get("description") or "",
                  language=layout.get("language") or "en", toc=layout.get("toc") or "auto",
                  numbering=bool(layout.get("numbering")), blocks=blocks)


def export_doc(p: Preset) -> dict:
    """The preset file (R-V1.7)."""
    return {"format": FILE_FORMAT, "version": FILE_VERSION, "name": p.name, "description": p.description,
            "language": p.language or "en", "toc": p.toc or "auto", "numbering": bool(p.numbering),
            "blocks": [{"block_type": b["block_type"], "options": copy.deepcopy(b["options"])} for b in p.blocks]}


def copy_name(name: str, taken: set[str]) -> str:
    """"{name} (copy)", then "{name} (copy 2)" and so on until free, at most 120 characters (R-V1.6)."""
    n = 1
    while True:
        suffix = " (copy)" if n == 1 else f" (copy {n})"
        candidate = name[: NAME_MAX - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1


def checked_name(value) -> str:
    """A preset or layout name of 1 to 120 characters, or 422 invalid_request."""
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > NAME_MAX:
        raise ApiError(422, "invalid_request", f"The name must be 1 to {NAME_MAX} characters.",
                       [{"pointer": "/name", "message": "is not valid"}])
    return value.strip()
