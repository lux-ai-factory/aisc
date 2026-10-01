"""The editor's block numbers are the report's section numbers (2026-10-01): the outline used to count
every block 1..N with a CSS counter, while the report numbers chapters 1, 2, their blocks 1.1, 1.2, the
appendix A, B and leaves the cover, the appendix heading and an unwritten free text without a number.
`report_composer.layouts.outline_numbers`, no database."""
import importlib.util
import sys
from pathlib import Path

import pytest

from conftest import blk, need

L = "report_composer.layouts"
STRUCTURE = Path(__file__).resolve().parents[2] / "report-generator/report_renderer/structure.py"
PLACEHOLDER = "Write this section."


def numbers(blocks, numbering=True):
    return need(L, "outline_numbers")(blocks, numbering=numbering)


def mixed():
    return [blk("cover"), blk("ai_card"), blk("chapter", title="System"), blk("test_results"),
            blk("control_answers"), blk("chapter", title="Empty"), blk("appendix"), blk("free_text", text="x"),
            blk("chapter", title="Extra"), blk("dashboard_chart", chart_id=33)]


def test_numbers_follow_chapters_and_the_appendix():
    assert numbers(mixed()) == ["", "1", "2", "2.1", "2.2", "3", "", "A", "B", "B.1"]


def test_no_numbers_when_numbering_is_off():
    assert numbers(mixed(), numbering=False) == [""] * len(mixed())


def test_an_unwritten_free_text_takes_no_number():
    blocks = [blk("chapter", title="C"), blk("free_text", text=PLACEHOLDER), blk("free_text", text="written"),
              blk("free_text", text=PLACEHOLDER), blk("ai_card")]
    assert numbers(blocks) == ["1", "", "1.1", "", "1.2"]


def test_outline_carries_the_number():
    blocks = [blk("cover"), blk("chapter", title="C"), blk("ai_card")]
    got = need(L, "outline")(blocks, (), numbering=True)
    assert [o["number"] for o in got] == ["", "1", "1.1"]
    assert [o["number"] for o in need(L, "outline")(blocks)] == ["", "", ""]


def _renderer_plan():
    if not STRUCTURE.exists():
        pytest.skip("the report generator is not checked out next to the composer")
    spec = importlib.util.spec_from_file_location("renderer_structure", STRUCTURE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                     # @dataclass looks its module up while the file runs
    spec.loader.exec_module(mod)
    return mod.plan


@pytest.mark.parametrize("blocks", [
    mixed(),
    [blk("ai_card"), blk("free_text", text="a"), blk("appendix"), blk("ai_card")],
    [blk("cover"), blk("chapter", title="C"), blk("free_text", text=PLACEHOLDER), blk("ai_card"), blk("appendix")],
    [blk("appendix"), blk("chapter", title="In the appendix"), blk("ai_card"), blk("chapter", title="2nd")],
])
def test_the_composer_numbers_as_the_renderer_does(blocks):
    """The renderer drops an unwritten free text before it numbers (document.py, R2-D3.8.1); the rest
    are its sections, with `kind` set for chapters and the appendix."""
    plan = _renderer_plan()
    kept = [b for b in blocks if not (b["block_type"] == "free_text" and b["options"].get("text") == PLACEHOLDER)]
    sections = [{"instance_id": b["instance_id"], "type_id": b["block_type"],
                 "kind": b["block_type"] if b["block_type"] in ("chapter", "appendix") else None} for b in kept]
    plan(sections, toc="on", numbering=True)
    by_id = {s["instance_id"]: s["number"] for s in sections}
    assert numbers(blocks) == [by_id.get(b["instance_id"], "") for b in blocks]
