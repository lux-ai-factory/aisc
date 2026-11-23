"""MLA-Reject inside the Test results block."""
from __future__ import annotations

from aisc_report_plugin_interface import BaseToolRenderer

from .statistics import compute_statistics


class MLAREJECTToolRenderer(BaseToolRenderer):
    tool_names = ("MLA-Reject",)

    def render(self, run, ctx) -> str:
        return self.render_package_template(
            "templates/tool_section.html.j2",
            tool_name=run.tool.get("display_name") or "MLA-Reject",
            statistics=compute_statistics(run.measurements),
        )

    # verdict: inherited (None): no pass/fail threshold is defined for MLA-Reject
