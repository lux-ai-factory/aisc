"""Helpers for the tests of the baked stack: docker-compose.baked.yml over the development files, and with the
Configurator's files docker-compose.baked.configurator.yml after it, exactly as scripts/aisc.py lays them.

A baked image holds its own code and configuration; these helpers find what a service still reads from the
checkout, and build and inspect images.
"""
from __future__ import annotations

import functools
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import compose_cfg
from conftest import ROOT, copy_install_scripts

#: the two ways the stack runs: the development files alone, and with the Configurator's (start --configurator)
MODES = ("development", "configurator")
#: the overlays the baked stack adds; the files before them are the base stack it is compared with
OVERLAYS = ("docker-compose.baked.yml", "docker-compose.baked.configurator.yml")
#: the settings each mode reads
SETTINGS = {"development": compose_cfg.SETTINGS, "configurator": ROOT / "env.configurator.example"}
#: the tag the tests build under, never the stack's own :latest
TEST_TAG = "baked-test"

_WORKER_MOUNTS = ["aisc-backend", "aisc-backend-migrate", "aisc-eval-declarations-worker", "aisc-eval-worker", "aisc-eval-flower", "plugin-publisher"]

#: (service, top-level source) -> why it may stay mounted in the baked stack
ALLOWED: dict[tuple[str, str], str] = {
    ("immudb-key", "immudb-signing.key"): "a secret; a Kubernetes Secret holds it",
    ("platform", "immudb-signing.pub"): "per install; a ConfigMap holds it",
    ("postgres-tls", "postgres-tls"): "key material; a Kubernetes Secret holds it",
    ("caddy", "caddy-tls"): "certificates; TLS ends at the load balancer on Kubernetes",
    ("platform", "local_controls"): "per install; copied from a bucket",
    ("platform", "adapters"): "per install; Plan 3 copies it from a bucket",
    **{(s, "local_plugins"): "per install; copied from a bucket" for s in _WORKER_MOUNTS},
}

#: services that exist for a developer's machine only
NOT_ON_KUBERNETES: set[str] = {"pgadmin", "schema-docs"}

#: (mode, service, target of a base mount) -> where the baked image holds that file instead, and the service runs
#: it from there: the gateway image's /etc/caddy/Caddyfile is the development one, and
#: docker-compose.baked.configurator.yml starts Caddy on the Configurator's
RELOCATED = {("configurator", "caddy", "/etc/caddy/Caddyfile"): "/etc/caddy/Caddyfile.configurator"}


@functools.cache
def files_of(mode: str) -> tuple[str, ...]:
    """The compose files scripts/aisc.py runs with AISC_BAKED=on in this mode, read from its COMPOSE in a scratch
    copy of the checkout (a fresh process, so no other test's state reaches it)."""
    with tempfile.TemporaryDirectory() as d:
        folder = Path(d)
        copy_install_scripts(folder)
        if mode == "configurator":
            shutil.copy(ROOT / "env.configurator.example", folder / "env.configurator")
        code = ("import importlib.util, json, sys\n"
                "s = importlib.util.spec_from_file_location('aisc_install', 'scripts/aisc.py')\n"
                "m = importlib.util.module_from_spec(s); sys.modules['aisc_install'] = m; s.loader.exec_module(m)\n"
                f"{'m.settings.use_configurator()' if mode == 'configurator' else ''}\n"
                "c = m.settings.COMPOSE\n"
                "print(json.dumps([c[i + 1] for i, a in enumerate(c) if a == '-f']))\n")
        env = {k: v for k, v in os.environ.items()
               if k not in ("CADDY_DOMAIN", "AISC_ADMIN_PORTS") and not k.endswith("_HOST")}
        r = subprocess.run([sys.executable, "-c", code], cwd=folder, env={**env, "AISC_BAKED": "on"},
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
        return tuple(json.loads(r.stdout.strip().splitlines()[-1]))


def base_files(mode: str) -> list[str]:
    """The same files without the baked overlays: the stack the baked one stands in for."""
    return [f for f in files_of(mode) if f not in OVERLAYS]


@functools.cache
def _config(mode: str, baked: bool) -> str:
    with tempfile.TemporaryDirectory() as d:
        resolved = compose_cfg.config(Path(d), files=list(files_of(mode)) if baked else base_files(mode),
                                      settings_file=SETTINGS[mode])
    return json.dumps(resolved)


def services(mode: str, baked: bool = True) -> dict:
    """The resolved services of the baked stack (or of its base) in this mode; fails with compose's message when
    the files do not resolve."""
    return json.loads(_config(mode, baked))["services"]


def checkout_mounts(service: dict) -> list[str]:
    """The bind sources of one service, relative to the checkout; the install's plugin folder reads as local_plugins."""
    return [source for source, _ in bind_mounts(service)]


def bind_mounts(service: dict) -> list[tuple[str, str]]:
    """(source relative to the checkout, target) of every bind mount; the install's plugin folder reads as
    local_plugins."""
    out = []
    for v in service.get("volumes") or []:
        if v.get("type") != "bind":
            continue
        src = Path(v["source"])
        try:
            out.append((str(src.relative_to(ROOT)), v["target"]))
        except ValueError:
            out.append(("local_plugins" if str(v.get("target", "")).startswith(("/app/plugins", "/srv/private/local-plugins"))
                        else str(src), v["target"]))
    return out


def _compose(mode: str) -> tuple[list[str], dict]:
    base = ["docker", "compose", "-p", "aisc-t-baked", "--project-directory", str(ROOT),
            "--env-file", str(SETTINGS[mode]), *[a for f in files_of(mode) for a in ("-f", str(ROOT / f))]]
    # compose wants a value for every secret the files demand, though a build uses none of them; the tag is the
    # tests' own, so the stack's :latest images are never replaced
    env = {**os.environ, **{k: "dummy" for k in compose_cfg.required(files_of(mode))}, "AISC_IMAGE_TAG": TEST_TAG}
    return base, env


@functools.cache
def built_image(service: str, mode: str = "development") -> str:
    """Builds the service with the baked files of this mode and returns its image name."""
    base, env = _compose(mode)
    built = subprocess.run([*base, "build", service], capture_output=True, text=True, env=env)
    if built.returncode:
        raise RuntimeError(f"building {service} failed:\n{built.stderr[-3000:]}")
    out = subprocess.run([*base, "config", "--format", "json"], check=True, capture_output=True, text=True, env=env)
    image = json.loads(out.stdout)["services"][service]["image"]
    assert image.endswith(f":{TEST_TAG}"), image
    return image


@functools.cache
def image_tree(image: str, path: str) -> dict[str, tuple[str | None, int, int]]:
    """What an image holds at `path`: relative name -> (SHA-256, mode, uid) of every file and folder under it
    ("." for `path` itself), read from a created, never started, container. Empty when the path is absent."""
    cid = subprocess.run(["docker", "create", image], check=True, capture_output=True, text=True).stdout.strip()
    try:
        r = subprocess.run(["docker", "cp", f"{cid}:{path}", "-"], capture_output=True)
    finally:
        subprocess.run(["docker", "rm", cid], capture_output=True)
    if r.returncode:
        return {}
    out = {}
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as tar:
        for m in tar.getmembers():
            rel = m.name.split("/", 1)[1] if "/" in m.name else "."
            digest = hashlib.sha256(tar.extractfile(m).read()).hexdigest() if m.isfile() else None
            out[rel] = (digest, m.mode, m.uid)
    return out


def image_file_sha256(image: str, path: str) -> str | None:
    """The SHA-256 of a file inside an image, None when the file is absent."""
    return image_tree(image, path).get(".", (None,))[0]


def checkout_files(source: Path) -> dict[str, str]:
    """A mount's source as the image must hold it: relative name -> SHA-256 of each file Git does not ignore
    (tracked or not; a local environment such as .venv is not part of it), leaving out __pycache__ and .git.
    A file reads as {".": its SHA-256}."""
    if source.is_file():
        return {".": sha256_of(source)}
    listed = subprocess.run(["git", "-C", str(source), "ls-files", "-co", "--exclude-standard", "-z", "."],
                            check=True, capture_output=True, text=True).stdout.split("\0")
    out = {}
    for rel in filter(None, listed):
        parts = rel.split("/")
        if "__pycache__" in parts or ".git" in parts or not (source / rel).is_file() or (source / rel).is_symlink():
            continue
        out[rel] = sha256_of(source / rel)
    return out


def image_user(image: str) -> str:
    """The user an image runs as; an upstream image that is not here yet is pulled first."""
    if subprocess.run(["docker", "image", "inspect", image], capture_output=True).returncode:
        subprocess.run(["docker", "pull", "-q", image], check=True, capture_output=True)
    r = subprocess.run(["docker", "image", "inspect", "-f", "{{.Config.User}}", image],
                       check=True, capture_output=True, text=True)
    return r.stdout.strip()


def sha256_of(path: Path) -> str:
    """The hex SHA-256 of a file of the checkout."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_contexts(services: dict) -> list[tuple[Path, bool]]:
    """(folder, whether it is a service's main build context) of every build context and additional context,
    resolved under the checkout. Docker applies a .dockerignore to the main context only."""
    out = set()
    for s in services.values():
        b = s.get("build")
        if not b:
            continue
        for c, main in [(b.get("context"), True), *[(a, False) for a in (b.get("additional_contexts") or {}).values()]]:
            if c and not str(c).startswith(("docker-image://", "service:", "http", "target:")):
                p = Path(c)
                out.add((p if p.is_absolute() else (ROOT / p).resolve(), main))
    return sorted(out)
