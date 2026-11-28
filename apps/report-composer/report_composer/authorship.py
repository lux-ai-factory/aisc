"""Who last changed each text people write in a layout, so the report can say who wrote it. Pure functions.

The texts are a block's commentary, a free text's text, a chapter's introduction and each tool's commentary of
Exported results (comments/<dashboard id>). A save stamps every written text whose content differs from the
previous revision with the saver ({"sub", "by", "at"}: subject, display name, time); a text left as it was keeps
its stamp, and one written before stamps were kept stays without one, so the report names nobody rather than
guessing. Empty texts and texts still holding the placeholder are not written and carry no stamp.
"""
from __future__ import annotations

from .prose import is_placeholder

#: the block types whose own text is written in the layout, and the option holding it
OWN_TEXT = {"free_text": "text", "chapter": "intro"}


def _written(value) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not is_placeholder(value)


def texts(block: dict) -> dict[str, str]:
    """{path: text} of the written texts of one block."""
    options = block.get("options") or {}
    out = {}
    if _written(options.get("commentary")):
        out["commentary"] = options["commentary"]
    own = OWN_TEXT.get(block.get("block_type"))
    if own and _written(options.get(own)):
        out[own] = options[own]
    comments = options.get("comments")
    if block.get("block_type") == "superset_exports" and isinstance(comments, dict):
        out.update({f"comments/{k}": v for k, v in comments.items() if _written(v)})
    return out


def stamps(before: list[dict], before_written: dict | None, blocks: list[dict], by: dict | None, at: str) -> dict:
    """{instance id: {path: stamp}} for `blocks` saved after `before` (stamped `before_written`) by `by`
    ({"sub", "name"}, or None for a save no person wrote, which stamps nothing new) at `at`."""
    before_written = before_written or {}
    old = {b["instance_id"]: texts(b) for b in before}
    out: dict = {}
    for b in blocks:
        iid = b["instance_id"]
        for path, text in texts(b).items():
            if old.get(iid, {}).get(path) == text:
                stamp = (before_written.get(iid) or {}).get(path)
            else:
                stamp = {"sub": by["sub"], "by": by["name"], "at": at} if by else None
            if stamp:
                out.setdefault(iid, {})[path] = stamp
    return out


def renamed(written: dict | None, new_ids: dict[str, str]) -> dict:
    """The stamps of a layout copied under new instance ids ({old id: new id})."""
    return {new_ids[iid]: s for iid, s in (written or {}).items() if iid in new_ids}


def for_renderer(written: dict | None, instance_id: str) -> dict | None:
    """What the renderer is sent of one block's stamps: who and when, never the subject."""
    mine = (written or {}).get(instance_id) or {}
    return {path: {"by": s["by"], "at": s["at"]} for path, s in mine.items()} or None
