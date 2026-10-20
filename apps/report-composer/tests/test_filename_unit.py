"""Download filenames: the layout name is slugified."""
from datetime import datetime, timezone

from conftest import need


def test_filename():
    f = need("report_composer.reports", "document_filename")
    when = datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc)
    assert f("alpha", 2, "Quarterly report: Q3 / final", when, "pdf") == "alpha-v2-quarterly-report-q3-final-20260920-1030.pdf"
