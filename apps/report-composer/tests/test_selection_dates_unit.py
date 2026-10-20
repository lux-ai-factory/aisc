"""selection.parse_dates: the last day 9999-12-31 has no day after it, so the period's end overflowed
(OverflowError, a 500 on the preview and the generate form). It is refused as a 422 like any
date that is not one."""
import pytest

from conftest import need


def parse(from_value, to_value):
    return need("report_composer.selection", "parse_dates")(from_value, to_value, False, None)


def test_the_last_representable_day_is_refused_with_a_pointer():
    from report_composer.errors import ApiError

    with pytest.raises(ApiError) as caught:
        parse(None, "9999-12-31")
    assert (caught.value.status, caught.value.code) == (422, "invalid_request")
    assert caught.value.details[0]["pointer"] == "/period_to"


def test_the_day_before_it_is_kept():
    assert parse("2026-01-01", "9999-12-30").period_to.year == 9999
