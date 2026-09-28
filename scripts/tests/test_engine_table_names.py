"""Our readers use Sean's engine table names (adapt plan 2026-09-28, item 1)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHORT = ("ai_component", "ai_system", "artifact", "dataset", "derived", "direct", "evaluation",
         "evaluation_input", "evaluation_plugin", "measurement", "metric", "metric_category",
         "metric_category_metrics", "model", "observation", "plugin", "plugin_config",
         "plugin_config_project_config", "project", "project_config")
PATTERN = re.compile(r"\bengine\.(" + "|".join(sorted(SHORT, key=len, reverse=True)) + r")\b(?!_)")
READERS = [
    "apps/results-dashboard/aisc_ext/projects.py",
    "platform/platform_service/isolate/ownership.py",
    "scripts/db_consistency/checks.py",
    "scripts/verify-project-databases.sh",
    "scripts/verify-one-database.sh",
    "scripts/report-grants.sh",
    "scripts/lib/report_bed_isolated.py",
    "scripts/lib/report_bed.py",
    "scripts/test-pipeline-chain.sh",
]
REPORT = Path.home() / "aisc-report-generator" / "report_renderer" / "data" / "engine.py"


def test_no_reader_names_a_short_engine_table():
    found = {f: PATTERN.findall((ROOT / f).read_text()) for f in READERS}
    if REPORT.exists():
        found[str(REPORT)] = PATTERN.findall(REPORT.read_text())
    assert {f: m for f, m in found.items() if m} == {}


def test_the_dashboard_review_script_builds_its_dataset_on_seans_measurement_table():
    src = (ROOT / "apps/results-dashboard/scripts/verify_review.py").read_text()
    assert 'table_name="measurement"' not in src
    assert 'table_name="aisc_backend_measurement"' in src
