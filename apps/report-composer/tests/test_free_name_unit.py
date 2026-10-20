"""templates.free_name, used when an imported layout or template is renamed to a free name, keeps the
result within 120 characters by shortening the name before the suffix, never the suffix:
it returned the taken name itself for a name of 116 to 120 characters."""
from conftest import need


def free_name(name, taken):
    return need("report_composer.templates", "free_name")(name, taken)


def test_a_free_name_is_kept():
    assert free_name("Bank X", {"Other"}) == "Bank X"


def test_a_taken_short_name_gets_a_number():
    assert free_name("Bank X", {"Bank X", "Bank X (2)"}) == "Bank X (3)"


def test_a_taken_name_of_120_characters_gets_a_free_one_of_120():
    name = "x" * 120
    first = free_name(name, {name})
    assert first != name and len(first) == 120 and first.endswith(" (2)")
    second = free_name(name, {name, first})
    assert second not in (name, first) and len(second) == 120
