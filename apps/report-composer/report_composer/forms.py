"""The configure form of a block, from its options schema (report run 2026-09-23, R4.2.2).

Python decides every field; the page only draws what this returns.
"""
from __future__ import annotations


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


def _is_all_or_list(prop: dict) -> bool:
    alts = prop.get("oneOf") or prop.get("anyOf") or []
    return any(a.get("const") == "all" for a in alts) and any(a.get("type") == "array" for a in alts)


def _array_of(prop: dict) -> dict:
    for a in prop.get("oneOf") or prop.get("anyOf") or []:
        if a.get("type") == "array":
            return a.get("items") or {}
    return prop.get("items") or {}


def form_fields(options_schema, values, choices) -> list[dict]:
    required = set(options_schema.get("required", []))
    values = values or {}
    choices = choices or {}
    fields = []
    for name, prop in (options_schema.get("properties") or {}).items():
        field = {"name": name, "label": _label(name), "widget": "text", "kind": "str", "value": values.get(name),
                 "required": name in required, "min": prop.get("minimum"), "max": prop.get("maximum"),
                 "options": [], "reference": bool(prop.get("x-aisc-reference"))}
        items = prop.get("items") or {}
        if prop.get("type") == "array" and items.get("type") == "object":
            field.update(widget="links", kind="links",
                         options={k: choices.get(f"{name}.{k}", []) for k in (items.get("properties") or {})})
        elif _is_all_or_list(prop):
            enum = _array_of(prop).get("enum")
            field.update(widget="multiselect", kind="all-or-list",
                         options=choices.get(name) or [{"value": v, "label": str(v)} for v in enum or []])
        elif prop.get("type") == "array":
            enum = items.get("enum")
            if enum:
                field.update(widget="multiselect", kind="list", options=[{"value": v, "label": str(v)} for v in enum])
            else:
                field.update(widget="list", kind="list")
        elif name in choices:
            field.update(widget="select", kind="int" if prop.get("type") == "integer" else "str",
                         options=list(choices[name]))
        elif "enum" in prop:
            field.update(widget="select", kind="enum", options=[{"value": v, "label": str(v)} for v in prop["enum"]])
        elif prop.get("type") == "boolean":
            field.update(widget="checkbox", kind="bool")
        elif prop.get("type") in ("integer", "number"):
            field.update(widget="number", kind="int")
        elif prop.get("type") == "string" and (prop.get("maxLength") or 0) > 300:
            field.update(widget="textarea", kind="str")
        fields.append(field)
    return fields
