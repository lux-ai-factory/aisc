"""The live-shape fixture used by the catalog-diff tests (01-specs.md I3.7, I7.9, I18.7, RULES: the rehearsal
dump is never copied into a repository). It must be schema-only and cover every moving table, forms included.
"""

from __future__ import annotations

import re

from conftest import ROOT

FIXTURE = ROOT / "scripts/tests/fixtures/isolation/live_shape.sql"


def _text() -> str:
    return FIXTURE.read_text()


def test_i18_7_fixture_holds_no_data_owner_acl_or_secret():
    text = _text()
    for pattern in (r"^COPY ", r"^INSERT ", r"setval\(", r"OWNER TO", r"^GRANT ", r"^REVOKE ", r"SCRAM-SHA-256",
                    r"\bmd5[0-9a-f]{32}\b", r"^CREATE ROLE", r"PASSWORD"):
        assert not re.search(pattern, text, re.M | re.I), f"I18.7: live_shape.sql contains {pattern}"


def test_i3_7_i7_9_fixture_covers_every_moving_table_including_forms():
    tables = set(re.findall(r"^CREATE TABLE (\w+\.\w+) \(", _text(), re.M))
    want = {"core.system", "qualification.qualification", "qualification.qualification_answer",
            "qualification.qualification_risk", "qualification.knowledge_graph", "qualification.card_component",
            "qualification.form", "qualification.form_version", "qualification.form_question",
            "qualification.form_version_question", "control_objectives.project", "control_objectives.graph",
            "control_objectives.risk", "control_objectives.mapping_run", "control_objectives.mapped_objective",
            "engine.aisc_backend_project", "engine.aisc_backend_aisystem", "engine.aisc_backend_evaluation",
            "engine.aisc_backend_pluginconfig",
            "report_composer.layout", "report_composer.layout_block", "report_composer.template",
            "report_composer.generated_report"}
    assert want <= tables, f"fixture lacks {sorted(want - tables)}"
    assert not any(t.startswith(("catalogue.", "controls.", "llm.")) for t in tables), "fixture has non-moving schemas"
