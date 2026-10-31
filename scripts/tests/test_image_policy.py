"""The rules every image of the stack keeps, checked over the compose files and every Dockerfile in the checkout.

- Every third-party image, in compose and on a FROM line, carries an exact tag (major.minor.patch, or major.minor
  for an image released that way) or a digest, so a rebuild or a pull next month runs what was tested.
- Every image the stack builds ends as a user other than root: a USER in its last stage, a compose `user:`, or a
  base image known to run unprivileged.
- Every build context has a .dockerignore (or a <Dockerfile>.dockerignore beside its Dockerfile), so a build does
  not send local secrets and virtual environments to the daemon.
- Every Dockerfile is built by one of the compose files, so none rots unseen.

Today's exceptions are listed by name, each with its reason. The test fails on a new violation, and on an
exception that no longer is one, so the list only shrinks. Read-only: nothing is built or pulled.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from conftest import ROOT

COMPOSE_FILES = sorted(ROOT.glob("docker-compose*.yml"))

#: base images whose own last USER is not root
UNPRIVILEGED_BASES = ("nginxinc/nginx-unprivileged",)
#: images whose releases are numbered major.minor, with no patch number: that tag is exact
TWO_PART_RELEASES = ("dpage/pgadmin4",)

FROZEN = "the engine's image (apps/backend, apps/eval, apps/webapp) is upstream's: report only"
#: a submodule's own Dockerfile: pinned there, in a commit of that repository, which takes it off this list
SUBMODULE_BASE = "a submodule's base image: pinned in that repository's own commit"
#: a root Dockerfile's base: pinned in the next root commit that touches it
ROOT_BASE = "a root image's base: pinned in the next root commit that touches its Dockerfile"
#: needs a live start of the service once it runs unprivileged: it may write inside the image or to a volume
#: made by root
NEEDS_A_LIVE_START = "runs as root until a USER is added and the service is started live with it"

#: (file, image) pairs whose tag floats, with why each is allowed for now
FLOATING_TAGS = {
    **{(f, "postgres:15-alpine"): "the stack's Postgres: pinned together with every throwaway bed "
                                  "(test_throwaway_images.py), whose dumps are compared with the stack's"
       for f in ("docker-compose-infra.development.yml", "docker-compose-infra.staging.yml",
                 "docker-compose.development.yml", "docker-compose.engine-standalone.yml")},
    **{("docker-compose.staging.yml", f"ghcr.io/lux-ai-factory/aisc-{name}:wip-plugins"): FROZEN
       for name in ("webapp", "backend", "eval")},
    ("apps/backend/Dockerfile", "ghcr.io/astral-sh/uv:python3.12-alpine"): FROZEN,
    ("apps/eval/Dockerfile", "ghcr.io/astral-sh/uv:python3.12-bookworm-slim"): FROZEN,
    ("apps/eval/Dockerfile.dev", "python:3.12-slim-bookworm"): FROZEN,
    ("apps/webapp/Dockerfile", "node:22-alpine"): FROZEN,
    ("apps/webapp/Dockerfile", "nginx:stable-alpine"): FROZEN,
    ("apps/webapp/Dockerfile.dev", "node:22-alpine"): FROZEN,
    ("apps/catalogue/frontend/Dockerfile", "nginxinc/nginx-unprivileged:1.27-alpine"): SUBMODULE_BASE,
    ("apps/catalogue/frontend/Dockerfile", "node:22-alpine"): SUBMODULE_BASE,
    ("apps/control-objectives/Dockerfile", "python:3.12-slim"): SUBMODULE_BASE,
    ("apps/controls/Dockerfile", "node:20-bookworm-slim"): SUBMODULE_BASE,
    ("apps/controls/services/pdf_renderer/Dockerfile", "python:3.12-slim"): SUBMODULE_BASE,
    ("apps/qualification/Dockerfile", "node:20-alpine"): SUBMODULE_BASE,
    ("apps/qualification/services/agents/Dockerfile.stack", "python:3.12-slim"): SUBMODULE_BASE,
    ("apps/qualification/services/ontology/Dockerfile", "python:3.12-slim"): SUBMODULE_BASE,
    ("apps/qualification/services/prefill/Dockerfile", "python:3.12-slim"): SUBMODULE_BASE,
    ("apps/qualification/services/system_card_renderer/Dockerfile", "python:3.12-slim"): SUBMODULE_BASE,
    ("apps/report-generator/Dockerfile", "python:3.12-slim"): SUBMODULE_BASE,
    ("apps/report-composer/Dockerfile", "python:3.12-slim"): ROOT_BASE,
    ("infra/minio/Dockerfile", "alpine:3.22"): ROOT_BASE,
    ("infra/minio/Dockerfile", "golang:1.24-alpine"): ROOT_BASE,
    ("infra/plugin-publisher/Dockerfile", "python:3.12-slim"): ROOT_BASE,
    ("platform/Dockerfile", "python:3.12-slim-bookworm"): ROOT_BASE,
}

#: services whose image runs as root, with why each is allowed for now
ROOT_USERS = {
    "aisc-backend": FROZEN,
    "aisc-eval-worker": FROZEN,
    "aisc-webapp": FROZEN,
    **{service: NEEDS_A_LIVE_START for service in (
        "minio", "controls-pdf", "controls-web", "qualification-prefill", "qualification-agents",
        "qualification-ontology", "qualification-pdf", "control-objectives", "report-composer", "plugin-publisher",
        "platform", "devpi")},
}

#: build contexts without a .dockerignore, with why each is allowed for now
NO_DOCKERIGNORE = {
    "apps/webapp": FROZEN,
    **{context: "sends the whole folder to the daemon until it has one" for context in (
        "infra/minio", "inspector/schema-docs", "apps/qualification/services/agents", "apps/report-composer",
        "apps/results-dashboard", "platform", "apps/catalogue/devpi")},
}

#: Dockerfiles nothing builds, with why each is kept
UNBUILT: dict[str, str] = {
    "apps/eval/Dockerfile.dev": FROZEN,
    "apps/webapp/Dockerfile.dev": FROZEN,
}


@dataclass(frozen=True)
class Build:
    file: str        # the compose file
    service: str
    context: Path
    dockerfile: Path
    target: str | None
    user: str | None


def with_defaults(text: str) -> str:
    """${NAME:-default} and ${NAME-default} as their defaults, as compose reads them with NAME unset."""
    return re.sub(r"\$\{[A-Z0-9_]+:?-([^}]*)\}", r"\1", text)


def compose_services():
    for path in COMPOSE_FILES:
        for name, service in (yaml.safe_load(path.read_text()).get("services") or {}).items():
            yield path.name, name, service


def builds() -> list[Build]:
    found = []
    for file, name, service in compose_services():
        build = service.get("build")
        if build is None:
            continue
        if isinstance(build, str):
            build = {"context": build}
        context = (ROOT / with_defaults(build.get("context", "."))).resolve()
        found.append(Build(file, name, context, context / build.get("dockerfile", "Dockerfile"), build.get("target"),
                           service.get("user")))
    return found


def third_party_images() -> set[tuple[str, str]]:
    """(compose file, image) of every service that pulls its image rather than building it."""
    return {(file, str(service["image"])) for file, _, service in compose_services()
            if "image" in service and "build" not in service and not str(service["image"]).startswith("aisc-")}


def instructions(dockerfile: Path) -> list[tuple[str, str]]:
    """(INSTRUCTION, its arguments) of each line, continuation lines joined, comments dropped."""
    text = re.sub(r"\\\n", " ", dockerfile.read_text())
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            word, _, rest = line.partition(" ")
            out.append((word.upper(), rest.strip()))
    return out


@dataclass
class Stage:
    name: str | None
    base: str
    user: str | None = None


def stages(dockerfile: Path) -> list[Stage]:
    args, found = {}, []
    for word, rest in instructions(dockerfile):
        if word == "ARG" and not found:
            name, _, default = rest.partition("=")
            args[name.strip()] = default.strip().strip('"')
        elif word == "FROM":
            parts = [p for p in rest.split() if not p.startswith("--")]
            base = re.sub(r"\$\{?([A-Za-z0-9_]+)\}?", lambda m: args.get(m.group(1), m.group(0)), parts[0])
            found.append(Stage(parts[2] if len(parts) > 2 and parts[1].upper() == "AS" else None, base))
        elif word == "USER" and found:
            found[-1].user = rest.split(":")[0]
    return found


def runs_as(stage_list: list[Stage], target: str | None) -> tuple[str | None, str]:
    """(the user the target stage, or the last, runs as, None for the image default; the external base it
    starts from), following FROM <earlier stage>."""
    by_name = {s.name: s for s in stage_list if s.name}
    stage = by_name[target] if target else stage_list[-1]
    user = stage.user
    while stage.base in by_name:
        stage = by_name[stage.base]
        user = user or stage.user
    return user, stage.base


def exact(image: str) -> bool:
    if "@sha256:" in image:
        return True
    name, _, tag = image.rpartition(":")
    if not name or "/" in tag:
        return False
    version = r"v?\d+\.\d+(?=$|[-_])" if name in TWO_PART_RELEASES else r"v?\d+\.\d+\.\d+(?=$|[-_])"
    return re.match(version, tag) is not None


def dockerfiles() -> list[Path]:
    listed = subprocess.run(["git", "ls-files", "--recurse-submodules"], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout.splitlines()
    return [ROOT / p for p in listed if re.search(r"(^|/)Dockerfile[^/]*$", p) and not p.endswith(".dockerignore")]


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def test_every_third_party_image_carries_an_exact_tag():
    floating = {(file, image) for file, image in third_party_images() if not exact(image)}
    for dockerfile in dockerfiles():
        names = {s.name for s in stages(dockerfile) if s.name}
        floating |= {(relative(dockerfile), s.base) for s in stages(dockerfile)
                     if s.base not in names and s.base != "scratch" and not exact(s.base)}
    assert floating - set(FLOATING_TAGS) == set(), "pin these to an exact tag"
    assert set(FLOATING_TAGS) - floating == set(), "pinned now: take them off FLOATING_TAGS"


def test_every_built_image_ends_as_a_user_other_than_root():
    as_root = set()
    for b in builds():
        user, base = runs_as(stages(b.dockerfile), b.target)
        user = b.user or user
        if user in (None, "root", "0") and not base.startswith(UNPRIVILEGED_BASES):
            as_root.add(b.service)
    assert as_root - set(ROOT_USERS) == set(), "give these a USER (or list them in ROOT_USERS with why)"
    assert set(ROOT_USERS) - as_root == set(), "no longer root: take them off ROOT_USERS"


def test_every_build_context_has_a_dockerignore():
    missing = {relative(b.context) for b in builds()
               if not (b.context / ".dockerignore").is_file()
               and not b.dockerfile.with_name(b.dockerfile.name + ".dockerignore").is_file()}
    assert missing - set(NO_DOCKERIGNORE) == set(), "add a .dockerignore to these build contexts"
    assert set(NO_DOCKERIGNORE) - missing == set(), "they have one now: take them off NO_DOCKERIGNORE"


def test_every_dockerfile_is_built_by_compose():
    built = {relative(b.dockerfile) for b in builds()}
    unbuilt = {relative(f) for f in dockerfiles() if relative(f) not in built}
    assert unbuilt - set(UNBUILT) == set(), "build these in compose, or delete them"
    assert set(UNBUILT) - unbuilt == set(), "built now: take them off UNBUILT"


def test_the_policy_reads_what_it_should():
    """The parsing above, on shapes the checkout has: a stage chain, an ARG base, a target, a digest."""
    assert exact("caddy:2.10.2") and exact("dpage/pgadmin4:9.18") and exact("x@sha256:" + "0" * 64)
    assert exact("redis:7.4.11-alpine") and exact("quay.io/oauth2-proxy/oauth2-proxy:v7.13.0")
    assert not exact("redis:7-alpine") and not exact("python:3.12-slim") and not exact("rabbitmq:3-management")
    assert not exact("dpage/pgadmin4:9") and not exact("alpine:3.22")
    assert not exact("localhost:5000/image")
    assert len(builds()) > 10 and third_party_images()
    chain = [Stage("deps", "python:3.12.15-slim", "app"), Stage(None, "deps")]
    assert runs_as(chain, None) == ("app", "python:3.12.15-slim")
    assert runs_as([Stage("a", "node:20.19.5"), Stage("b", "a", "node")], "a") == (None, "node:20.19.5")
