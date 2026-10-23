"""Where a plugin's source is: which repos may be fetched, which branch, and what its pyproject.toml
names and versions."""

import os
import re
import tomllib
from pathlib import Path

from plugin_publisher.git import NO_TOKEN_FAILURE, StepFailed, git, has_github_token

DEFAULT_GITHUB_BASE = "https://github.com/lux-ai-factory"

# Only the organisation's plugin repos can be fetched on a request, never an arbitrary URL.
ALLOWED_REPO = re.compile(r"aisc-plugin-[a-z0-9][a-z0-9-]{0,60}")

# Every AISC change is made on feat/unified-modules: a repo that has that branch is built from it,
# one that doesn't (yet) from its default branch.
BRANCH = "feat/unified-modules"


class NotAllowed(ValueError):
    pass


class SourceError(Exception):
    """A step on a repo failed; the message names the step and the repo, output is the tool's."""

    def __init__(self, step: str, repo: str, output: str):
        super().__init__(f"could not {step} {repo}")
        self.step, self.repo, self.output = step, repo, output


def dist(name: str) -> str:
    """A distribution name as PEP 503 compares them (wheels write data-monitor as data_monitor)."""
    return re.sub(r"[-_.]+", "-", name).lower()


# These match the pattern but are the plugin tooling, not plugins (the old downloader left them out
# too); the interface is published only from the copy bundled with the stack.
TOOLING_REPOS = {"aisc-plugin-builder", "aisc-plugin-integrator", "aisc-plugin-interface",
                 "aisc-plugin-manager"}


def check_allowed(repo) -> str:
    if not isinstance(repo, str) or not ALLOWED_REPO.fullmatch(repo):
        raise NotAllowed(f"{repo!r} is not a plugin repo of the organisation")
    if repo in TOOLING_REPOS:
        raise NotAllowed(f"{repo} is plugin tooling, not a plugin")
    return repo


def repo_url(repo: str) -> str:
    base = os.environ.get("GITHUB_BASE") or DEFAULT_GITHUB_BASE
    return f"{base.rstrip('/')}/{check_allowed(repo)}.git"


def clone(repo: str, dest: Path, checkout: bool = True) -> str:
    """Shallow-clones the repo's head into dest and returns the branch it came from. Without
    checkout only the history is fetched, no file content, and no working tree is written."""
    url = repo_url(repo)
    try:
        found = git("ls-remote", "--exit-code", "--heads", url, BRANCH, url=url)
        branch = BRANCH if found.returncode == 0 else None
        light = [] if checkout else ["--filter=blob:none", "--no-checkout"]
        cloned = git("clone", "-q", "--depth", "1", *light,
                     *(["--branch", branch] if branch else []), "--", url, str(dest), url=url)
        if cloned.returncode != 0:
            raise StepFailed(NO_TOKEN_FAILURE if not has_github_token()
                             else cloned.stderr + cloned.stdout)
        if branch is None:
            head = git("rev-parse", "--abbrev-ref", "HEAD", url=url, cwd=dest)
            branch = head.stdout.strip() if head.returncode == 0 else "HEAD"
    except StepFailed as exc:
        raise SourceError("clone", repo, exc.output) from None
    return branch


def _name_and_version(text: str, label: str) -> tuple[str, str]:
    try:
        project = tomllib.loads(text)["project"]
        return project["name"], project["version"]
    except (KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise SourceError("read the pyproject.toml of", label, f"{type(exc).__name__}: {exc}") from None


def read_project(folder: Path, label: str) -> tuple[str, str]:
    """The [project] name and version of the pyproject.toml in folder."""
    try:
        text = (Path(folder) / "pyproject.toml").read_text()
    except OSError as exc:
        raise SourceError("read the pyproject.toml of", label, f"{type(exc).__name__}: {exc}") from None
    return _name_and_version(text, label)


def read_source(repo: str, dest: Path) -> tuple[str, str, str]:
    """(branch, package, version) at the head of the repo, read without checking out its tree:
    a clone with no blobs and no checkout into dest, then pyproject.toml alone from git."""
    branch = clone(repo, dest, checkout=False)
    url = repo_url(repo)
    shown = git("show", "HEAD:pyproject.toml", url=url, cwd=dest)
    if shown.returncode != 0:
        raise SourceError("read the pyproject.toml of", repo, shown.stderr + shown.stdout)
    package, version = _name_and_version(shown.stdout, repo)
    return branch, package, version


def artefact_name(filename: str) -> str:
    """The distribution a built file is of: wheels are name-version-tags.whl, sdists
    name-version.tar.gz."""
    if filename.endswith(".whl"):
        return filename.split("-")[0]
    stem = re.sub(r"\.(tar\.gz|zip)$", "", filename)
    return stem.rsplit("-", 1)[0]

