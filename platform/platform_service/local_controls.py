"""Local controls: checklists kept in the stack, in the public catalogue's seed format
(apps/catalogue/backend/controls_seed.json), one control or a list per *.json in LOCAL_CONTROLS_DIR (the
repo's local_controls/, mounted read-only). The catalogue offers them to every project, public or private,
and the evidence page takes their dimension from them, until the hosted catalogue publishes them itself
(local_controls/README.md)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: the folder of local controls (the repo's local_controls/, mounted read-only)
LOCAL_CONTROLS_DIR = "/app/local_controls"


def local_controls() -> list[dict]:
    """The controls in LOCAL_CONTROLS_DIR: each *.json holds one control or a list of them, in the public
    catalogue's seed format (apps/catalogue/backend/controls_seed.json). A file or control that cannot be
    read is skipped with a warning; a slug is taken once, first file (by name) first."""
    folder = Path(os.environ.get("LOCAL_CONTROLS_DIR") or LOCAL_CONTROLS_DIR)
    if not folder.is_dir():
        return []
    out: dict[str, dict] = {}
    for path in sorted(folder.glob("*.json")):
        try:
            found = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("local controls: %s skipped: %s", path.name, exc)
            continue
        for c in found if isinstance(found, list) else [found]:
            if not (isinstance(c, dict) and c.get("slug") and c.get("name") and c.get("questions")):
                logger.warning("local controls: an entry of %s skipped (needs slug, name and questions): %s",
                               path.name, (c.get("slug") if isinstance(c, dict) else None) or c)
                continue
            out.setdefault(c["slug"], c)
    return list(out.values())
