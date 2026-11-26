"""Every file that reads the card views is classified, and every stamping writer takes the card lock.

The card state of a project (card version, revision) is guarded by one advisory lock. A stamping writer reads
"the latest card" to store it on a record or to compare it with what a page sent; it takes the lock shared,
through the helper of its language, before it reads. The files that query project.saved_system,
project.carded_system or project.system are listed here by what they do with them. A file that reads one of
the three and is on no list fails the test: a new reader has to be classified.

Read as source text; nothing is imported or run.

Run from the repo root:

    uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' \
        python -m pytest -q -p no:cacheprovider scripts/tests/test_card_lock_use.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: read "the latest card" to stamp a record or to compare it with what a page sent: the helper call each makes
STAMPING_WRITERS = {
    "apps/backend/aisc_backend/repositories/system_version_repository.py": "card_lock.shared(",
    "apps/control-objectives/src/aisc_control_objectives/db/repository.py": "card_lock.shared(",
    "apps/report-composer/report_composer/db.py": "card_lock.shared(",
    "apps/controls/src/lib/systemVersion.ts": "cardLockShared(",
}
#: the platform's version counter: create, revise and withdraw read the versions under the lock they own
LOCK_OWNERS = [
    "platform/platform_service/db.py",
]
#: read the versions to show them, and store nothing about them
DISPLAY_READERS = [
    "apps/chart-assistant/chart_assistant/views.py",
    "apps/report-generator/report_renderer/data/control_objectives.py",
    "apps/report-generator/report_renderer/data/engine.py",
    "apps/report-generator/report_renderer/data/platform.py",
    "apps/report-generator/report_renderer/data/qualification.py",
    "apps/results-dashboard/aisc_ext/projects.py",
    "platform/platform_service/evidence.py",
]
CLASSIFIED = {*STAMPING_WRITERS, *LOCK_OWNERS, *DISPLAY_READERS}

#: a query of one of the three, in SQL as the modules write it
QUERIES = re.compile(r"\b(?:from|join|update|into)\s+\"?project\"?\.\"?(?:saved_system|carded_system|system)\b",
                     re.IGNORECASE)
#: a line that is only a comment says nothing about what the file reads
COMMENT = re.compile(r"^\s*(?:#|//|\*|/\*|--)")
SOURCES = {".py", ".ts", ".tsx", ".mjs", ".js"}
#: tests, dependencies and migrations (which make the three, and run before anybody stores a card)
NOT_MODULE_CODE = {"tests", "test", "node_modules", ".venv", "site-packages", "migrations", "alembic", "prisma",
                   ".next", "__pycache__"}


def _code(path: Path) -> str:
    return "\n".join(line for line in path.read_text(errors="ignore").splitlines() if not COMMENT.match(line))


def _readers() -> list[str]:
    """Every source file of the modules, the platform and the shared code that queries one of the three."""
    found = []
    for top in ("apps", "platform", "shared"):
        for path in (ROOT / top).rglob("*"):
            if path.suffix not in SOURCES or NOT_MODULE_CODE & set(path.parts) or not path.is_file():
                continue
            if QUERIES.search(_code(path)):
                found.append(str(path.relative_to(ROOT)))
    return sorted(found)


@pytest.mark.parametrize("path", sorted(STAMPING_WRITERS))
def test_each_stamping_writer_takes_the_lock_through_the_helper(path):
    call = STAMPING_WRITERS[path]
    assert call in _code(ROOT / path), f"{path} reads the latest card without calling {call.rstrip('(')}"


def test_no_file_reads_the_card_views_without_being_classified():
    unclassified = [path for path in _readers() if path not in CLASSIFIED]
    assert unclassified == [], ("these files read project.system, project.saved_system or project.carded_system and "
                                "are on no list here (stamping writer, lock owner, display reader):\n"
                                + "\n".join(unclassified))
