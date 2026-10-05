"""The AI system under assessment, as its AI card describes it.

A project is the thing being assessed; the *system* is what is actually
qualified, tested and reported on, and every module has to name the same one.
Each saved card is a row of `project.system` in the project's own database,
numbered 1, 2, ..., written by the platform and read by every module of that
project.

Name and version are kept exactly as their makers write them, only trimmed:
guessing that "1.2" and "v1.2" are the same would merge two real versions.
What is refused is a system with no name at all.
"""
from __future__ import annotations


class InvalidSystem(ValueError):
    """A system that cannot be stored as given."""


def normalise_version(version: str | None) -> str | None:
    """A version without its surrounding space, or nothing when there is none.

    An unversioned system stores NULL rather than "".
    """
    cleaned = (version or "").strip()
    return cleaned or None


def system_key(name: str, version: str | None) -> tuple[str, str | None]:
    """The name and version as they are stored."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise InvalidSystem("a system needs a name")
    return cleaned, normalise_version(version)
