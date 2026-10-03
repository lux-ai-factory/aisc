"""Layouts in Python.

A layout is an ordered list of blocks {instance_id, block_type, options}. Block types, their
options schemas and the values a data reference may take come from the renderer; this module
decides what a layout may hold. A template is a layout without project data.
"""
from __future__ import annotations

import copy
import uuid

from jsonschema import Draft202012Validator

from . import prose

DEFAULT_ORDER = ["cover", "ai_card", "risk_classification", "control_objectives", "test_results",
                 "control_answers", "summary_coverage"]
MAX_BLOCKS, MAX_CHARTS = 50, 10


def _new_id() -> str:
    return str(uuid.uuid4())


def default_blocks(block_types) -> list[dict]:
    """The block types of DEFAULT_ORDER the renderer offers, with their default options."""
    by_type = {t["type_id"]: t for t in block_types}
    return [{"instance_id": _new_id(), "block_type": t, "options": copy.deepcopy(by_type[t]["default_options"])}
            for t in DEFAULT_ORDER if t in by_type]


def reference_options(block_type: dict) -> list[str]:
    """The options that name data of a project (marked `x-aisc-reference` in the schema)."""
    props = (block_type.get("options_schema") or {}).get("properties") or {}
    return [name for name, prop in props.items() if isinstance(prop, dict) and prop.get("x-aisc-reference")]


def _problem(instance_id, code, pointer, message) -> dict:
    return {"instance_id": instance_id, "code": code, "pointer": pointer, "message": message}


def _pointer(path) -> str:
    return "".join("/" + str(p) for p in path)


def _message(err) -> str:
    v = err.validator_value
    messages = {
        "maximum": f"must be at most {v}", "minimum": f"must be at least {v}",
        "maxLength": f"must be at most {v} characters", "minLength": f"must be at least {v} characters",
        "type": f"must be of type {v}", "required": "is required",
        "additionalProperties": "is not an option of this block", "oneOf": "is not a valid value",
        "anyOf": "is not a valid value", "const": "is not a valid value",
    }
    if err.validator == "enum":
        return "must be one of " + ", ".join(str(x) for x in v)
    return messages.get(err.validator, err.message[:200])


def _option_problems(schema: dict, options: dict, iid, drop_required: set[str], refs=()) -> list[dict]:
    out = []
    seen = set()
    for err in sorted(Draft202012Validator(schema).iter_errors(options), key=lambda e: [str(p) for p in e.path]):
        if err.validator == "required":
            present = err.instance if isinstance(err.instance, dict) else {}
            for name in err.validator_value:
                if name in present or (not err.path and name in drop_required):
                    continue
                pointer = _pointer(err.path) + "/" + name
                if pointer in seen:
                    continue
                seen.add(pointer)
                message = CHOOSE_A_VALUE if (not err.path and name in refs) else "is required"
                out.append(_problem(iid, "invalid_options", pointer, message))
            continue
        out.append(_problem(iid, "invalid_options", _pointer(err.path), _message(err)))
    props = schema.get("properties") or {}
    for name, prop in props.items():
        if isinstance(prop, dict) and is_all_or_list(prop) and options.get(name) == []:
            out.append(_problem(iid, "invalid_options", f"/{name}", PICK_ONE))
    return out


PICK_ONE = "Pick at least one, or choose All."
CHOOSE_A_VALUE = "Choose a value"


def _allowed(choices: dict, key: str) -> list:
    """The values a reference may take (a list: dict values are not hashable)."""
    return [c.get("value") for c in choices.get(key) or []]


def is_all_or_list(prop: dict) -> bool:
    """An option that is "all" or a list (a oneOf/anyOf of const "all" and an array)."""
    alts = (prop or {}).get("oneOf") or (prop or {}).get("anyOf") or []
    return any(isinstance(a, dict) and a.get("const") == "all" for a in alts) and \
        any(isinstance(a, dict) and a.get("type") == "array" for a in alts)


def _reference_problems(name, value, choices: dict, iid, default=None) -> list[dict]:
    if value is None or value == "all" or value == [] or (default is not None and value == default):
        return []
    out = []
    bad = "is not available for this project and version"
    if isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, dict) and name in choices:
                if item not in _allowed(choices, name):
                    out.append(_problem(iid, "invalid_reference", f"/{name}/{i}", bad))
            elif isinstance(item, dict):
                # a per-field check (the Summary block's links): only where the renderer offers the field's choices
                for field, v in item.items():
                    key = f"{name}.{field}"
                    if key not in choices:
                        continue
                    allowed = _allowed(choices, key)
                    if isinstance(v, list):
                        for j, x in enumerate(v):
                            if x not in allowed:
                                out.append(_problem(iid, "invalid_reference", f"/{name}/{i}/{field}/{j}", bad))
                    elif v is not None and v not in allowed:
                        out.append(_problem(iid, "invalid_reference", f"/{name}/{i}/{field}", bad))
            elif item not in _allowed(choices, name):
                out.append(_problem(iid, "invalid_reference", f"/{name}/{i}", bad))
    elif value not in _allowed(choices, name):
        out.append(_problem(iid, "invalid_reference", f"/{name}", bad))
    return out


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return isinstance(value, str)
    except (ValueError, TypeError, AttributeError):
        return False


def _layout_problems(blocks) -> list[dict]:
    """What is wrong with the layout as a whole: too many blocks or charts, more than one cover or appendix."""
    problems = []
    if len(blocks) > MAX_BLOCKS:
        problems.append(_problem(None, "too_many_blocks", "", f"a layout holds at most {MAX_BLOCKS} blocks"))
    if sum(1 for b in blocks if isinstance(b, dict) and b.get("block_type") == "dashboard_chart") > MAX_CHARTS:
        problems.append(_problem(None, "too_many_blocks", "", f"a layout holds at most {MAX_CHARTS} charts"))
    covers = [b for b in blocks if isinstance(b, dict) and b.get("block_type") == "cover"]
    if len(covers) > 1:
        problems.append(_problem(covers[1].get("instance_id"), "duplicate_cover", "", "a layout has one cover at most"))
    appendices = [b for b in blocks if isinstance(b, dict) and b.get("block_type") == "appendix"]
    if len(appendices) > 1:
        problems.append(_problem(appendices[1].get("instance_id"), "duplicate_appendix", "",
                                 "a layout has one appendix at most"))
    return problems


def _block_problems(b: dict, t: dict, choices_of, allow_missing_references: bool) -> list[dict]:
    """What is wrong with one block of a known type: its options first, then its references."""
    iid = b["instance_id"]
    options = b.get("options") if b.get("options") is not None else {}
    if not isinstance(options, dict):
        return [_problem(iid, "invalid_options", "", "must be an object")]
    merged = {**copy.deepcopy(t.get("default_options") or {}), **options}
    refs = reference_options(t)
    found = _option_problems(t["options_schema"], merged, iid, set(refs) if allow_missing_references else set(),
                             refs)
    if found or not refs or choices_of is None:      # no choices: the shape only
        return found
    allowed = choices_of(t["type_id"])
    defaults = t.get("default_options") or {}
    return [p for name in refs
            for p in _reference_problems(name, merged.get(name), allowed, iid, defaults.get(name))]


def validate_layout(blocks, *, block_types, choices, allow_missing_references=False) -> list[dict]:
    """Problems of a layout, layout-level first, as [{instance_id, code, pointer, message}].

    `choices(block_type)` answers the values each reference option may take (called at most once
    per block type, and only for a block whose options are otherwise valid); `choices=None` checks the
    shape only, as a layout is saved without a version.
    """
    types = {t["type_id"]: t for t in block_types}
    problems = _layout_problems(blocks)
    seen: set = set()
    cache: dict = {}

    def choices_of(type_id):
        if type_id not in cache:
            cache[type_id] = choices(type_id) or {}
        return cache[type_id]

    for b in blocks:
        if not isinstance(b, dict) or not _is_uuid(b.get("instance_id")):
            problems.append(_problem(b.get("instance_id") if isinstance(b, dict) else None, "invalid_block",
                                     "/instance_id", "a block needs a UUID instance id"))
            continue
        iid = b["instance_id"]
        if iid in seen:
            problems.append(_problem(iid, "duplicate_instance_id", "/instance_id", "is used by another block"))
            continue
        seen.add(iid)
        t = types.get(b.get("block_type"))
        if t is None:
            problems.append(_problem(iid, "unknown_block_type", "/block_type",
                                     f"the block type {b.get('block_type')!r} is not available"))
            continue
        problems.extend(_block_problems(b, t, choices_of if choices is not None else None, allow_missing_references))
    return problems


def _reset(options: dict, name: str, block_type: dict) -> None:
    defaults = block_type.get("default_options") or {}
    if name in defaults:
        options[name] = copy.deepcopy(defaults[name])
    else:
        options.pop(name, None)


def reset_invalid(blocks, problems, block_types) -> list[dict]:
    """Every option with an invalid reference goes back to its default (or away without one)."""
    types = {t["type_id"]: t for t in block_types}
    out = copy.deepcopy(list(blocks))
    by_id = {b["instance_id"]: b for b in out if isinstance(b, dict)}
    for p in problems:
        if p["code"] != "invalid_reference" or p["instance_id"] not in by_id:
            continue
        b = by_id[p["instance_id"]]
        t = types.get(b["block_type"])
        name = p["pointer"].split("/")[1] if p["pointer"].count("/") >= 1 else ""
        if t is not None and name:
            b.setdefault("options", {})
            _reset(b["options"], name, t)
    return out


CONTENT_EXCLUDED = ("cover", "chapter", "appendix")


def outline_depths(blocks: list[dict]) -> list[tuple[int, bool]]:
    """(depth, empty chapter) per block: 1 after a chapter until the next chapter or appendix, and
    whether a chapter holds no content block. Computed from the order; nothing is stored."""
    out = []
    inside = False
    for i, b in enumerate(blocks):
        t = b["block_type"]
        if t == "chapter":
            rest = blocks[i + 1:]
            end = next((j for j, r in enumerate(rest) if r["block_type"] in ("chapter", "appendix")), len(rest))
            empty = not any(r["block_type"] not in CONTENT_EXCLUDED for r in rest[:end])
            out.append((0, empty))
            inside = True
        elif t == "appendix":
            out.append((0, False))
            inside = False
        else:
            out.append((1 if inside and t != "cover" else 0, False))
    return out


def _letters(n: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA, as the renderer labels the appendix."""
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def outline_numbers(blocks: list[dict], numbering: bool = False) -> list[str]:
    """The report's section number per block ("" for none), so the editor shows what the report prints:
    the renderer's structure.plan rule (chapters 1, 2, their blocks 1.1, 1.2, the appendix A, B; no number
    for the cover or the appendix heading). An unwritten free text is left out of the report and takes no
    number (the renderer's document.py). Nothing is numbered when numbering is off."""
    out = []
    top = sub = 0
    in_appendix, chapter = False, None
    for b in blocks:
        t = b["block_type"]
        options = b.get("options") if isinstance(b.get("options"), dict) else {}
        if not numbering or t == "cover" or (t == "free_text" and prose.is_placeholder(options.get("text"))):
            out.append("")
        elif t == "appendix":
            in_appendix, top, chapter = True, 0, None
            out.append("")
        elif t == "chapter":
            top, sub = top + 1, 0
            chapter = _letters(top) if in_appendix else str(top)
            out.append(chapter)
        elif chapter is not None:
            sub += 1
            out.append(f"{chapter}.{sub}")
        else:
            top += 1
            out.append(_letters(top) if in_appendix else str(top))
    return out


def outline(blocks: list[dict], block_types=(), numbering: bool = False) -> list[dict]:
    """The editor's outline for any block order: {instance_id, depth, empty_chapter, unwritten, unwritten_hint,
    number} per block; the editor redraws indentation, hints and numbers from this after a move or an
    edit. `unwritten` names the options still holding the placeholder; a block type the
    renderer does not describe uses the fixed list."""
    by_type = {t["type_id"]: t for t in block_types or ()}
    out = []
    for b, (depth, empty), number in zip(blocks, outline_depths(blocks), outline_numbers(blocks, numbering)):
        options = b.get("options") if isinstance(b.get("options"), dict) else {}
        names = prose.unwritten(b["block_type"], options, by_type.get(b["block_type"]))
        out.append({"instance_id": b.get("instance_id"), "depth": depth, "empty_chapter": empty,
                    "unwritten": names, "unwritten_hint": prose.unwritten_hint(b["block_type"], names),
                    "number": number})
    return out
