"""The baked stack: docker-compose.baked.yml over the development files, and with the Configurator's files
docker-compose.baked.configurator.yml after it, exactly as scripts/aisc.py lays them with AISC_BAKED=on. In both
modes no service of the Kubernetes stack reads the checkout, each image holds what its service mounted, read-only,
and no image can copy a secret.

The tests marked `images` build the images (the CI job "baked images" runs them); the others only read: `docker
compose config` on copies of the compose files, and a walk of the build contexts.
"""
import functools
import os
import re
import subprocess
from pathlib import Path

import pytest

import compose_cfg
from baked_support import (ALLOWED, MODES, NOT_ON_KUBERNETES, RELOCATED, base_files, bind_mounts, build_contexts,
                           built_image, checkout_files, checkout_mounts, files_of, image_tree, image_user, services,
                           sha256_of)
from conftest import ROOT

SECRET_GLOBS = ["*.key", "env.secrets", "env.runtime", "caddy-tls/*", "postgres-tls/*"]
SKIP_DIRS = {"node_modules", ".git"}


def named_mounts(services: dict) -> set[tuple[str, str, str]]:
    """(service, volume, target) of every named-volume mount."""
    return {(n, v["source"], v["target"]) for n, s in services.items()
            for v in s.get("volumes") or [] if v.get("type") == "volume"}


def _docker_pattern(pat: str) -> re.Pattern:
    """A .dockerignore pattern as a regex over the path from the context root: `*` and `?` stay within one path
    segment, `**` spans segments, and the pattern is anchored at the root."""
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pat.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pat[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pat[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pat[i]), i + 1
    return re.compile(out + r"\Z")


def ignored_by(rules: str, rel: str) -> bool:
    """Whether .dockerignore `rules` leave out the file `rel` (a path from the context root): the last rule that
    matches the path or one of its parent folders wins, and `!` re-includes."""
    parts = rel.split("/")
    prefixes = ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]
    result = False
    for line in rules.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pat = (line[1:] if negate else line).strip().lstrip("/").rstrip("/")
        rx = _docker_pattern(pat)
        if any(rx.match(p) for p in prefixes):
            result = not negate
    return result


def ignored(ctx: Path, path: Path) -> bool:
    """Whether the context's .dockerignore leaves `path` out; no .dockerignore leaves nothing out."""
    f = ctx / ".dockerignore"
    return f.is_file() and ignored_by(f.read_text(), path.relative_to(ctx).as_posix())


def test_dockerignore_rules_follow_docker():
    assert ignored_by("*.key", "a.key") and not ignored_by("*.key", "sub/a.key")
    assert ignored_by("**/*.key", "a.key") and ignored_by("**/*.key", "sub/a.key")
    assert ignored_by("/.venv", ".venv/x") and not ignored_by("/.venv", "sub/.venv/x")
    assert not ignored_by("*.key\n!keep.key", "keep.key") and ignored_by("*.key\n!keep.key", "other.key")


def _walk(ctx: Path, glob: str):
    """Files of ctx matching glob, leaving out node_modules and .git."""
    for dirpath, dirs, files in os.walk(ctx):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for p in Path(dirpath).glob(glob):
            if p.is_file():
                yield p


def copyable_secrets(services: dict) -> dict[Path, list[str]]:
    """Per build context, the secret files a build could copy. Docker reads a .dockerignore for a service's main
    context only: every file of an additional context can be copied."""
    out = {}
    for ctx, main in build_contexts(services):
        assert ctx != ROOT, "the repository root is never a build context: name the folder"
        exposed = sorted({p.relative_to(ctx).as_posix() for g in SECRET_GLOBS for p in _walk(ctx, g)
                          if not (main and ignored(ctx, p))})
        if exposed:
            out[ctx] = exposed
    return out


def test_an_additional_context_has_no_dockerignore_and_the_settings_with_secrets_count(tmp_path):
    for folder in ("main", "extra"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / ".dockerignore").write_text("*.key\nenv.*\n")
        (tmp_path / folder / "a.key").write_text("k")
        (tmp_path / folder / "env.runtime").write_text("POSTGRES_PASSWORD=x")
    found = copyable_secrets({"s": {"build": {"context": str(tmp_path / "main"),
                                              "additional_contexts": {"extra": str(tmp_path / "extra")}}}})
    assert found == {tmp_path / "extra": ["a.key", "env.runtime"]}


def test_aisc_lays_the_baked_overlays_after_every_other_file():
    dev = ["docker-compose-infra.development.yml", "docker-compose.development.yml"]
    assert list(files_of("development")) == [*dev, "docker-compose.baked.yml"]
    assert list(files_of("configurator")) == [*dev, "docker-compose.https.yml", "docker-compose.configurator.yml",
                                              "docker-compose.baked.yml", "docker-compose.baked.configurator.yml"]


@pytest.mark.parametrize("mode", MODES)
def test_no_service_reads_the_checkout_in_the_baked_stack(mode):
    left = {(n, src.split("/")[0]) for n, s in services(mode).items() if n not in NOT_ON_KUBERNETES
            for src in checkout_mounts(s)} - set(ALLOWED)
    assert left == set()


@pytest.mark.parametrize("mode", MODES)
def test_the_overlay_keeps_every_state_volume(mode):
    assert named_mounts(services(mode, baked=False)) == named_mounts(services(mode))


@pytest.mark.parametrize("mode", MODES)
def test_no_build_context_can_copy_secrets(mode):
    assert copyable_secrets(services(mode)) == {}


#: the services of the Kubernetes stack that are made self-contained, grown by each step of Plan 1
BAKED_SERVICES = ["control-objectives", "control-objectives-migrate", "report-composer",
                  "report-composer-migrate", "plugin-publisher", "platform", "report-renderer", "dashboard", "dashboard-migrate",
                  "postgres", "postgres-setup", "report-grants", "keycloak", "rabbitmq", "rabbitmq-setup", "caddy"]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", BAKED_SERVICES)
def test_reads_no_checkout_file(mode, name):
    s = services(mode)[name]
    assert {m.split("/")[0] for m in checkout_mounts(s)} <= {src for (svc, src) in ALLOWED if svc == name}


def test_the_configurator_gateway_runs_the_configurator_caddyfile_the_image_holds():
    caddy = services("configurator")["caddy"]
    command = caddy["command"] if isinstance(caddy["command"], str) else " ".join(caddy["command"])
    assert f"--config {RELOCATED[('configurator', 'caddy', '/etc/caddy/Caddyfile')]}" in command
    assert not services("development")["caddy"].get("command"), "the development gateway runs the image's default"


def base_mounts(mode: str, name: str) -> list[tuple[str, str]]:
    """(source, target in the image) of every bind mount of the service in the base stack that the baked image
    must hold: all but the allowed ones."""
    return [(src, RELOCATED.get((mode, name, target), target))
            for src, target in bind_mounts(services(mode, baked=False)[name])
            if (name, src.split("/")[0]) not in ALLOWED]


@pytest.mark.images
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", BAKED_SERVICES)
def test_the_image_holds_every_file_its_service_mounted(mode, name):
    """What the base stack mounts, the image holds at the same place with the same bytes: a file by its SHA-256, a
    folder by each file Git does not ignore and its SHA-256."""
    image = built_image(name, mode)
    missing = {}
    for src, target in base_mounts(mode, name):
        held = {rel: digest for rel, (digest, _, _) in image_tree(image, target).items()}
        wrong = sorted(rel for rel, digest in checkout_files(ROOT / src).items() if held.get(rel) != digest)
        if wrong:
            missing[f"{src} -> {target}"] = wrong[:10]
    assert missing == {}


@pytest.mark.images
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("name", BAKED_SERVICES)
def test_the_files_an_image_holds_for_its_mounts_are_read_only(mode, name):
    """No user but root can write the files that came from the checkout, nor the folders they are in: no group or
    other write bit, and the owner's only when it is root. A folder target itself, and what the upstream image keeps
    beside the checkout's files, keep the upstream image's modes."""
    image = built_image(name, mode)
    writable = {}
    for src, target in base_mounts(mode, name):
        ours = set(checkout_files(ROOT / src))
        ours |= {"/".join(rel.split("/")[:i]) for rel in ours for i in range(1, rel.count("/") + 1)}
        folder = (ROOT / src).is_dir()
        bad = sorted(rel for rel, (_, mode_bits, uid) in image_tree(image, target).items()
                     if rel in ours and not (folder and rel == ".")
                     and (mode_bits & 0o022 or (uid != 0 and mode_bits & 0o200)))
        if bad:
            writable[target] = bad[:10]
    assert writable == {}


@pytest.mark.images
def test_the_platform_image_holds_no_adapters():
    """The operator's protocol adapters are per install: mounted, never baked into an image that may be shared."""
    assert image_tree(built_image("platform"), "/app/adapters") == {}


#: (service, image) of every wrapper around an upstream image
WRAPPERS = [("postgres", "aisc-postgres"), ("postgres-setup", "aisc-postgres-setup"),
            ("report-grants", "aisc-report-grants"), ("keycloak", "aisc-keycloak"),
            ("rabbitmq", "aisc-rabbitmq"), ("rabbitmq-setup", "aisc-rabbitmq-setup"), ("caddy", "aisc-gateway")]


#: the wrappers that run as an unprivileged user instead of upstream's (root): the one-shot jobs
ONE_SHOT_USERS = {"postgres-setup": "postgres", "report-grants": "postgres", "rabbitmq-setup": "65534"}


@pytest.mark.images
@pytest.mark.parametrize("service,wrapper", WRAPPERS)
def test_a_wrapper_keeps_the_upstream_user(service, wrapper):
    image = built_image(service)
    assert image.startswith(f"{wrapper}:")
    # the three one-shot clients need no root, so their stages set a user of their own; every other wrapper keeps
    # upstream's
    expected = ONE_SHOT_USERS.get(service) or image_user(services("development", baked=False)[service]["image"])
    assert image_user(image) == expected


def test_the_gateway_copy_of_the_caddyfile_is_the_root_one():
    assert sha256_of(ROOT / "Caddyfile") == sha256_of(ROOT / "infra/caddy/Caddyfile.development"), \
        "after editing the root Caddyfile, copy it over infra/caddy/Caddyfile.development"


#: (service, Dockerfile, stage) of every wrapper
WRAPPER_FILES = [("postgres", "infra/postgres/Dockerfile", "postgres"), ("postgres-setup", "infra/postgres/Dockerfile", "setup"),
                 ("report-grants", "infra/postgres/Dockerfile", "report-grants"),
                 ("keycloak", "infra/keycloak/Dockerfile", None), ("rabbitmq", "infra/rabbitmq/Dockerfile", None),
                 ("rabbitmq-setup", "infra/rabbitmq/Dockerfile.setup", None), ("caddy", "infra/caddy/Dockerfile", None)]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("service,dockerfile,stage", WRAPPER_FILES)
def test_a_wrapper_starts_from_the_image_the_compose_files_pin(mode, service, dockerfile, stage):
    froms = re.findall(r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", (ROOT / dockerfile).read_text(), re.M | re.I)
    refs = [ref for ref, name in froms if stage is None or name == stage]
    assert refs == [services(mode, baked=False)[service]["image"]]


#: the named contexts a build needs whatever the stack (the report renderer's report plugin interface)
NEEDED_CONTEXTS = {"apps/report-generator": {"interface": "shared/report-plugin-interface"}}


@functools.cache
def stand_in_image(context: str) -> str:
    """The context built as the development stack builds it: without the baked overlay's named contexts."""
    tag = f"aisc-t-standin-{context.split('/')[-1]}:test"
    extra = [a for name, folder in NEEDED_CONTEXTS.get(context, {}).items()
             for a in ("--build-context", f"{name}={ROOT / folder}")]
    built = subprocess.run(["docker", "build", "-q", "-t", tag, *extra, str(ROOT / context)],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr[-2000:]
    return tag


#: (build context, module of a Python stand-in, PYTHONPATH it is found on) of every stand-in a build without the
#: baked overlay's named contexts gets
STAND_INS = [
    ("apps/control-objectives", "aisc_identity", "/app/shared/identity"),
    ("apps/control-objectives", "aisc_redact", "/app/shared/identity"),
    ("apps/control-objectives", "aisc_service_client", "/app/shared/identity"),
    ("apps/report-composer", "aisc_identity", "/app/shared/identity"),
    ("apps/report-composer", "aisc_service_client", "/app/shared/identity"),
    ("apps/results-dashboard", "aisc_identity", "/app/pythonpath_identity"),
    ("apps/results-dashboard", "gateway_identity", "/app/pythonpath_gateway"),
    ("apps/results-dashboard", "superset_gateway_config", "/app/pythonpath_gateway"),
    ("infra/plugin-publisher", "aisc_plugin_interface", "/interface/src"),
]


@pytest.mark.images
@pytest.mark.parametrize("context,module,path", STAND_INS)
def test_a_stand_in_fails_loudly_on_import_and_names_the_overlay(context, module, path):
    """Built without the named contexts (the development build, which mounts the real code over the stand-ins), the
    image's stand-in raises ImportError naming docker-compose.baked.yml instead of importing as an empty module."""
    r = subprocess.run(["docker", "run", "--rm", "-e", f"PYTHONPATH={path}", "--entrypoint", "python",
                        stand_in_image(context), "-c",
                        f"import {module}"], capture_output=True, text=True)
    assert r.returncode != 0 and "ImportError" in r.stderr and "docker-compose.baked.yml" in r.stderr, r.stderr[-1500:]


#: (build context, file in the image) of every data stand-in: no module to import, so it holds a line naming the
#: overlay instead of nothing
DATA_STAND_INS = [("apps/report-generator", "/data/airo_vocab.json"), ("apps/report-generator", "/data/vair_vocab.json"),
                  ("apps/report-generator", "/data/ai_act_control_objectives.csv"),
                  ("infra/plugin-publisher", "/interface/pyproject.toml")]


@pytest.mark.images
@pytest.mark.parametrize("context,inside", DATA_STAND_INS)
def test_a_data_stand_in_names_the_overlay(context, inside):
    r = subprocess.run(["docker", "run", "--rm", "--entrypoint", "cat", stand_in_image(context), inside],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "docker-compose.baked.yml" in r.stdout, r.stdout + r.stderr
