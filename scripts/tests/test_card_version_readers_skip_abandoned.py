"""Every reader of "the latest card version" skips a withdrawn one.

A version made for a card that was never saved stays in project.system, marked abandoned. Every module that
picks the latest version (or the highest number) reads the view project.saved_system, which leaves those
rows out; no module outside the platform picks the latest from project.system itself.

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_card_version_readers_skip_abandoned.py
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: the modules' latest-version readers
LATEST_READERS = [
    "apps/backend/aisc_backend/repositories/system_version_repository.py",
    "apps/control-objectives/src/aisc_control_objectives/db/repository.py",
    "apps/report-composer/report_composer/db.py",
    "platform/platform_service/evidence.py",
    "apps/report-generator/report_renderer/data/engine.py",
    "apps/report-generator/report_renderer/data/platform.py",
    "apps/results-dashboard/aisc_ext/projects.py",
]

#: picking the latest or the highest number straight from the table
LATEST_FROM_TABLE = re.compile(
    r"FROM\s+project\.system\s+(?:\w+\s+)?ORDER\s+BY|max\(\s*(?:\w+\.)?number\s*\)\s+(?:AS\s+\w+\s+)?FROM\s+project\.system\b",
    re.IGNORECASE)


@pytest.mark.parametrize("path", LATEST_READERS)
def test_each_latest_reader_reads_the_saved_versions_view(path):
    text = (ROOT / path).read_text()
    assert "project.saved_system" in text, f"{path} picks the latest version without leaving abandoned ones out"


def _module_sources():
    for top in ("apps", "shared"):
        for path in (ROOT / top).rglob("*.py"):
            parts = set(path.parts)
            if parts & {"tests", "test", ".venv", "node_modules", "migrations", "site-packages"}:
                continue
            yield path


def test_no_module_outside_the_platform_picks_the_latest_from_the_table():
    found = [f"{p.relative_to(ROOT)}: {m.group(0)}" for p in _module_sources()
             for m in [LATEST_FROM_TABLE.search(p.read_text(errors="ignore"))] if m]
    assert found == [], "latest version read from project.system, abandoned versions included:\n" + "\n".join(found)
