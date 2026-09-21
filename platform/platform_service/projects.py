"""The platform's project: created once, referenced by every module.

Only the rules that decide identity live here, with no database and no web
framework, so they can be tested and reasoned about on their own.
"""
from __future__ import annotations

import re
import unicodedata

SLUG_MAX = 64
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class InvalidProject(ValueError):
    """The input cannot identify a project, and guessing one would be worse."""


def normalise_name(name: str | None) -> str:
    """The name as it will be stored: trimmed, otherwise untouched.

    A project's name is for people, so it keeps its capitals, punctuation and
    accents. Only surrounding space is meaningless.
    """
    if not isinstance(name, str) or not name.strip():
        raise InvalidProject("a project needs a name")
    return name.strip()


def slug_for(name: str) -> str:
    """A URL-safe handle derived from a name.

    Accents are folded to their base letters rather than dropped, so
    "Évaluation" gives "evaluation" and not "valuation". Anything else that is
    not a letter or digit becomes a separator, runs collapse, and the result is
    bounded so it fits in a path. A name with nothing usable in it raises: a
    project addressed by a random string would be worse than a refusal.
    """
    text = normalise_name(name)
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    lowered = ascii_only.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:SLUG_MAX].strip("-")
    if not slug:
        raise InvalidProject(f"no url-safe handle can be made from {name!r}")
    return slug


def validate_slug(slug: str | None) -> str:
    """An explicitly supplied slug, accepted as given or refused.

    Never rewritten: if a caller names the handle, the handle they get is the
    one they asked for, or an error saying it cannot be used.
    """
    if not isinstance(slug, str) or not _SLUG_RE.match(slug) or len(slug) > SLUG_MAX:
        raise InvalidProject(
            "a slug is lowercase letters, digits and single hyphens, "
            f"at most {SLUG_MAX} characters"
        )
    return slug


#: A project is named two ways: the slug a URL reads, and the pid rows point at.
#: A module is handed whichever its page happens to have, so every endpoint that
#: takes a project takes either; this is how they are told apart.
_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def looks_like_pid(value: str) -> bool:
    return bool(_PID.match(value or ""))
