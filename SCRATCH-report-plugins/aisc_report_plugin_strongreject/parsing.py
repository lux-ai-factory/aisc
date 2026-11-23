"""Pure parsing of what aisc-plugin-strongreject 0.1.0 writes. Never raises."""
from __future__ import annotations

import re

HARMFULNESS = "StrongREJECT Harmfulness"
RESISTANCE = "Jailbreak Resistance"
WORST = "Worst-Case Jailbreak Harmfulness"
BASELINE = "Baseline Harmfulness (no jailbreak)"
SUMMARY_NAMES = (HARMFULNESS, RESISTANCE, WORST, BASELINE)

#: The start of the description the plugin writes on success
SUCCESS_TEXT = {
    HARMFULNESS: "Mean harmfulness across all jailbreaks",
    RESISTANCE: "1 - harmfulness.",
    WORST: "Most effective jailbreak: ",
    BASELINE: "Harmfulness with no jailbreak applied",
}
JAILBREAK_PREFIX = "Harmfulness | "

_WORST_KEY = re.compile(r"^Most effective jailbreak:\s*(.+?)\s*\(lower is safer\)\.?\s*$")
_PROMPTS = re.compile(r"over\s+(\d+)\s+prompts")


def is_scored(name: str, description) -> bool:
    """A summary measurement is scored when its description starts with the plugin's success text."""
    text = description.strip() if isinstance(description, str) else ""
    return text.startswith(SUCCESS_TEXT[name].strip())


def jailbreak_key(name) -> str | None:
    if isinstance(name, str) and name.startswith(JAILBREAK_PREFIX) and len(name) > len(JAILBREAK_PREFIX):
        return name[len(JAILBREAK_PREFIX):].strip()
    return None


def worst_key(description) -> str | None:
    if not isinstance(description, str):
        return None
    match = _WORST_KEY.match(description.strip())
    if match:
        return match.group(1)
    text = description.strip()
    prefix = SUCCESS_TEXT[WORST].strip()
    return text[len(prefix):].strip() or None if text.startswith(prefix) else None


def prompts(description) -> int | None:
    if not isinstance(description, str):
        return None
    match = _PROMPTS.search(description)
    return int(match.group(1)) if match else None
