"""Which options of a block hold prose written for one project (report run v2, part 2: R2-D3.7.3 to
R2-D3.7.5, R2-D3.8.3). Pure functions, no I/O.

The rule walks a block type's options schema (as GET /v1/block-types returns it) through `properties`,
`additionalProperties`, `items`, `prefixItems` and the `oneOf` / `anyOf` / `allOf` branches. A string leaf
(`type` "string" or a list holding "string") is prose when it carries `x-aisc-prose: true`, or when it
carries no `x-aisc-prose`, lies under no `x-aisc-prose: false` or `x-aisc-reference`, and has none of
`enum`, `const`, `pattern`, `format` or a `maxLength` of 300 or less. A block type the renderer does not
describe keeps the fixed list: commentary, free_text.text and chapter.intro.

Presets drop prose unless texts are kept (`strip_options`), and the editor flags options that still hold
the placeholder (`unwritten`, `unwritten_hint`).
"""
from __future__ import annotations

import copy

from jsonschema import Draft202012Validator

PLACEHOLDER = "Write this section."
#: the prose options known without a schema: name -> needs a value
FIXED_COMMON = {"commentary": False}
FIXED = {"free_text": {"text": True}, "chapter": {"intro": False}}
#: options the renderer leaves out of the report while they hold the placeholder (R2-D3.8.1)
LEFT_OUT = {"commentary", ("free_text", "text"), ("chapter", "intro")}
TITLE_MAX = 300
CONSTRAINTS = ("enum", "const", "pattern", "format")
HINT_LEFT_OUT = "Not written yet: this text still holds the placeholder and is left out of the report."
HINT = "Not written yet: this text still holds the placeholder."


def is_string(node) -> bool:
    kind = node.get("type") if isinstance(node, dict) else None
    return kind == "string" or (isinstance(kind, list) and "string" in kind)


def _blocks_below(node, blocked: bool) -> bool:
    """True below a node marked `x-aisc-prose: false` or `x-aisc-reference`."""
    return blocked or node.get("x-aisc-prose") is False or bool(node.get("x-aisc-reference"))


def is_prose(node, blocked: bool = False) -> bool:
    """A string leaf that holds prose (rule of the module docstring)."""
    if not is_string(node) or _blocks_below(node, blocked):
        return False
    if node.get("x-aisc-prose") is True:
        return True
    if "x-aisc-prose" in node or any(k in node for k in CONSTRAINTS):
        return False
    max_len = node.get("maxLength")
    return not (isinstance(max_len, int) and max_len <= TITLE_MAX)


def _is_null(node) -> bool:
    kind = node.get("type") if isinstance(node, dict) else None
    return kind == "null" or (isinstance(kind, list) and "null" in kind)


def _placeholder(node) -> str:
    max_len = node.get("maxLength")
    return PLACEHOLDER[:max_len] if isinstance(max_len, int) else PLACEHOLDER


def _leaf_blank(node, *, required: bool, nullable: bool):
    if required or (node.get("minLength") or 0) >= 1:
        return _placeholder(node)
    if nullable or _is_null(node):
        return None
    return ""


def _matching(value, branches) -> list:
    out = []
    for b in branches:
        try:
            if isinstance(b, dict) and Draft202012Validator(b).is_valid(value):
                out.append(b)
        except Exception:  # noqa: BLE001 - a schema we cannot use decides nothing
            continue
    return out


def _choice(value, node, blocked):
    """For a oneOf / anyOf node: ("leaf", branch, nullable), ("walk", branch) or None (leave as it is)."""
    branches = node.get("oneOf") or node.get("anyOf") or []
    found = _matching(value, branches)
    if not found:
        return None
    if all(is_prose(b, blocked) for b in found):
        return "leaf", found[0], any(_is_null(b) for b in branches)
    if len(found) == 1 and not is_string(found[0]):
        return "walk", found[0]
    return None


def blank(value, node, *, required: bool = False, blocked: bool = False, nullable: bool = False):
    """`value` with every prose string it holds replaced (R2-D3.7.4); a value of another shape stays."""
    if not isinstance(node, dict):
        return value
    blocked_here = _blocks_below(node, blocked)
    if node.get("oneOf") or node.get("anyOf"):
        choice = _choice(value, node, blocked_here)
        if choice is None:
            return value
        if choice[0] == "leaf":
            return _leaf_blank(choice[1], required=required, nullable=choice[2]) if isinstance(value, str) else value
        return blank(value, choice[1], required=required, blocked=blocked_here)
    if node.get("allOf"):
        typed = next((b for b in node["allOf"] if isinstance(b, dict) and "type" in b), None)
        return blank(value, typed, required=required, blocked=blocked_here) if typed else value
    if is_string(node):
        if isinstance(value, str) and is_prose(node, blocked):
            return _leaf_blank(node, required=required, nullable=nullable)
        return value
    if isinstance(value, dict) and ("properties" in node or isinstance(node.get("additionalProperties"), dict)):
        props = node.get("properties") or {}
        extra = node.get("additionalProperties") if isinstance(node.get("additionalProperties"), dict) else None
        needed = set(node.get("required") or ())
        return {k: blank(v, props.get(k, extra), required=k in needed, blocked=blocked_here) for k, v in value.items()}
    if isinstance(value, list) and ("items" in node or "prefixItems" in node):
        prefix = node.get("prefixItems") or []
        items = node.get("items") if isinstance(node.get("items"), dict) else None
        if not prefix and items is not None and is_prose(items, blocked_here):
            return [_placeholder(items)] * (node.get("minItems") or 0)
        return [blank(v, prefix[i] if i < len(prefix) else items, blocked=blocked_here) for i, v in enumerate(value)]
    return value


def _prose_texts(value, node, blocked: bool = False):
    """Every string held at a prose leaf of `value` (same walk as `blank`)."""
    if not isinstance(node, dict):
        return
    blocked_here = _blocks_below(node, blocked)
    if node.get("oneOf") or node.get("anyOf"):
        choice = _choice(value, node, blocked_here)
        if choice is not None and choice[0] == "leaf" and isinstance(value, str):
            yield value
        elif choice is not None and choice[0] == "walk":
            yield from _prose_texts(value, choice[1], blocked_here)
        return
    if node.get("allOf"):
        typed = next((b for b in node["allOf"] if isinstance(b, dict) and "type" in b), None)
        yield from _prose_texts(value, typed, blocked_here)
        return
    if is_string(node):
        if isinstance(value, str) and is_prose(node, blocked):
            yield value
        return
    if isinstance(value, dict):
        props = node.get("properties") or {}
        extra = node.get("additionalProperties") if isinstance(node.get("additionalProperties"), dict) else None
        for k, v in value.items():
            yield from _prose_texts(v, props.get(k, extra), blocked_here)
    elif isinstance(value, list):
        prefix = node.get("prefixItems") or []
        items = node.get("items") if isinstance(node.get("items"), dict) else None
        for i, v in enumerate(value):
            yield from _prose_texts(v, prefix[i] if i < len(prefix) else items, blocked_here)


def _fixed(type_id: str) -> dict:
    return {**FIXED.get(type_id, {}), **FIXED_COMMON}


def strip_options(type_id: str, options: dict, block_type: dict | None) -> dict:
    """The options of one block with every prose value replaced (placeholder, null or "") for a preset
    whose texts are not kept. Titles, identifiers and references stay (references are reset elsewhere)."""
    out = copy.deepcopy(options)
    schema = (block_type or {}).get("options_schema") or {}
    props = schema.get("properties") or {}
    needed = set(schema.get("required") or ())
    for name, fixed_required in _fixed(type_id).items():
        if name in out and name not in props:
            out[name] = PLACEHOLDER if fixed_required else ""
    for name in list(out):
        if name in props:
            out[name] = blank(out[name], props[name], required=name in needed)
    return out


def is_placeholder(text) -> bool:
    return isinstance(text, str) and text.strip() == PLACEHOLDER


_is_placeholder = is_placeholder


def unwritten(type_id: str, options: dict, block_type: dict | None) -> list[str]:
    """Top-level option names that still hold the placeholder at a prose leaf, in schema order."""
    options = options or {}
    props = ((block_type or {}).get("options_schema") or {}).get("properties") or {}
    names = [n for n in props if n in options and any(_is_placeholder(s) for s in _prose_texts(options[n], props[n]))]
    names += [n for n in _fixed(type_id) if n in options and n not in props and _is_placeholder(options[n])]
    return names


def unwritten_hint(type_id: str, names) -> str | None:
    """The editor's hint for a block with unwritten options, or None when every text is written."""
    if not names:
        return None
    left_out = all(n in LEFT_OUT or (type_id, n) in LEFT_OUT for n in names)
    return HINT_LEFT_OUT if left_out else HINT
