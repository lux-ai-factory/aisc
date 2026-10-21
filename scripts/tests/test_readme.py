"""The README takes a newcomer from nothing to a running AISC, on Windows, macOS or Linux."""
import re
import subprocess

from conftest import ROOT

README = ROOT / "README.md"


def section(title: str) -> str:
    """The text of one `## ` section, its subsections included."""
    return README.read_text().split(f"\n## {title}\n", 1)[1].split("\n## ", 1)[0]


def test_the_readme_lists_what_an_install_needs():
    """Every requirement to install and run the whole stack is in the README itself."""
    text = README.read_text()
    needs = section("Before you install")
    for needed in ("x86_64", "RAM", "30 GB", "8100 and 8188", "port 80 and 443", "8081", "5432", "Internet", "PyPI",
                   "npm"):
        assert needed in needs, needed
    for needed in ("Compose plugin 2.17", "Docker Desktop", "uv", "WSL 2", "virtualisation", "administrator rights"):
        assert needed in text, needed


def test_installing_needs_no_private_submodule():
    """Every submodule is public, so the README's clone command works without a GitHub account."""
    assert "submodule is private" not in README.read_text() and "submodules are private" not in README.read_text()
    assert "add-controls" not in (ROOT / ".gitmodules").read_text()


def test_each_system_installs_its_tools_and_then_everyone_runs_the_same_commands():
    """What differs per system (Docker and uv) is written per system; the download and start once, for all."""
    tools = section("1. Install Docker and uv")
    for system in ("### Windows", "### macOS", "### Linux"):
        assert system in tools, system
    assert "aisc.py start" not in tools and "clone" not in tools
    assert "uv run scripts/aisc.py start" in section("2. Download and start AISC")
    # the quick start and the step everyone follows: nowhere else
    assert README.read_text().count("git -c core.autocrlf=false clone") == 2


def test_the_readme_does_not_teach_installing_git():
    text = README.read_text()
    for teaching in ("Git.Git", "apt install git", "xcode-select", "Docker, Git", "Git and uv"):
        assert teaching not in text, teaching


def test_every_clone_command_keeps_linux_line_endings():
    """The containers run scripts from the clone; a clone that converts line endings breaks them on Windows."""
    clones = re.findall(r"^.*git\b.*\bclone\b.*$", README.read_text(), re.M)
    assert clones
    for line in clones:
        if "github.com" in line:
            assert "git -c core.autocrlf=false clone --recursive" in line, line


def test_installing_needs_no_unix_tool_on_windows():
    windows = section("1. Install Docker and uv").split("### Windows", 1)[1].split("\n### ", 1)[0]
    for unix_only in ("curl", "openssl", "sudo", "bash"):
        assert unix_only not in windows, unix_only


def test_the_readme_walks_the_four_steps_of_the_project_page():
    intro = section("What it does")
    assert "four steps" in intro
    for step in ("**Qualify the AI system.**", "**Set control objectives.**", "**Choose tests and checklists.**",
                 "**Collect evidence.**"):
        assert step in intro, step


def test_the_readme_says_how_to_stop_restart_update_and_remove():
    everyday = section("Everyday use")
    for command in ("docker compose -p aisc stop", "uv run scripts/aisc.py start", "git pull",
                    "git submodule update --init --recursive", "docker compose -p aisc down -v"):
        assert command in everyday, command


def test_every_local_link_and_image_exists():
    """Links into the repository (files and the guide's headings) resolve, so a newcomer never meets a 404."""
    text = README.read_text()
    # a target in <...> may hold spaces and parentheses (AISC ICLA (Individuals).txt)
    targets = [a or b for a, b in re.findall(r"\]\((?!https?://|#)(?:<([^>]+)>|([^)\s]+))\)", text)]
    assert "docs/images/project-page.png" in targets
    guide_headings = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
                      for h in re.findall(r"^#+ (.+)$", (ROOT / "docs/guide.md").read_text(), re.M)}
    for target in targets:
        path, _, anchor = target.partition("#")
        assert (ROOT / path).exists(), target
        if anchor and path == "docs/guide.md":
            assert anchor in guide_headings, target


def test_every_anchor_inside_the_readme_has_its_heading():
    text = README.read_text()
    headings = {re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-")
                for h in re.findall(r"^#+ (.+)$", text, re.M)}
    for anchor in re.findall(r"\]\(#([^)]+)\)", text):
        assert anchor in headings, anchor


def test_the_readme_says_start_moves_a_new_install_off_a_taken_port_80():
    start = section("2. Download and start AISC").split("### What `start` does", 1)[1]
    assert "port 80" in start and "8080" in start
    assert "port 80" in section("Before you install") and "8080" in section("Before you install")


def test_the_guide_names_the_engine_port_settings():
    guide = (ROOT / "docs/guide.md").read_text()
    for name in ("ENGINE_PORT", "ENGINE_HTTPS_PORT", "env.local"):
        assert name in guide, name


def test_the_readme_says_admin_admin_holds_only_until_the_passwords_change():
    sign_in = section("3. Open AISC")
    assert "admin" in sign_in and "uv run scripts/aisc.py password" in sign_in
    assert "rotate-infra-password" in sign_in and "last message" in sign_in


def test_no_document_gives_a_compose_command_that_drops_the_https_file():
    """A hand-written `docker compose ... -f docker-compose-infra.development.yml ...` names the three base files
    only. On an install served over https, following it recreates Caddy without docker-compose.https.yml, and 443
    stops answering. The documents send the reader to `uv run scripts/aisc.py start` instead, which adds the file
    when the install needs it. Only this repository's own Markdown: a submodule's documents are its own."""
    tracked = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True)
    offending = []
    for name in tracked.stdout.split():
        # a command continued over several lines with a trailing backslash is read as one line
        for command in (ROOT / name).read_text().replace("\\\n", " ").splitlines():
            if ("docker compose" in command and "-f docker-compose-infra.development.yml" in command
                    and "docker-compose.https.yml" not in command):
                offending.append(name)
    assert offending == []
