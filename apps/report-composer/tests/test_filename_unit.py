"""PDF filenames (report run 2026-09-23: R4.3.4, D11)."""
from datetime import datetime, timezone

from conftest import need


# R4.3.4
def test_r4_3_4_filename():
    f = need("report_composer.reports", "pdf_filename")
    when = datetime(2026, 9, 20, 10, 30, tzinfo=timezone.utc)
    assert f("alpha", 2, "Quarterly report: Q3 / final", when) == "alpha-v2-quarterly-report-q3-final-20260920-1030.pdf"
