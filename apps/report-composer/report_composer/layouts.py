"""Layouts in Python.

A layout is an ordered list of blocks {instance_id, block_type, options}. Block types, their
options schemas and the values a data reference may take come from the renderer; this module
decides what a layout may hold. A template is a layout without project data.
"""
from __future__ import annotations

import copy
import uuid

from jsonschema import Draft202012Validator

DEFAULT_ORDER = ["cover", "ai_card", "risk_classification", "control_objectives", "test_results",
                 "control_answers", "summary_coverage"]
MAX_BLOCKS, MAX_CHARTS = 50, 10
FREE_TEXT_PLACEHOLDER = "[text]"


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


def _option_problems(schema: dict, options: dict, iid, drop_required: set[str]) -> list[dict]:
    out = []
    for err in sorted(Draft202012Validator(schema).iter_errors(options), key=lambda e: [str(p) for p in e.path]):
        if err.validator == "required":
            present = err.instance if isinstance(err.instance, dict) else {}
            for name in err.validator_value:
                if name in present or (not err.path and name in drop_required):
                    continue
                out.append(_problem(iid, "invalid_options", _pointer(err.path) + "/" + name, "is required"))
            continue
        out.append(_problem(iid, "invalid_options", _pointer(err.path), _message(err)))
    return out


def _allowed(choices: dict, key: str) -> set:
    return {c.get("value") for c in choices.get(key) or []}


def _reference_problems(name, value, choices: dict, iid) -> list[dict]:
    if value is None or value == "all" or value == []:
        return []
    out = []
    bad = "is not available for this project and version"
    if isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, dict):
                for field, v in item.items():
                    key = f"{name}.{field}"
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


def validate_layout(blocks, *, block_types, choices, allow_missing_references=False) -> list[dict]:
    """Problems of a layout, layout-level first, as [{instance_id, code, pointer, message}].

    `choices(block_type)` answers the values each reference option may take (called at most once
    per block type, and only for a block whose options are otherwise valid).
    """
    types = {t["type_id"]: t for t in block_types}
    problems: list[dict] = []
    if len(blocks) > MAX_BLOCKS:
        problems.append(_problem(None, "too_many_blocks", "", f"a layout holds at most {MAX_BLOCKS} blocks"))
    if sum(1 for b in blocks if isinstance(b, dict) and b.get("block_type") == "dashboard_chart") > MAX_CHARTS:
        problems.append(_problem(None, "too_many_blocks", "", f"a layout holds at most {MAX_CHARTS} charts"))
    covers = [b for b in blocks if isinstance(b, dict) and b.get("block_type") == "cover"]
    if len(covers) > 1:
        problems.append(_problem(covers[1].get("instance_id"), "duplicate_cover", "", "a layout has one cover at most"))
    seen: set = set()
    cache: dict = {}
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
        options = b.get("options") if b.get("options") is not None else {}
        if not isinstance(options, dict):
            problems.append(_problem(iid, "invalid_options", "", "must be an object"))
            continue
        merged = {**copy.deepcopy(t.get("default_options") or {}), **options}
        refs = reference_options(t)
        found = _option_problems(t["options_schema"], merged, iid, set(refs) if allow_missing_references else set())
        if found:
            problems.extend(found)
            continue
        if not refs:
            continue
        if t["type_id"] not in cache:
            cache[t["type_id"]] = choices(t["type_id"]) or {}
        for name in refs:
            problems.extend(_reference_problems(name, merged.get(name), cache[t["type_id"]], iid))
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
