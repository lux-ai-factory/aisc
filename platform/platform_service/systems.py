"""The AI system under assessment.

A project is the thing being assessed; the *system* is what is actually
qualified, tested and reported on. Qualification describes it, the execution
engine runs tests against it, and the dashboard reads those results, so all
three have to name the same system. `core.system` is that name, written here
and read by every module.

Identity is (project, name, version). Nothing else is derived: a version is
kept exactly as its makers write it, because guessing that "1.2" and "v1.2" are
the same system would merge two real ones, and guessing they differ would split
one. What is refused is a system with no name at all.
"""
from __future__ import annotations


class InvalidSystem(ValueError):
    """A system that cannot be stored as given."""


def normalise_version(version: str | None) -> str | None:
    """A version without its surrounding space, or nothing when there is none.

    An unversioned system stores NULL rather than "", so two unversioned
    systems in a project are one system.
    """
    cleaned = (version or "").strip()
    return cleaned or None


def system_key(name: str, version: str | None) -> tuple[str, str | None]:
    """What makes this system this system, inside its project."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise InvalidSystem("a system needs a name")
    return cleaned, normalise_version(version)
