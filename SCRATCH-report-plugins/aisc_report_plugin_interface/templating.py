"""Package templates for block and tool renderers.

Autoescape is on for every template, whatever its extension (`.html.j2` included).
"""
from __future__ import annotations

import functools
import importlib.util
from pathlib import PurePosixPath
from typing import Any

import jinja2


def validate_relative_template_path(path: str) -> str:
    """The path of a template inside its package: relative, no `..`, no empty part."""
    if not isinstance(path, str) or not path or path.strip() == "":
        raise ValueError("Template path must be a non-empty relative path")
    p = PurePosixPath(path)
    if p.is_absolute():
        raise ValueError("Template path must be relative to the plugin package")
    if any(part in {"..", ""} for part in p.parts) or ".." in path.split("/"):
        raise ValueError("Template path cannot navigate outside the plugin package")
    return p.as_posix()


@functools.lru_cache(maxsize=None)
def _environment(package: str) -> jinja2.Environment:
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError) as exc:
        raise ValueError(f"package {package!r} cannot be found") from exc
    if spec is None or not spec.submodule_search_locations:
        raise ValueError(f"package {package!r} cannot be found")
    loader = jinja2.FileSystemLoader(list(spec.submodule_search_locations))
    return jinja2.Environment(loader=loader, autoescape=True)


def render_package_template(package: str, template_relative_path: str, **context: Any) -> str:
    """Render `template_relative_path` from the folder of `package`, autoescaped."""
    safe = validate_relative_template_path(template_relative_path)
    return _environment(package).get_template(safe).render(**context)


def template_folders_of(cls) -> tuple[str, ...]:
    """Where a renderer class's templates are: the folder of the module it is defined in (a package's
    own folder for a class in its __init__). Found from the module itself, not from its dotted name, so a
    one-file plugin loaded from a path has its folder too."""
    import os
    import sys

    module = sys.modules.get(cls.__module__)
    if module is not None and getattr(module, "__path__", None):
        return tuple(module.__path__)
    if module is not None and getattr(module, "__file__", None):
        return (os.path.dirname(os.path.abspath(module.__file__)),)
    name = cls.__module__
    package = name.rsplit(".", 1)[0] if "." in name else name
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise ValueError(f"package {package!r} cannot be found")
    return tuple(spec.submodule_search_locations)


@functools.lru_cache(maxsize=None)
def _folder_environment(folders: tuple[str, ...]) -> jinja2.Environment:
    return jinja2.Environment(loader=jinja2.FileSystemLoader(list(folders)), autoescape=True)


def render_class_template(cls, template_relative_path: str, **context: Any) -> str:
    """Render `template_relative_path` from the folder of the module `cls` is defined in, autoescaped."""
    safe = validate_relative_template_path(template_relative_path)
    return _folder_environment(template_folders_of(cls)).get_template(safe).render(**context)
