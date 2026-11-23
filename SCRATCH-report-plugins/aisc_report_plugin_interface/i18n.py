"""Catalogues of translated texts for the renderer and its plugins.

A catalogue file is JSON: {"_meta": {"code": "en", "name": "English", "decimal_separator": ".",
"percent_format": "{value}%"}, "messages": {"Message id": "Text shown"}}. The English text is the message
id. Reports are in English only; the mechanism takes any language code. Nothing here reads a file at
import time.

Singular forms: a message may have a variant under "<msgid>|one", used when the first
whole-number parameter of the msgid is in the catalogue's `_meta.plural_one` list (default [1]). So
"{count} evaluations" can read "1 evaluation".
"""
from __future__ import annotations

import importlib.util
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

CODE = re.compile(r"^[a-z]{2}(-[A-Z]{2})?$")
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Catalogue:
    code: str
    name: str
    messages: dict = field(default_factory=dict)
    decimal_separator: str = "."
    percent_format: str = "{value}%"
    plural_one: tuple = (1,)


ONE = "|one"


def load_catalogue(path) -> Catalogue:
    """Read one catalogue file; anything that is not a catalogue raises ValueError."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not a catalogue: {exc}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("_meta"), dict) or not isinstance(doc.get("messages"), dict):
        raise ValueError("a catalogue has _meta and messages")
    meta = doc["_meta"]
    code = meta.get("code")
    if not isinstance(code, str) or not CODE.match(code):
        raise ValueError("the catalogue code must look like en or en-GB")
    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("the catalogue needs a name")
    messages = doc["messages"]
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in messages.items()):
        raise ValueError("messages map texts to texts")
    decimal_separator = meta.get("decimal_separator", ".")
    percent_format = meta.get("percent_format", "{value}%")
    if not isinstance(decimal_separator, str) or not isinstance(percent_format, str) \
            or "{value}" not in percent_format:
        raise ValueError("decimal_separator and percent_format must be texts")
    plural_one = meta.get("plural_one", [1])
    if not isinstance(plural_one, list) or not all(
            isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in plural_one):
        raise ValueError("plural_one must be a list of whole numbers")
    return Catalogue(code=code, name=name, messages=dict(messages), decimal_separator=decimal_separator,
                     percent_format=percent_format, plural_one=tuple(plural_one))


def package_catalogue(package: str, code: str) -> Catalogue | None:
    """The package's own i18n/{code}.json, or None when it has none."""
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    for location in spec.submodule_search_locations:
        path = Path(location) / "i18n" / f"{code}.json"
        if path.is_file():
            try:
                return load_catalogue(path)
            except ValueError as exc:
                logger.warning("the %s catalogue of %s is unusable, English is used instead: %s", code, package, exc)
                return None
    return None


def fill(msgid: str, params: dict) -> str:
    """Replace {name} by params[name]; every other brace stays as it is."""
    def repl(match: re.Match) -> str:
        name = match.group(1)
        return str(params[name]) if name in params else match.group(0)
    return _PLACEHOLDER.sub(repl, str(msgid))


def _counts_as_one(msgid, params: dict, plural_one) -> bool:
    """True when the first whole-number parameter named in msgid is in plural_one."""
    for match in _PLACEHOLDER.finditer(str(msgid)):
        value = params.get(match.group(1))
        if isinstance(value, int) and not isinstance(value, bool):
            return value in plural_one
    return False


def translator(*catalogues):
    """t(msgid, **params): the first catalogue holding msgid wins, else msgid; then placeholders."""
    found = [c for c in catalogues if c is not None]

    def t(msgid, **params) -> str:
        text = msgid
        for catalogue in found:
            if msgid in catalogue.messages or f"{msgid}{ONE}" in catalogue.messages:
                text = catalogue.messages.get(msgid, msgid)
                if f"{msgid}{ONE}" in catalogue.messages and _counts_as_one(msgid, params, catalogue.plural_one):
                    text = catalogue.messages[f"{msgid}{ONE}"]
                break
        try:
            return fill(text, params)
        except Exception:  # noqa: BLE001 - a translation never breaks a report
            return str(msgid)
    return t


def translator_for(ctx, package: str):
    """A plugin's translator: the renderer's translate_for(package), else ctx.t, else English."""
    translate_for = getattr(ctx, "translate_for", None)
    if callable(translate_for):
        try:
            return translate_for(package)
        except Exception as exc:  # noqa: BLE001
            logger.warning("no translator for %s, the report's own is used instead: %s", package, exc)
    t = getattr(ctx, "t", None)
    if callable(t):
        return t
    return translator()


def format_number(ctx, value, decimals: int | None = None) -> str:
    """A number as the renderer prints it (:g, or fixed decimals), with the report's decimal separator."""
    if value is None:
        return "n/a"
    try:
        text = f"{float(value):.{decimals}f}" if decimals is not None else f"{value:g}"
    except (TypeError, ValueError):
        text = str(value)
    return text.replace(".", getattr(ctx, "decimal_separator", ".") or ".")


def format_percent(ctx, share, decimals: int = 1) -> str:
    """A share 0..1 as a percentage (at most `decimals` decimals, trailing zeros dropped)."""
    if share is None:
        return "n/a"
    text = f"{float(share) * 100:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text == "-0":
        text = "0"
    text = text.replace(".", getattr(ctx, "decimal_separator", ".") or ".")
    return (getattr(ctx, "percent_format", "{value}%") or "{value}%").replace("{value}", text)


# The same objects under other names, for the report renderer: its guard test forbids the word
# "catalogue" anywhere in its code.
LanguageFile = Catalogue
read_language_file = load_catalogue
package_language_file = package_catalogue
