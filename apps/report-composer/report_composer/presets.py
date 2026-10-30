"""Layout files: report structures without project data.

A file is an ordered list of {block_type, options} plus the document settings show_index (version 1:
toc) and numbering (reports are English only; a `language` in a file is ignored). It carries a structure
to another project or platform; a layout made from it keeps no link to it. The built-in layouts are the
files of report_composer/presets/ (builtin_layouts.py).
"""
from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import layouts, prose
from .errors import ApiError

DIRECTORY = Path(__file__).resolve().parent / "presets"
FILE_FORMAT = "aisc-report-preset"
#: the version written; version 1 files (with toc auto/on/off, a language, run ids) are still read
FILE_VERSION = 2
READ_VERSIONS = (1, 2)
#: options that named one run or one version, which a layout does not hold:
#: (block type, option) -> the value that replaces it, or DROP
DROP = object()
RETIRED_OPTIONS = {("test_results", "evaluations"): DROP, ("changes_since", "compare_to"): "previous"}
MAX_BLOCKS = 50
NAME_MAX = 120


@dataclass
class Preset:
    name: str
    description: str = ""
    show_index: bool | None = None
    numbering: bool | None = None
    blocks: list = field(default_factory=list)
    #: (block index, option, label) of every reference a preset file held and that was reset;
    #: neither exported nor stored
    reset: list = field(default_factory=list)


def _types(block_types) -> dict:
    return {t["type_id"]: t for t in block_types}


def unknown_types_problem(blocks, block_types) -> None:
    """422 unknown_block_type naming every block type the renderer does not offer."""
    types = _types(block_types)
    unknown = []
    for b in blocks:
        name = b.get("block_type") if isinstance(b, dict) else None
        if name not in types and name not in unknown:
            unknown.append(name)
    if unknown:
        raise ApiError(422, "unknown_block_type",
                       "This file uses sections this installation does not offer: "
                       + ", ".join(str(u) for u in unknown) + ".",
                       [{"pointer": "/blocks", "block_type": u, "message": f"the section type {u!r} is not available"}
                        for u in unknown])


def _without_references(options: dict, block_type: dict) -> dict:
    """Options with every data reference set to its type default, or left out."""
    out = copy.deepcopy(options)
    defaults = block_type.get("default_options") or {}
    for name in layouts.reference_options(block_type):
        if name in defaults:
            out[name] = copy.deepcopy(defaults[name])
        else:
            out.pop(name, None)
    return out


def reset_references(blocks, block_types) -> tuple[list[dict], list[tuple[int, str, str]]]:
    """The blocks of a preset file with every reference option reset (file options only, no
    defaults merged), and (i, option, label) for each reference whose value in the file was changed."""
    types = _types(block_types)
    out, changed = [], []
    for i, b in enumerate(blocks):
        options = dict(b.get("options") or {})
        t = types.get(b["block_type"])
        if t is not None:
            kept = _without_references(options, t)
            props = (t.get("options_schema") or {}).get("properties") or {}
            for name in layouts.reference_options(t):
                if name in options and (name not in kept or kept[name] != options[name]):
                    changed.append((i, name, props[name].get("title") or name))
            options = kept
        out.append({"block_type": b["block_type"], "options": options})
    return out, changed


def reference_notices(changed, where: str) -> list[dict]:
    """One notice per reset reference; `where` says whose data it pointed at."""
    return [{"pointer": f"/blocks/{i}/{option}",
             "message": f"The {label} of section {i + 1} pointed at {where}; it was reset to its default."}
            for i, option, label in changed]


def _show_index(doc: dict) -> bool | None:
    """A file's index setting: `show_index` (version 2), or version 1's toc (off is no index)."""
    if isinstance(doc.get("show_index"), bool):
        return doc["show_index"]
    if doc.get("toc") in ("auto", "on", "off"):
        return doc["toc"] != "off"
    return None


def retire_options(blocks, block_types=()) -> tuple[list[dict], list[tuple[int, str, str]]]:
    """Blocks without the options that named one run or one version, and (i, option, label) for each
    one that was dropped or put back to "previous". The label is the option's
    title in the block type's schema when it has one."""
    fallback = {"evaluations": "Evaluations", "compare_to": "Compare with"}
    types = _types(block_types)

    def label(type_id, name):
        props = ((types.get(type_id) or {}).get("options_schema") or {}).get("properties") or {}
        return (props.get(name) or {}).get("title") or fallback[name]

    out, changed = [], []
    for i, b in enumerate(blocks):
        options = dict(b.get("options") or {})
        for (type_id, name), value in RETIRED_OPTIONS.items():
            if b.get("block_type") != type_id or name not in options:
                continue
            if value is DROP:
                del options[name]
                changed.append((i, name, label(type_id, name)))
            elif options[name] != value:
                options[name] = value
                changed.append((i, name, label(type_id, name)))
        out.append({**b, "options": options})
    return out, changed


def from_file(doc, block_types) -> Preset:
    """A preset file checked: 422 not_a_preset, unknown_block_type, invalid_options or duplicate_cover.
    Its references are reset and listed in `reset`."""
    if not isinstance(doc, dict) or doc.get("format") != FILE_FORMAT or doc.get("version") not in READ_VERSIONS:
        raise ApiError(422, "not_a_preset", "This file is not a report preset.")
    blocks = doc.get("blocks")
    if not isinstance(blocks, list) or not all(isinstance(b, dict) and isinstance(b.get("options", {}), dict)
                                               for b in blocks):
        raise ApiError(422, "not_a_preset", "This file is not a report preset.",
                       [{"pointer": "/blocks", "message": "must be a list of blocks"}])
    if len(blocks) > MAX_BLOCKS:
        raise ApiError(422, "too_many_blocks", f"A preset holds at most {MAX_BLOCKS} sections.",
                       [{"pointer": "/blocks", "message": f"holds at most {MAX_BLOCKS} sections"}])
    unknown_types_problem(blocks, block_types)
    blocks, retired = retire_options(blocks, block_types)
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
    if _show_index(doc) is not None:
        settings["show_index"] = _show_index(doc)
    if isinstance(doc.get("numbering"), bool):
        settings["numbering"] = doc["numbering"]
    description = doc.get("description") if isinstance(doc.get("description"), str) else ""
    kept, changed = reset_references(blocks, block_types)
    return Preset(name=name.strip()[:NAME_MAX], description=description[:2000], blocks=kept,
                  reset=sorted(retired + changed, key=lambda c: c[0]), **settings)


def with_defaults(block: dict, block_types) -> dict:
    """A block's options merged over its type's defaults (the block's own when the type is unknown)."""
    t = _types(block_types).get(block["block_type"])
    return {**copy.deepcopy((t or {}).get("default_options") or {}), **copy.deepcopy(block.get("options") or {})}


def blocks_for_layout(preset: Preset, block_types) -> list[dict]:
    """The layout blocks of a preset: new instance ids, default options merged, references reset."""
    unknown_types_problem(preset.blocks, block_types)
    types = _types(block_types)
    return [{"instance_id": str(uuid.uuid4()), "block_type": b["block_type"],
             "options": _without_references(with_defaults(b, block_types), types[b["block_type"]])}
            for b in preset.blocks]


def from_layout(layout: dict, block_types, keep_text: bool = False) -> Preset:
    """A layout's structure as a preset: references stripped, every prose option (found from the block
    type's schema by prose.strip_options) becomes the placeholder, null or empty
    unless kept. Titles, cover title and subtitle stay."""
    types = _types(block_types)
    blocks = []
    for b in layout["blocks"]:
        options = copy.deepcopy(b.get("options") or {})
        t = types.get(b["block_type"])
        if t is not None:
            options = _without_references(options, t)
        if not keep_text:
            options = prose.strip_options(b["block_type"], options, t)
        blocks.append({"block_type": b["block_type"], "options": options})
    return Preset(name=layout["name"], description=layout.get("description") or "",
                  show_index=bool(layout.get("show_index", True)),
                  numbering=bool(layout.get("numbering", True)), blocks=blocks)


def export_doc(p: Preset) -> dict:
    """The preset file."""
    return {"format": FILE_FORMAT, "version": FILE_VERSION, "name": p.name, "description": p.description,
            "show_index": True if p.show_index is None else bool(p.show_index), "numbering": True if p.numbering is None else bool(p.numbering),
            "blocks": [{"block_type": b["block_type"], "options": copy.deepcopy(b["options"])} for b in p.blocks]}


def copy_name(name: str, taken: set[str]) -> str:
    """"{name} (copy)", then "{name} (copy 2)" and so on until free, at most 120 characters."""
    n = 1
    while True:
        suffix = " (copy)" if n == 1 else f" (copy {n})"
        candidate = name[: NAME_MAX - len(suffix)] + suffix
        if candidate not in taken:
            return candidate
        n += 1
