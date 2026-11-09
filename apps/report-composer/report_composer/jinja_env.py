"""The Jinja environment the screens and the error page are drawn with."""
from __future__ import annotations

import hashlib
import os
from functools import cache
from pathlib import Path

import jinja2

env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
                         autoescape=True)
# The launcher, where the header's mark and "Back" lead, as in the other modules.
env.globals["launcher"] = os.environ.get("LAUNCHER_URL", "http://localhost:8100/").rstrip("/") + "/"


@cache
def asset(name: str) -> str:
    """The path of a file under static/ with a hash of its content (?v=), so a browser that kept an older copy
    fetches the new one after a deploy. Read once per process: a deploy restarts it."""
    digest = hashlib.sha256((Path(__file__).resolve().parent / "static" / name).read_bytes()).hexdigest()[:12]
    return f"/static/{name}?v={digest}"


env.globals["asset"] = asset
