"""The editor's outline says which sections have a written commentary ("noted") and which flags each row
shows: note, to write, empty, problems. `report_composer.layouts.outline` and `outline_flags`, no database."""
from conftest import blk, need

L = "report_composer.layouts"
PLACEHOLDER = "Write this section."


def outline(blocks, numbering=True):
    return need(L, "outline")(blocks, (), numbering=numbering)


def flag_names(entry):
    return [f["name"] for f in entry["flags"]]


def test_noted_is_true_only_for_a_written_commentary():
    blocks = [blk("ai_card", commentary="Accuracy held."), blk("ai_card", commentary=""),
              blk("ai_card", commentary="   "), blk("ai_card", commentary=PLACEHOLDER), blk("ai_card"),
              blk("ai_card", commentary=None)]
    assert [o["noted"] for o in outline(blocks)] == [True, False, False, False, False, False]


def test_the_flags_follow_the_outline():
    blocks = [blk("chapter", title="Empty"), blk("chapter", title="Full"), blk("ai_card", commentary="Done."),
              blk("free_text", text=PLACEHOLDER)]
    entries = outline(blocks)
    assert [flag_names(o) for o in entries] == [["empty"], [], ["note"], ["to-write"]]
    labels = {f["name"]: f["label"] for o in entries for f in o["flags"]}
    assert labels == {"empty": "empty", "note": "note", "to-write": "to write"}
    assert entries[3]["flags"][0]["title"] == entries[3]["unwritten_hint"]
    assert entries[0]["flags"][0]["title"] == "This chapter is empty."


def test_a_problems_flag_names_the_problems():
    flags = need(L, "outline_flags")(noted=True, unwritten_hint=None, empty_chapter=False,
                                     problems=["Choose a value", "must be at least 1"])
    assert [f["name"] for f in flags] == ["note", "problems"]
    assert flags[1]["label"] == "problems" and flags[1]["title"] == "Choose a value; must be at least 1"
