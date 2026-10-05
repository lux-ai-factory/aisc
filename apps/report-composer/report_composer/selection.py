"""The data a report covers. Dates are inclusive, in UTC:
a period runs from 00:00 of `from` to 00:00 of the day after `to`."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from .errors import ApiError


@dataclass(frozen=True)
class Selection:
    period_from: datetime | None
    period_to: datetime | None
    other_versions: bool
    compare_to: str | None


def _day(value, pointer) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ApiError(422, "invalid_request", "A date is YYYY-MM-DD.",
                       [{"pointer": pointer, "message": "is not a date"}]) from None


def parse_dates(from_value, to_value, other_versions: bool, compare_to) -> Selection:
    start, end = _day(from_value, "/period_from"), _day(to_value, "/period_to")
    if start and end and end < start:
        raise ApiError(422, "invalid_request", "The period ends before it starts.",
                       [{"pointer": "/period_to", "message": "is before the start"}])
    pf = datetime.combine(start, time(0), timezone.utc) if start else None
    pt = datetime.combine(end + timedelta(days=1), time(0), timezone.utc) if end else None
    return Selection(pf, pt, bool(other_versions), compare_to)


def for_snapshot(sel: Selection) -> dict:
    """The snapshot's `selection` object (the renderer's report_renderer.selection)."""
    def iso(d):
        return d.isoformat() if d else None
    return {"period_from": iso(sel.period_from), "period_to": iso(sel.period_to),
            "other_versions": sel.other_versions, "compare_to": sel.compare_to}


def last_day(period_to: datetime | None) -> date | None:
    """The inclusive last day of a stored period."""
    return (period_to - timedelta(days=1)).date() if period_to else None
