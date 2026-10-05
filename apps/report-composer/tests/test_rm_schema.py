"""The layout tables hold no data columns."""
import pytest

from conftest import pdb_of

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _columns(bed, table) -> set[str]:
    out = bed.scalar(pdb_of("A"), "SELECT string_agg(column_name, ',' ORDER BY column_name) FROM"
                     " information_schema.columns WHERE table_schema = 'report_composer'"
                     f" AND table_name = '{table}'")
    return set(out.strip().split(","))


def test_a_layout_has_no_version_language_or_toc(client, bed):
    client.get("/health")
    client.get("/api/p/alpha/layouts", headers={})      # opens (and migrates) Alpha's database
    cols = _columns(bed, "layout")
    assert {"system_id", "language", "toc"}.isdisjoint(cols), cols
    assert {"show_index", "numbering", "coverage"} <= cols


def test_a_report_records_its_selection(client, bed):
    client.get("/health")
    cols = _columns(bed, "generated_report")
    assert {"system_id", "period_from", "period_to", "other_versions", "compare_to"} <= cols, cols


def test_the_settings_default_to_an_index_and_numbering():
    """Numbering is on by default (see test_numbering_on_by_default.py)."""
    from report_composer.settings import document_settings, snapshot_document
    s = document_settings({}, None)
    assert (s["show_index"], s["numbering"]) == (True, True)
    assert snapshot_document({**s, "show_index": False}, None)["toc"] == "off"
    assert snapshot_document(s, None)["toc"] == "on"
    with pytest.raises(Exception):
        document_settings({"show_index": "yes"}, None)
