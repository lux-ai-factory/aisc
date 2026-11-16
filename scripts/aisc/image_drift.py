"""drift: which running containers of the stack no longer run what their image holds (read-only)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .docker import DOCKER_CALL_WAIT_S, docker_in_time, find_docker
from .settings import NO_DOCKER, Refused, project, say


#: where an image we build keeps its code, besides the image's own working folder
APP_FOLDERS = ("/app", "/aisc", "/srv", "/usr/share/nginx/html", "/etc/nginx")
#: what a file of code ends in: a changed folder, data file or log is not code
CODE_SUFFIXES = frozenset({".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".html", ".htm", ".j2",
                           ".jinja", ".jinja2", ".conf", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".sh", ".sql"})
#: what a running service writes into its app folders by itself: bytecode, the venv uv syncs, caches, logs, tmp
NOT_CODE = re.compile(r"(^|/)(__pycache__|\.venv|node_modules|\.cache|\.npm|logs?|tmp)(/|$)|\.(pyc|log)$")
#: an image whose name starts so is built from this checkout; any other is an upstream image, used as published
OWN_IMAGE = "aisc-"
DIFF_WAIT_S = 120


#: files an image of ours rewrites itself at every start, so `docker diff` always shows them changed: the webapp's
#: env.sh (in /docker-entrypoint.d) writes the deployment mode into its config and its bundle. A copy made by hand of
#: these same files cannot be told apart from that rewrite.
WRITTEN_AT_START = {"aisc-webapp": re.compile(r"^(/etc/nginx/conf\.d/default\.conf|/usr/share/nginx/html/assets/index-[^/]+\.js)$")}


def written_at_start(image: str, line: str) -> bool:
    """A change (C) the image's own start-up makes, not drift."""
    rule = WRITTEN_AT_START.get(image.split(":")[0].split("/")[-1])
    return bool(rule) and line.startswith("C ") and bool(rule.match(line[2:]))


def code_path(path: str, workdir: str, mounts: list[str]) -> bool:
    """A file of code inside the image's app folders (APP_FOLDERS and its working folder), not one a bind mount
    brings from the tree, and not one the service writes by itself (NOT_CODE)."""
    def under(folder: str) -> bool:
        return path == folder or path.startswith(folder.rstrip("/") + "/")

    folders = [*APP_FOLDERS, *([workdir] if workdir not in ("", "/") else [])]
    return (any(under(f) for f in folders) and not any(under(m) for m in mounts)
            and not NOT_CODE.search(path) and Path(path).suffix in CODE_SUFFIXES)


def drift(args: list[str]) -> None:
    """Which running containers of the stack no longer run what their image holds. Read-only: docker ps, inspect
    and diff only. Reports, per container of an image built here (named aisc-...):
      - code docker diff shows changed (C), added (A) or deleted (D) since the image: files ending in a code
        suffix (CODE_SUFFIXES) under /app, /aisc, /srv, /usr/share/nginx/html, /etc/nginx or the image's working
        folder; not __pycache__/*.pyc, .venv, node_modules, .cache, .npm, *.log and log folders, tmp folders,
        nor anything under a bind mount (code mounted from the tree runs as the tree is: nothing to report);
      - containers made from one image name that run different image ids (one was made before a rebuild).
    Upstream images (keycloak, postgres, pgadmin ...) are listed, not checked: their entrypoints write files. Files
    one of our images rewrites at every start (WRITTEN_AT_START: the webapp's config and bundle) are not drift.
    Exit 0 when nothing drifted, 1 otherwise.
        uv run scripts/aisc.py drift [--prefix STACK]   (default: this checkout's stack)"""
    stack = project()
    rest = list(args)
    while rest:
        option = rest.pop(0)
        if option == "--prefix" and rest:
            stack = rest.pop(0)
        else:
            raise Refused(f"aisc.py drift: unknown option {option}; usage: aisc.py drift [--prefix STACK]", 2)
    docker_command = find_docker()
    if docker_command is None:
        raise Refused(NO_DOCKER)
    listed = docker_in_time([docker_command, "ps", "--filter", f"label=com.docker.compose.project={stack}",
                             "--format", "{{.Names}}"], DOCKER_CALL_WAIT_S)
    if listed is None or listed.returncode != 0:
        raise Refused(f"Docker did not list the containers of stack {stack}")
    names = sorted(listed.stdout.split())
    if not names:
        raise Refused(f"stack {stack} has no running container: nothing to compare")
    inspected = docker_in_time([docker_command, "inspect", *names], DOCKER_CALL_WAIT_S)
    if inspected is None or inspected.returncode != 0:
        raise Refused(f"Docker did not inspect the containers of stack {stack}")
    containers = {c["Name"].lstrip("/"): c for c in json.loads(inspected.stdout)}

    rows: list[tuple[str, str, str, list[str]]] = []
    drifted: set[str] = set()
    by_image: dict[str, dict[str, list[str]]] = {}
    for name in names:
        c = containers[name]
        image, image_id = c["Config"]["Image"], c["Image"].removeprefix("sha256:")[:12]
        if not image.startswith(OWN_IMAGE):
            rows.append((name, image, "upstream image, not checked", []))
            continue
        by_image.setdefault(image, {}).setdefault(image_id, []).append(name)
        diff = docker_in_time([docker_command, "diff", name], DIFF_WAIT_S)
        if diff is None or diff.returncode != 0:
            rows.append((name, image_id, "docker diff did not answer", []))
            drifted.add(name)
            continue
        mounts = [m["Destination"] for m in c.get("Mounts") or []]
        workdir = c["Config"].get("WorkingDir") or ""
        changed = [line for line in diff.stdout.splitlines()
                   if line[:2] in ("C ", "A ", "D ") and code_path(line[2:], workdir, mounts)
                   and not written_at_start(image, line)]
        if changed:
            drifted.add(name)
        rows.append((name, image_id, f"{len(changed)} code paths differ from the image" if changed else "ok", changed))

    split = {image: ids for image, ids in by_image.items() if len(ids) > 1}
    for ids in split.values():
        drifted.update(n for members in ids.values() for n in members)

    width, image_width = max(len(n) for n in names) + 2, max(len(r[1]) for r in rows) + 2
    say(f"Drift of stack {stack}: running containers against their images", "",
        f"{'container':<{width}}{'image':<{image_width}}state")
    for name, image, state, changed in rows:
        say(f"{name:<{width}}{image:<{image_width}}{state}", *(f"    {line}" for line in sorted(changed)))
    for image, ids in sorted(split.items()):
        say("", f"{image} runs as {len(ids)} different images:",
            *(f"    {image_id}  {', '.join(members)}" for image_id, members in sorted(ids.items())))
    say("", f"{len(drifted)} of {len(names)} containers drifted." if drifted else "No container drifted.")
    if drifted:
        raise Refused("aisc.py drift: the containers above do not run what their image holds", 1)
