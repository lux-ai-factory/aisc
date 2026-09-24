"""The configure form of a block, from its options schema.

Python decides every field; the page only draws what this returns. Report run v2: labels and help
come from the schema's `title` and `description` (R-U5.3), enum values from `x-aisc-enum-labels`,
options marked `x-aisc-more` go under "More options" after the main ones (R-U5.4), options with
`x-aisc-show-if` are hidden while the named option has another value (R-V4.15), "all or a list"
options are radios and checkboxes (R-U4.2), enum lists are checkbox lists (R-U4.4), and the
commentary has a field of its own (R-V3.13). A block without annotations keeps today's generated
labels, all main (R-U5.5).
"""
from __future__ import annotations

from .layouts import is_all_or_list

#: the help line under every textarea that takes light formatting (R-V3.15)
LIGHT_FORMATTING_HELP = ("Light formatting: **bold**, *italic*, lists with - or 1., links [text](https://...),"
                         " tables with |.")
FILTER_ABOVE = 10
NULLABLE_SELECT_MAX = 10


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _array_of(prop: dict) -> dict:
    for a in prop.get("oneOf") or prop.get("anyOf") or []:
        if a.get("type") == "array":
            return a.get("items") or {}
    return prop.get("items") or {}


def _enum_options(values, labels=None) -> list[dict]:
    labels = labels or {}
    return [{"value": v, "label": labels.get(v, str(v)) if isinstance(v, str) else str(v)} for v in values]


def _types(prop: dict) -> list:
    t = prop.get("type")
    return t if isinstance(t, list) else [t]


def _hidden(show_if, values: dict) -> bool:
    if not isinstance(show_if, dict):
        return False
    return any(values.get(option) not in (allowed or []) for option, allowed in show_if.items())


def _field(name: str, prop: dict, values: dict, choices: dict, required: set) -> dict | None:
    value = values.get(name)
    show_if = prop.get("x-aisc-show-if") if isinstance(prop.get("x-aisc-show-if"), dict) else None
    field = {"name": name, "label": prop.get("title") or _label(name), "help": prop.get("description") or "",
             "more": bool(prop.get("x-aisc-more")) and name != "commentary", "show_if": show_if,
             "hidden": _hidden(show_if, values), "filter": False, "light": False,
             "widget": "text", "kind": "str", "value": value, "required": name in required,
             "min": prop.get("minimum"), "max": prop.get("maximum"), "options": [],
             "reference": bool(prop.get("x-aisc-reference"))}
    labels = prop.get("x-aisc-enum-labels") or {}
    items = prop.get("items") or {}
    types = _types(prop)
    if name == "commentary":
        field.update(widget="commentary", kind="str", light=True)
    elif "array" in types and items.get("type") == "object":
        # the Summary block's own links, from before the coverage map: shown read only (R-U2.6)
        if not value:
            return None
        field.update(widget="legacy-links", kind="json", options=list(value))
    elif is_all_or_list(prop):
        inner = _array_of(prop)
        options = list(choices.get(name) or _enum_options(inner.get("enum") or [],
                                                          inner.get("x-aisc-enum-labels") or labels))
        field.update(widget="all-or-list", kind="all-or-list", options=options, filter=len(options) > FILTER_ABOVE)
    elif "array" in types:
        enum = items.get("enum")
        if enum:
            field.update(widget="checkboxes", kind="list",
                         options=_enum_options(enum, items.get("x-aisc-enum-labels") or labels))
        else:
            field.update(widget="list", kind="list")
    elif name in choices:
        options = list(choices[name])
        kind = "int" if "integer" in types else ("json" if any(isinstance(o.get("value"), dict) for o in options)
                                                or "object" in types else "str")
        field.update(widget="select", kind=kind, options=options)
    elif "integer" in types and "null" in types and prop.get("minimum") is not None \
            and prop.get("maximum") is not None and prop["maximum"] - prop["minimum"] < NULLABLE_SELECT_MAX:
        options = [{"value": "", "label": prop.get("x-aisc-null-label") or ""}] + \
            [{"value": n, "label": str(n)} for n in range(int(prop["minimum"]), int(prop["maximum"]) + 1)]
        field.update(widget="select", kind="int-or-null", options=options)
    elif "enum" in prop:
        field.update(widget="select", kind="enum", options=_enum_options(prop["enum"], labels))
    elif "boolean" in types:
        field.update(widget="checkbox", kind="bool")
    elif "integer" in types or "number" in types:
        field.update(widget="number", kind="int")
    elif "string" in types and (prop.get("maxLength") or 0) > 300:
        field.update(widget="textarea", kind="str", light=values.get("format") == "markdown")
    return field


def form_fields(options_schema, values, choices) -> list[dict]:
    """The fields of a block's form: main fields in schema order, then the "More options" fields."""
    required = set(options_schema.get("required", []))
    values = values or {}
    choices = choices or {}
    fields = []
    for name, prop in (options_schema.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        field = _field(name, prop, values, choices, required)
        if field is not None:
            fields.append(field)
    return [f for f in fields if not f["more"]] + [f for f in fields if f["more"]]
