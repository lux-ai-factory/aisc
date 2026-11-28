"""Who last changed each text written in a layout: the stamps a save keeps. Pure, no database."""
from conftest import need

ANNA = {"sub": "alice", "name": "Anna"}
LUCA = {"sub": "olga", "name": "Luca"}
T1, T2 = "2026-09-14T08:15:00+00:00", "2026-09-20T10:30:00+00:00"


def b(iid, block_type, **options):
    return {"instance_id": iid, "block_type": block_type, "options": options}


def texts(block):
    return need("report_composer.authorship", "texts")(block)


def stamps(before, before_written, blocks, by, at):
    return need("report_composer.authorship", "stamps")(before, before_written, blocks, by, at)


def test_the_texts_people_write_in_a_layout():
    assert texts(b("1", "ai_card", commentary="Read this.")) == {"commentary": "Read this."}
    assert texts(b("2", "free_text", text="Words.", commentary="More.")) == {"text": "Words.", "commentary": "More."}
    assert texts(b("3", "chapter", title="Tests", intro="Why.")) == {"intro": "Why."}
    assert texts(b("4", "superset_exports", comments={"10": "Bias held.", "11": ""})) == {"comments/10": "Bias held."}


def test_empty_and_placeholder_texts_are_not_written():
    assert texts(b("1", "free_text", text="Write this section.", commentary="  ")) == {}
    assert texts(b("2", "chapter", title="Write this section.", intro="")) == {}


def test_a_new_text_is_stamped_with_the_saver_and_an_unchanged_one_keeps_its_stamp():
    first = [b("a", "ai_card", commentary="A")]
    w1 = stamps([], {}, first, ANNA, T1)
    assert w1 == {"a": {"commentary": {"sub": "alice", "by": "Anna", "at": T1}}}
    second = first + [b("b", "test_results", commentary="B")]
    w2 = stamps(first, w1, second, LUCA, T2)
    assert w2 == {"a": {"commentary": {"sub": "alice", "by": "Anna", "at": T1}},
                  "b": {"commentary": {"sub": "olga", "by": "Luca", "at": T2}}}


def test_a_changed_text_takes_the_new_saver():
    first = [b("a", "free_text", text="Old words.")]
    w1 = stamps([], {}, first, ANNA, T1)
    w2 = stamps(first, w1, [b("a", "free_text", text="New words.")], LUCA, T2)
    assert w2 == {"a": {"text": {"sub": "olga", "by": "Luca", "at": T2}}}


def test_a_text_written_before_stamps_were_kept_stays_without_one():
    old = [b("a", "ai_card", commentary="Old.")]
    assert stamps(old, {}, old, LUCA, T2) == {}


def test_a_save_without_a_saver_stamps_nothing_new_and_keeps_the_old_stamps():
    first = [b("a", "ai_card", commentary="A")]
    w1 = stamps([], {}, first, ANNA, T1)
    assert stamps(first, w1, first + [b("b", "ai_card", commentary="B")], None, T2) == w1


def test_a_cleared_text_loses_its_stamp():
    first = [b("a", "ai_card", commentary="A")]
    w1 = stamps([], {}, first, ANNA, T1)
    assert stamps(first, w1, [b("a", "ai_card", commentary="")], LUCA, T2) == {}


def test_one_tool_commentary_changed_leaves_the_others_stamp():
    first = [b("x", "superset_exports", comments={"10": "Ten.", "11": "Eleven."})]
    w1 = stamps([], {}, first, ANNA, T1)
    w2 = stamps(first, w1, [b("x", "superset_exports", comments={"10": "Ten.", "11": "Eleven, again."})], LUCA, T2)
    assert w2 == {"x": {"comments/10": {"sub": "alice", "by": "Anna", "at": T1},
                        "comments/11": {"sub": "olga", "by": "Luca", "at": T2}}}
