"""What "at head" means for every migration history a project database has (used by check C7).

Read from the repository, never from a database: the template files of the platform, each module's own
migrations directory, and control objectives' alembic revisions (the heads are the revisions no
`down_revision` names). `verify-project-databases.sh` reuses this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_TEMPLATE = ROOT / "platform/project-template"
CONTROLS_MIGRATIONS = ROOT / "apps/controls/prisma/migrations"
QUALIFICATION_MIGRATIONS = ROOT / "apps/qualification/prisma/migrations"
ENGINE_MIGRATIONS = ROOT / "apps/backend/aisc_backend/migrations"
COMPOSER_MIGRATIONS = ROOT / "apps/report-composer/migrations/project"
CO_VERSIONS = ROOT / "apps/control-objectives/alembic/versions"

_REVISION = re.compile(r"^revision\s*(?::\s*\w+\s*)?=\s*['\"]([^'\"]+)['\"]", re.M)
_DOWN = re.compile(r"^down_revision\s*(?::[^=]+)?=\s*(.+)$", re.M)
_QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")


def templates() -> list[str]:
    return sorted(p.name for p in PROJECT_TEMPLATE.glob("*.sql"))


def _prisma(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []


def controls() -> list[str]:
    return _prisma(CONTROLS_MIGRATIONS)


def qualification() -> list[str]:
    return _prisma(QUALIFICATION_MIGRATIONS)


def engine() -> list[str]:
    return sorted(p.stem for p in ENGINE_MIGRATIONS.glob("[0-9]*.py"))


def report_composer() -> list[str]:
    return sorted(p.name for p in COMPOSER_MIGRATIONS.glob("*.sql"))


def control_objectives() -> list[str]:
    """The alembic heads: every revision that no other revision names as its down_revision."""
    revisions, downs = set(), set()
    for path in CO_VERSIONS.glob("*.py"):
        text = path.read_text()
        rev = _REVISION.search(text)
        if not rev:
            continue
        revisions.add(rev.group(1))
        down = _DOWN.search(text)
        if down:
            downs.update(_QUOTED.findall(down.group(1)))
    return sorted(revisions - downs)


@dataclass(frozen=True)
class Tracker:
    module: str
    table: str   # schema.table
    sql: str     # the names this database has applied
    wanted: tuple[str, ...]
    exact: bool = False   # alembic: the applied set must equal the heads


def trackers() -> list[Tracker]:
    """Every history of a project database, in pipeline order."""
    return [
        Tracker("template", "provision.template_migration", "SELECT name FROM provision.template_migration",
                tuple(templates())),
        Tracker("qualification", "qualification._prisma_migrations",
                "SELECT migration_name FROM qualification._prisma_migrations"
                " WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL", tuple(qualification())),
        Tracker("controls", "controls._prisma_migrations",
                "SELECT migration_name FROM controls._prisma_migrations"
                " WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL", tuple(controls())),
        Tracker("control_objectives", "control_objectives.alembic_version",
                "SELECT version_num FROM control_objectives.alembic_version", tuple(control_objectives()), exact=True),
        Tracker("engine", "engine.django_migrations",
                "SELECT name FROM engine.django_migrations WHERE app = 'aisc_backend'", tuple(engine())),
        Tracker("report_composer", "report_composer.schema_migration",
                "SELECT name FROM report_composer.schema_migration", tuple(report_composer())),
    ]


def behind(tracker: Tracker, applied: set[str]) -> list[str]:
    """The names the database lacks (for alembic, the heads it is not at)."""
    return [w for w in tracker.wanted if w not in applied]


def extra(tracker: Tracker, applied: set[str]) -> list[str]:
    """alembic only: revisions the database is at that are not heads (it is behind, or ahead of this tree)."""
    return sorted(applied - set(tracker.wanted)) if tracker.exact else []
