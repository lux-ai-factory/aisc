"""Every image the stack builds runs as a user other than root, except two that need root for a stated reason, and
every build context keeps local files out of the build with a .dockerignore.

The image policy's own exception lists shrink as images are fixed; this file states where they end. Read-only:
Dockerfiles and compose files as text, nothing built.
"""

import test_image_policy as policy

PER_RUN_UID = "switches to a uid of its own for each run, which only root can do"
BUILDS_AS_ANOTHER_USER = "builds each plugin as an unprivileged builder user, which only root can switch to"

#: the only services left running as root, with why
ROOT_USERS = {"aisc-eval-worker": PER_RUN_UID, "plugin-publisher": BUILDS_AS_ANOTHER_USER}
#: services that run one of those images rather than a third: the declarations worker reads manifests and runs form
#: hooks as a uid of their own, so it is root for the run worker's reason
SAME_IMAGE_AS = {"aisc-eval-declarations-worker": "aisc-eval-worker"}


def _as_root() -> set[str]:
    found = set()
    for b in policy.builds():
        user, base = policy.runs_as(policy.stages(b.dockerfile), b.target)
        user = b.user or user
        if user in (None, "root", "0") and not base.startswith(policy.UNPRIVILEGED_BASES):
            found.add(b.service)
    return found


def test_only_the_worker_and_the_publisher_run_as_root():
    assert sorted(_as_root() - set(ROOT_USERS)) == [], "give these images a USER"


def test_every_build_context_has_a_dockerignore():
    missing = sorted({policy.relative(b.context) for b in policy.builds()
                      if not (b.context / ".dockerignore").is_file()
                      and not b.dockerfile.with_name(b.dockerfile.name + ".dockerignore").is_file()})
    assert missing == [], "add a .dockerignore to these build contexts"


def test_a_service_that_keeps_root_runs_one_of_the_two_images():
    for file, name, service in policy.compose_services():
        if name in SAME_IMAGE_AS:
            builder = dict((n, s) for f, n, s in policy.compose_services() if f == file)[SAME_IMAGE_AS[name]]
            assert "build" not in service and service["image"] == builder["image"], \
                f"{name} in {file} runs an image of its own"
            assert service.get("user") == builder.get("user"), f"{name} in {file} runs as another user"
