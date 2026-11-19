"""Simple bar charts drawn as inline SVG.

`svg(spec, colours)` is a pure function: no I/O, no randomness, no font measuring. The same spec
and colours give the same bytes. Bars use the primary colour only (no red, amber or green scale).

A spec is {"id", "title", "kind": "bar" | "hbar", "value_format": "percent" | "number",
"axis_min" (default 0, or below the lowest value when one is negative), "axis_max" (None = rounded-up
maximum), "series": [{"label", "value"}], "note" (optional)}.
"""
from __future__ import annotations

import math
from numbers import Real

from markupsafe import Markup, escape

KINDS = ("bar", "hbar")
VALUE_FORMATS = ("percent", "number")
MAX_ITEMS = 60
LABEL_CHARS = 40
WIDTH_MM = 160
WIDTH = 640  # user units; 4 units per millimetre
UNITS_PER_MM = WIDTH / WIDTH_MM
TICKS = 5


def _is_number(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))


def validate_spec(spec) -> None:
    """Raise ValueError when the spec cannot be drawn."""
    if not isinstance(spec, dict):
        raise ValueError("a chart spec is an object")
    if spec.get("kind") not in KINDS:
        raise ValueError("kind must be bar or hbar")
    if spec.get("value_format", "number") not in VALUE_FORMATS:
        raise ValueError("value_format must be percent or number")
    series = spec.get("series")
    if not isinstance(series, (list, tuple)):
        raise ValueError("series must be a list")
    if len(series) > MAX_ITEMS:
        raise ValueError(f"a chart has at most {MAX_ITEMS} items")
    for item in series:
        if not isinstance(item, dict):
            raise ValueError("a series item is an object")
        if not isinstance(item.get("label"), str):
            raise ValueError("a series label must be text")
        value = item.get("value")
        if value is not None and not _is_number(value):
            raise ValueError("a series value must be a number or null")
    for key in ("axis_min", "axis_max"):
        value = spec.get(key)
        if value is not None and not _is_number(value):
            raise ValueError(f"{key} must be a number")
    if not isinstance(spec.get("title", ""), str):
        raise ValueError("title must be text")


def _nice_max(value: float) -> float:
    if value <= 0:
        return 1.0
    power = 10 ** math.floor(math.log10(value))
    for step in (1, 2, 5, 10):
        if value <= step * power + 1e-12:
            return float(step * power)
    return float(10 * power)


def _trim(number: float, decimals: int) -> str:
    text = f"{number:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _format(value, value_format: str, decimal_separator: str, percent_format: str) -> str:
    if value is None:
        return "n/a"
    if value_format == "percent":
        text = _trim(float(value) * 100, 1)
        return percent_format.replace("{value}", text.replace(".", decimal_separator))
    return f"{value:g}".replace(".", decimal_separator)


def _cut(label: str) -> str:
    return label if len(label) <= LABEL_CHARS else label[: LABEL_CHARS - 1] + "..."


def _n(x: float) -> str:
    """A coordinate with at most two decimals."""
    return _trim(round(x, 2), 2)


def svg(spec, colours, *, decimal_separator: str = ".", percent_format: str = "{value}%") -> Markup:
    """Draw the spec as an accessible inline SVG (a Markup)."""
    validate_spec(spec)
    primary = str(colours["primary"])
    text_colour = str(colours["text"])
    grid = str(colours["grid"])
    kind = spec["kind"]
    fmt = spec.get("value_format", "number")
    title = spec.get("title", "")
    series = list(spec["series"])
    values = [item["value"] for item in series if item.get("value") is not None]
    # without an axis_min the axis starts at 0, or below the lowest value when one is negative
    lowest = min(values) if values else 0.0
    axis_min = float(spec["axis_min"]) if spec.get("axis_min") is not None else (
        -_nice_max(-float(lowest)) if lowest < 0 else 0.0)
    if spec.get("axis_max") is not None:
        axis_max = float(spec["axis_max"])
    elif values and max(values) <= 0 and axis_min < 0:
        axis_max = 0.0                                                # every value at or below zero
    else:
        axis_max = _nice_max(max(values) if values else 0.0)
    if axis_max <= axis_min:
        axis_max = axis_min + 1.0
    span = axis_max - axis_min

    def fmt_value(v):
        return _format(v, fmt, decimal_separator, percent_format)

    def ratio(v: float) -> float:
        return min(max((float(v) - axis_min) / span, 0.0), 1.0)

    # a bar goes from the zero line (or the axis's nearer end) to its value
    zero = ratio(min(max(0.0, axis_min), axis_max))

    ticks = [axis_min + span * i / (TICKS - 1) for i in range(TICKS)]
    parts: list[str] = []
    n = max(len(series), 1)
    font = 11
    if kind == "hbar":
        label_w, value_w, top, row = 200.0, 60.0, 10.0, 22.0
        plot_x0, plot_x1 = label_w, WIDTH - value_w
        plot_w = plot_x1 - plot_x0
        plot_h = row * n
        height = top + plot_h + 30
        for t in ticks:
            x = plot_x0 + plot_w * ratio(t)
            parts.append(f'<line x1="{_n(x)}" y1="{_n(top)}" x2="{_n(x)}" y2="{_n(top + plot_h)}" stroke="{escape(grid)}" '
                         f'stroke-width="0.5"/>')
            parts.append(f'<text x="{_n(x)}" y="{_n(top + plot_h + 14)}" font-size="{font - 1}" text-anchor="middle" '
                         f'fill="{escape(text_colour)}">{escape(fmt_value(t))}</text>')
        for i, item in enumerate(series):
            y = top + row * i
            cy = y + row / 2 + font / 3
            parts.append(f'<text x="{_n(plot_x0 - 6)}" y="{_n(cy)}" font-size="{font}" text-anchor="end" '
                         f'fill="{escape(text_colour)}">{escape(_cut(item["label"]))}</text>')
            value = item.get("value")
            if value is None:
                parts.append(f'<text x="{_n(plot_x0 + 4)}" y="{_n(cy)}" font-size="{font}" '
                             f'fill="{escape(text_colour)}">n/a</text>')
                continue
            x0, x1 = plot_x0 + plot_w * zero, plot_x0 + plot_w * ratio(value)
            parts.append(f'<rect x="{_n(min(x0, x1))}" y="{_n(y + 4)}" width="{_n(abs(x1 - x0))}" '
                         f'height="{_n(row - 8)}" fill="{escape(primary)}"/>')
            parts.append(f'<text x="{_n(max(x0, x1) + 4)}" y="{_n(cy)}" font-size="{font}" '
                         f'fill="{escape(text_colour)}">{escape(fmt_value(value))}</text>')
        parts.append(f'<line x1="{_n(plot_x0)}" y1="{_n(top)}" x2="{_n(plot_x0)}" y2="{_n(top + plot_h)}" '
                     f'stroke="{escape(grid)}" stroke-width="1"/>')
    else:
        axis_w, top, plot_h, label_h = 60.0, 20.0, 200.0, 70.0
        plot_x0, plot_x1 = axis_w, WIDTH - 10
        plot_w = plot_x1 - plot_x0
        slot = plot_w / n
        base = top + plot_h
        height = base + label_h
        for t in ticks:
            y = base - plot_h * ratio(t)
            parts.append(f'<line x1="{_n(plot_x0)}" y1="{_n(y)}" x2="{_n(plot_x1)}" y2="{_n(y)}" stroke="{escape(grid)}" '
                         f'stroke-width="0.5"/>')
            parts.append(f'<text x="{_n(plot_x0 - 6)}" y="{_n(y + font / 3)}" font-size="{font - 1}" '
                         f'text-anchor="end" fill="{escape(text_colour)}">{escape(fmt_value(t))}</text>')
        for i, item in enumerate(series):
            cx = plot_x0 + slot * i + slot / 2
            label_y = base + 14
            parts.append(f'<text x="{_n(cx)}" y="{_n(label_y)}" font-size="{font - 1}" text-anchor="end" '
                         f'transform="rotate(-30 {_n(cx)} {_n(label_y)})" '
                         f'fill="{escape(text_colour)}">{escape(_cut(item["label"]))}</text>')
            value = item.get("value")
            if value is None:
                parts.append(f'<text x="{_n(cx)}" y="{_n(base - 4)}" font-size="{font}" text-anchor="middle" '
                             f'fill="{escape(text_colour)}">n/a</text>')
                continue
            y0, y1 = base - plot_h * zero, base - plot_h * ratio(value)
            bw = max(slot * 0.6, 1.0)
            parts.append(f'<rect x="{_n(cx - bw / 2)}" y="{_n(min(y0, y1))}" width="{_n(bw)}" '
                         f'height="{_n(abs(y1 - y0))}" fill="{escape(primary)}"/>')
            parts.append(f'<text x="{_n(cx)}" y="{_n(min(y0, y1) - 4)}" font-size="{font}" text-anchor="middle" '
                         f'fill="{escape(text_colour)}">{escape(fmt_value(value))}</text>')
        parts.append(f'<line x1="{_n(plot_x0)}" y1="{_n(base)}" x2="{_n(plot_x1)}" y2="{_n(base)}" '
                     f'stroke="{escape(grid)}" stroke-width="1"/>')
    note = spec.get("note")
    if isinstance(note, str) and note:
        height += 18
        parts.append(f'<text x="0" y="{_n(height - 6)}" font-size="{font - 1}" font-style="italic" '
                     f'fill="{escape(text_colour)}">{escape(note)}</text>')
    height_mm = height / UNITS_PER_MM
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{escape(title)}" '
            f'width="{WIDTH_MM}mm" height="{_n(height_mm)}mm" viewBox="0 0 {WIDTH} {_n(height)}" '
            f'font-family="sans-serif">')
    return Markup(head + f"<title>{escape(title)}</title>" + "".join(parts) + "</svg>")
