"""The composer keeps nothing in `platform`: the install-wide library of report presets is gone."""
from pathlib import Path

from report_composer import migrate

ROOT = Path(__file__).resolve().parents[1]


def test_there_is_no_library_history_to_migrate():
    assert not (ROOT / "migrations/library").exists()
    for name in ("LIBRARY", "LIBRARY_TABLE", "LIBRARY_NAME", "migrate_library"):
        assert not hasattr(migrate, name), name
