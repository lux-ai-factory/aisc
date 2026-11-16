"""Every image the stack pulls or builds from, in compose and on every FROM line, is named by an exact version and
its sha256 digest, so a rebuild next month runs the bytes that were tested and a moved tag is noticed. A tag alone
or a digest alone is not enough. The staging compose files are upstream's and stay as they are.

Read-only: compose files, Dockerfiles and scripts as text, nothing pulled.
"""

import re

import test_image_policy as policy
from conftest import ROOT

#: upstream's staging files, listed in the upstream coordination note instead of being edited here
UPSTREAM_FILES = ("docker-compose.staging.yml", "docker-compose-infra.staging.yml")


def pinned(image: str) -> bool:
    """name:version@sha256:<64 hex>, the version exact (major.minor.patch, or major.minor where released so)."""
    name, _, digest = image.partition("@sha256:")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        return False
    base, _, tag = name.rpartition(":")
    if not base or "/" in tag:
        return False
    two_part = base in policy.TWO_PART_RELEASES
    return re.match(r"v?\d+\.\d+(?=$|[-_])" if two_part else r"v?\d+\.\d+\.\d+(?=$|[-_])", tag) is not None


def test_the_rule_reads_what_it_should():
    d = "@sha256:" + "0" * 64
    assert pinned("caddy:2.10.2" + d) and pinned("dpage/pgadmin4:9.18" + d)
    assert pinned("ghcr.io/astral-sh/uv:0.9.9-python3.12-alpine" + d)
    assert not pinned("caddy:2.10.2") and not pinned("x" + d) and not pinned("python:3.12-slim" + d)


def test_every_pulled_image_carries_a_version_and_a_digest():
    loose = sorted((f, i) for f, i in policy.third_party_images() if f not in UPSTREAM_FILES and not pinned(i))
    assert loose == [], "pin these as image:version@sha256:digest"


def test_every_base_image_carries_a_version_and_a_digest():
    loose = []
    for dockerfile in policy.dockerfiles():
        stages = policy.stages(dockerfile)
        names = {s.name for s in stages if s.name}
        loose += [(policy.relative(dockerfile), s.base) for s in stages
                  if s.base not in names and s.base != "scratch" and not pinned(s.base)]
    assert sorted(loose) == [], "pin these FROM lines as image:version@sha256:digest"


def test_the_images_the_scripts_pull_are_pinned_too():
    pg = re.search(r"TPG_IMAGE=\$\{TPG_IMAGE:-([^}]+)\}", (ROOT / "scripts/lib/throwaway-pg.sh").read_text()).group(1)
    probe = re.search(r'^PROBE_IMAGE = "([^"]+)"', (ROOT / "scripts/aisc/ports.py").read_text(), re.M).group(1)
    assert pinned(pg), f"the throwaway Postgres runs {pg}"
    assert pinned(probe), f"the port probe runs {probe}"


def test_the_throwaway_postgres_is_the_stacks_image_digest_included():
    import yaml
    stack = yaml.safe_load((ROOT / "docker-compose-infra.development.yml").read_text())["services"]["postgres"]["image"]
    pg = re.search(r"TPG_IMAGE=\$\{TPG_IMAGE:-([^}]+)\}", (ROOT / "scripts/lib/throwaway-pg.sh").read_text()).group(1)
    assert "@sha256:" in stack and pg == stack
