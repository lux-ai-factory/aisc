"""Which lux-ai-factory repo a test's package is built from.

A test's plugin is published to this stack's package index only when it is installed: the plugin
publisher fetches its repo from github.com/lux-ai-factory, builds it and uploads it. Most packages
are named after their repo; the table lists the ones that are not. The plugin tooling (builder,
integrator, interface, manager) is no test and has no source to install from."""
from __future__ import annotations

import re

#: packages whose name is not their repo's
RENAMED = {
    "data-monitor": "aisc-plugin-data-evaluation",
    "explitest-plugin": "aisc-plugin-explitest",
    "fairness-awareness": "aisc-plugin-fairness",
    "predictive-insights": "aisc-plugin-performance",
}

PLUGIN_TOOLING = {"aisc-plugin-builder", "aisc-plugin-integrator", "aisc-plugin-interface",
                  "aisc-plugin-manager"}

#: the repo names the publisher accepts
ALLOWED_REPO = re.compile(r"^aisc-plugin-[a-z0-9][a-z0-9-]{0,60}$")


def normalised(name: str) -> str:
    """A distribution name as package indexes compare them (PEP 503)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def repo_of(package: str) -> str | None:
    """The lux-ai-factory repo that builds `package`, or None when there is none."""
    name = normalised(package)
    repo = RENAMED.get(name, name)
    if repo in PLUGIN_TOOLING or not ALLOWED_REPO.match(repo):
        return None
    return repo
