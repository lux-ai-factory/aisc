"""The install's own plugins: the folders of local_plugins/, mounted read-only at LOCAL_PLUGINS_DIR. A folder is
found by the package its pyproject.toml names, and built from a copy that leaves out its git, virtual
environments and old build output, and refuses a link (the build, and the upload after it, must read only the
plugin's own files)."""

import os
import shutil
from pathlib import Path

from plugin_publisher.sources import SourceError, _name_and_version, dist

LOCAL_DIR_ENV = "LOCAL_PLUGINS_DIR"
#: what a copy leaves out, at any depth: tooling state, not the plugin
SKIPPED = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
#: what it leaves out at the top only: build output and virtual environments (a subpackage may be called build)
SKIPPED_AT_TOP = {"dist", "build", "venv", ".venv"}


def _environment_file(name: str) -> bool:
    """.env and .env.*: secrets of the folder's owner, never the plugin's."""
    return name == ".env" or name.startswith(".env.")


class LocalRefused(Exception):
    """Why a local plugin cannot be published, with the status to answer."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def local_folder(package: str) -> Path:
    """The one folder of local_plugins/ whose pyproject.toml names `package` (compared as PEP 503 does)."""
    root = os.environ.get(LOCAL_DIR_ENV)
    if not root or not Path(root).is_dir():
        raise LocalRefused(404, "this install has no local_plugins folder for the publisher (LOCAL_PLUGINS_DIR)")
    found = []
    for folder in sorted(p for p in Path(root).iterdir() if p.is_dir() and not p.is_symlink()):
        pyproject = folder / "pyproject.toml"
        if not pyproject.is_file():
            continue
        try:
            name, _version = _name_and_version(pyproject.read_text(), folder.name)
        except (SourceError, OSError):
            continue
        if dist(name) == dist(package):
            found.append(folder)
    if not found:
        raise LocalRefused(404, f"no folder in local_plugins builds the package {package}")
    if len(found) > 1:
        raise LocalRefused(409, f"more than one folder in local_plugins builds {package}: "
                                f"{', '.join(f.name for f in found)}; keep one")
    return found[0]


def copy_local(folder: Path, dest: Path) -> None:
    """The plugin's own files into dest: no git, virtual environment, build output or .env file, and no link."""
    dest.mkdir(parents=True)
    for here, dirs, files in os.walk(folder):
        here = Path(here)
        dirs[:] = sorted(d for d in dirs if d not in SKIPPED and not (here == folder and d in SKIPPED_AT_TOP))
        files[:] = [f for f in files if not _environment_file(f)]
        for name in dirs + files:
            if (here / name).is_symlink():
                raise LocalRefused(409, f"local_plugins/{folder.name} holds a link, "
                                        f"{(here / name).relative_to(folder)}; replace it with the file itself")
        target = dest / here.relative_to(folder)
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            shutil.copyfile(here / name, target / name, follow_symlinks=False)
