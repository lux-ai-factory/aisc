"""docs/architecture.md says what AISC is made of and what each step of an assessment is for; one appendix per
step (and one for Manage) gives the details. Every link between them resolves."""
import re

import pytest

from conftest import ROOT

ARCHITECTURE = ROOT / "docs/architecture.md"
APPENDICES = ROOT / "docs/appendices"
STEPS = {
    "1-qualify.md": "Qualify the AI system",
    "2-control-objectives.md": "Set control objectives",
    "3-tests-and-checklists.md": "Choose tests and checklists",
    "4-collect-evidence.md": "Collect evidence",
    "manage.md": "Manage",
}
DOCS = [ARCHITECTURE] + [APPENDICES / name for name in STEPS]


def anchors(path):
    """GitHub's anchors for the headings of a Markdown file."""
    return {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
            for h in re.findall(r"^#+ (.+)$", path.read_text(), re.M)}


def test_each_step_has_its_appendix_and_the_architecture_links_to_it():
    text = ARCHITECTURE.read_text()
    for name, title in STEPS.items():
        appendix = APPENDICES / name
        assert appendix.exists(), name
        assert title in appendix.read_text().splitlines()[0], name
        assert f"appendices/{name}" in text, name
        assert title in text, title


def test_the_architecture_names_every_service_it_runs_by_its_compose_name():
    compose = (ROOT / "docker-compose.development.yml").read_text() + \
        (ROOT / "docker-compose-infra.development.yml").read_text()
    named = set(re.findall(r"`([a-z0-9-]+)`", ARCHITECTURE.read_text()))
    for service in ("platform", "aisc-backend", "aisc-eval-worker", "plugin-publisher", "devpi", "catalogue-private",
                    "qualification-web", "control-objectives", "controls-web", "report-composer", "report-renderer",
                    "dashboard", "caddy", "keycloak", "oauth2-proxy", "postgres", "immudb", "minio"):
        assert service in named, service
        assert re.search(rf"^  {re.escape(service)}:", compose, re.M), service


@pytest.mark.parametrize("doc", DOCS, ids=[d.name for d in DOCS])
def test_every_local_link_resolves(doc):
    if not doc.exists():
        pytest.fail(f"{doc.relative_to(ROOT)} is missing")
    for target in re.findall(r"\]\((?!https?://|mailto:)([^)\s]+)\)", doc.read_text()):
        path, _, anchor = target.partition("#")
        file = (doc.parent / path).resolve() if path else doc
        assert file.exists(), (doc.name, target)
        if anchor and file.suffix == ".md":
            assert anchor in anchors(file), (doc.name, target)
