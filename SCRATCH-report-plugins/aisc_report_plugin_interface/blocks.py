"""The block-renderer contract.

A block type declares its id, title, contract version, options schema (JSON Schema draft
2020-12), default options and the sources it reads; it loads its data and renders an HTML
fragment. Every block also accepts the common options `title`, `page_break_before`, `commentary` and
`commentary_position`. Options may carry the composer annotations `title`,
`description`, `x-aisc-enum-labels`, `x-aisc-more`, `x-aisc-show-if`, `x-aisc-reference` and `x-aisc-prose`;
JSON Schema ignores them when validating. `x-aisc-prose` is true on a string option that holds prose written for
one project (dropped from presets unless texts are kept) and false on a name, id or other identifier.
"""
from __future__ import annotations

import copy
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from . import templating

SOURCES = ("platform", "qualification", "control_objectives", "engine", "controls", "superset")
STATUSES = ("ok", "empty", "stale", "error")
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

_SLUG = re.compile(r"^[a-z][a-z0-9_]*$")
_DOCUMENT_TAG = re.compile(r"<\s*(!doctype|html|body)\b", re.I)


class InvalidBlockType(ValueError):
    """A block type's declaration breaks the contract."""


@dataclass
class BlockResult:
    html: str
    status: str
    notices: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if _DOCUMENT_TAG.search(self.html or ""):
            raise ValueError("a block renders a fragment, not a document")


COMMON_PROPERTIES = {
    "title": {"type": "string", "minLength": 0, "maxLength": 200, "title": "Section title",
              "description": "Replaces the block's own heading.", "x-aisc-more": True},
    "page_break_before": {"type": "boolean", "title": "Start on a new page",
                          "description": "Starts this section on a new page in the PDF.", "x-aisc-more": True},
    "commentary": {"type": "string", "minLength": 0, "maxLength": 10000, "title": "Commentary",
                   "description": "Your own words about this section, printed with it.",
                   "x-aisc-prose": True},
    "commentary_position": {"enum": ["after", "before"], "title": "Place the commentary",
                            "description": "Where the commentary goes.",
                            "x-aisc-enum-labels": {"after": "After the section", "before": "Before the section"},
                            "x-aisc-more": True},
}
COMMON_DEFAULTS = {"title": "", "page_break_before": False, "commentary": "", "commentary_position": "after"}


def _message(err: jsonschema.ValidationError) -> str:
    v = err.validator_value
    if err.validator == "maximum":
        return f"must be at most {v}"
    if err.validator == "minimum":
        return f"must be at least {v}"
    if err.validator == "maxLength":
        return f"must be at most {v} characters"
    if err.validator == "minLength":
        return f"must be at least {v} characters"
    if err.validator == "enum":
        return "must be one of " + ", ".join(str(x) for x in v)
    if err.validator == "type":
        return f"must be of type {v}"
    if err.validator == "required":
        return "is required"
    if err.validator == "additionalProperties":
        return "is not an option of this block"
    if err.validator in ("oneOf", "anyOf"):
        return "is not a valid value"
    return err.message[:200]


def _pointer(path) -> str:
    return "".join("/" + str(p) for p in path)


def schema_problems(schema: dict, options: Any) -> list[dict]:
    """Problems of `options` against `schema`: [{pointer, message}], the value never echoed."""
    problems: list[dict] = []
    errors = sorted(Draft202012Validator(schema).iter_errors(options), key=lambda e: [str(p) for p in e.path])
    for err in errors:
        if err.validator == "required":
            present = err.instance if isinstance(err.instance, dict) else {}
            for name in err.validator_value:
                if name not in present:
                    problems.append({"pointer": _pointer(err.path) + "/" + name, "message": "is required"})
            continue
        if err.validator == "additionalProperties" and isinstance(err.instance, dict):
            allowed = set((err.schema or {}).get("properties", {}))
            extra = [k for k in err.instance if k not in allowed]
            if extra:
                for name in extra:
                    problems.append({"pointer": _pointer(err.path) + "/" + str(name),
                                     "message": "is not an option of this block"})
                continue
        problems.append({"pointer": _pointer(err.path), "message": _message(err)})
    return problems


class BaseBlockRenderer(ABC):
    type_id: str
    title: str
    contract_version: int
    options_schema: dict
    default_options: dict
    reads: tuple
    #: option names that choices() answers for
    choice_options: tuple[str, ...] = ()
    #: one sentence shown in the composer's palette
    description: str = ""
    #: options put on a block when the user adds it, on top of default_options; never mutated
    new_instance_options: dict = {}

    @abstractmethod
    def load(self, ctx, options):
        """Read what the block shows, for the pinned version only."""

    @abstractmethod
    def render(self, data, options, ctx):
        """Return a BlockResult."""

    def choices(self, ctx, option_name) -> list[dict]:
        return []

    @classmethod
    def validate_declaration(cls) -> None:
        type_id = getattr(cls, "type_id", None)
        if not isinstance(type_id, str) or not _SLUG.match(type_id):
            raise InvalidBlockType("type_id must be a lowercase slug")
        title = getattr(cls, "title", None)
        if not isinstance(title, str) or not title.strip():
            raise InvalidBlockType(f"{type_id}: title must be a non-empty string")
        version = getattr(cls, "contract_version", None)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise InvalidBlockType(f"{type_id}: contract_version must be an integer from 1")
        schema = getattr(cls, "options_schema", None)
        if not isinstance(schema, dict):
            raise InvalidBlockType(f"{type_id}: options_schema must be a JSON Schema object")
        try:
            Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise InvalidBlockType(f"{type_id}: options_schema is not a valid schema: {exc.message}") from None
        defaults = getattr(cls, "default_options", None)
        if not isinstance(defaults, dict):
            raise InvalidBlockType(f"{type_id}: default_options must be an object")
        relaxed = {k: v for k, v in schema.items() if k != "required"}
        if any(True for _ in Draft202012Validator(relaxed).iter_errors(defaults)):
            raise InvalidBlockType(f"{type_id}: default_options do not match options_schema")
        reads = getattr(cls, "reads", None)
        if not isinstance(reads, (tuple, list, set, frozenset)) or any(r not in SOURCES for r in reads):
            raise InvalidBlockType(f"{type_id}: reads must list sources of {', '.join(SOURCES)}")
        if not isinstance(getattr(cls, "description", ""), str):
            raise InvalidBlockType(f"{type_id}: description must be a string")
        new_instance = getattr(cls, "new_instance_options", {})
        if not isinstance(new_instance, dict):
            raise InvalidBlockType(f"{type_id}: new_instance_options must be an object")
        if new_instance and any(True for _ in Draft202012Validator(relaxed).iter_errors({**defaults, **new_instance})):
            raise InvalidBlockType(f"{type_id}: new_instance_options do not match options_schema")

    @classmethod
    def full_options_schema(cls) -> dict:
        own = copy.deepcopy(cls.options_schema)
        schema = {k: v for k, v in own.items() if k not in ("properties", "required")}
        schema["$schema"] = DRAFT_2020_12
        schema["type"] = "object"
        schema["properties"] = {**copy.deepcopy(COMMON_PROPERTIES), **own.get("properties", {})}
        if own.get("required"):
            schema["required"] = list(own["required"])
        return schema

    @classmethod
    def full_default_options(cls) -> dict:
        return {**COMMON_DEFAULTS, **copy.deepcopy(cls.default_options)}

    @classmethod
    def options_problems(cls, options: dict) -> list[dict]:
        return schema_problems(cls.full_options_schema(), options)

    def render_package_template(self, template_relative_path: str, **context: Any) -> str:
        # the folder of the module this class is in: a one-file plugin from a path has one too
        return templating.render_class_template(self.__class__, template_relative_path, **context)
