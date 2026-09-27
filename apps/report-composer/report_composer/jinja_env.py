"""The Jinja environment the screens and the error page are drawn with."""
from __future__ import annotations

import os
from pathlib import Path

import jinja2

env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(Path(__file__).resolve().parent / "templates")),
                         autoescape=True)
# The launcher, where the header's mark and "Back" lead, as in the other modules.
env.globals["launcher"] = os.environ.get("LAUNCHER_URL", "http://localhost:8100/").rstrip("/") + "/"
