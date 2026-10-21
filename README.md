# AI Assessment Sandbox Configurator (AISC)

AISC is a platform for assessing an AI system against the EU AI Act and similar requirements. A
project walks through four steps: **1** Qualify the AI system (describe the system and its components
in its AI card, and find its AI Act risk class), **2** Set control objectives (rate the system's risks
and link them to the control objectives it must meet), **3** Choose tests and checklists (install the
ones the assessment needs), **4** Collect evidence (answer the checklists, run the tests, look at the
results and compose the report). The steps are built from modules, most of them in a git submodule of
their own; this repository ties them together and runs the whole stack
with Docker Compose, behind one sign-in.

**Details** (components, how it works, configuration, tests): [docs/guide.md](docs/guide.md).
Background documentation (architecture, mission, user guide):
[lux-ai-factory/rfc](https://github.com/lux-ai-factory/rfc).

## Prerequisites

**Machine**
- Linux, Windows 10 or 11, or macOS, on x86_64. Linux is tested; Windows and macOS should work the same way
  but have not been tried yet, and arm64 has not been tested.
- At least 8 GB of RAM for the stack (it uses about 4 GB at rest; test plugins that run a model locally need
  more) and 30 GB of disk (about 14 GB of images, Docker's build cache, and the data). On Windows and macOS,
  Docker Desktop gives its Linux machine part of the computer's memory: a computer with 16 GB is comfortable.
- Free ports 80, 443, 8100 and 8188, and 8081, 5432, 5672, 6379, 9000 and 3322 on `127.0.0.1`.

**Software**
- Docker with the Compose plugin, Compose 2.17 or later (`docker compose version`):
  - Linux: Docker Engine 23 or later, used by a user allowed to use Docker.
  - Windows and macOS: [Docker Desktop](https://www.docker.com/products/docker-desktop/), started. On Windows it
    sets up what it needs to run Linux containers on its first start; nothing else is needed there.
- [Git](https://git-scm.com/downloads). Git LFS is not needed: only the test data of `apps/eval` is kept in it,
  and the install does not use it.
- [uv](https://docs.astral.sh/uv/getting-started/installation/), which runs the install script and fetches the
  Python it needs.

On Windows, all three install from PowerShell:
```powershell
winget install --id Docker.DockerDesktop -e
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
```
then sign out and in again, and start Docker Desktop once.

**Access**
- Internet access while installing: GitHub (submodules, the test plugins, MinIO's source), Docker Hub, quay.io and
  ghcr.io (images), PyPI, npm and the Go module proxy (packages), Debian and Alpine package mirrors. While running: the hosted catalogue for public
  projects, and the model providers a project uses.
- Optional: a `GITHUB_TOKEN` that can read lux-ai-factory's private plugin repos, added to `env.secrets`;
  without it those plugins are skipped. Optional model keys are in [docs/guide.md](docs/guide.md).

## Install and run

The same commands on every system: in a terminal on Linux or macOS, in PowerShell or Windows Terminal on
Windows.

1. **Clone with the submodules**, keeping Linux line endings (the containers run the scripts in it):
   ```
   git -c core.autocrlf=false clone --recursive --branch feat/unified-modules https://github.com/lux-ai-factory/aisc.git
   cd aisc
   ```
   On Windows, clone inside your own user folder (for example `C:\Users\<you>\aisc`), not in a folder
   OneDrive synchronises. Already cloned without the submodules: `git submodule update --init --recursive`.

2. **Start the stack** (the first start builds every image and takes several minutes; on Windows and macOS
   the first start is slower than on Linux, as the containers read the clone through Docker Desktop):
   ```
   uv run scripts/aisc.py start
   ```
   It checks Docker, Compose, the branch and the submodules first and says what to fix; makes the
   secrets (none is committed; it keeps existing values, so run it again after a pull); builds, trying a
   failed build twice more; starts the stack; and waits until the sign-in page answers. On Linux and macOS,
   `./scripts/start.sh` does the same.

3. **By hand instead**, the same in two commands:
   ```
   uv run scripts/aisc.py secrets
   docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build
   ```
   `up -d` returns before the sign-in is ready: a page opened in the first 30 seconds or so shows 502.

4. **Sign in** at http://localhost:8100 as `admin` / `admin` (or `user` / `user`, an ordinary account) and
   create a project. Only this machine reaches the sign-in, so the names are the passwords. An install
   served to others (`CADDY_DOMAIN` set to an `https://` address) gets generated passwords instead, kept as
   `AISC_ADMIN_PASSWORD` and `AISC_USER_PASSWORD` in `env.secrets`, which git ignores: show them with
   ```
   uv run scripts/aisc.py password
   ```
   To choose your own: `uv run scripts/aisc.py rotate-infra-password AISC_ADMIN_PASSWORD --ask` (it sets it
   in Keycloak and in `env.secrets` together, so the checks keep signing in).

5. **Check it:** `./scripts/verify.sh --stack` (needs `python3` and `uv`; the plugin check installs every plugin
   and takes a while). The checks are bash scripts: on Windows, run `bash scripts/verify.sh --stack` from Git
   Bash, which Git for Windows installs; they have not been tried there yet.

**If something stops**
- "Docker is not running": start Docker Desktop (or the docker service on Linux) and wait until it says it
  is running.
- Port 80 or 443 is taken (common on Windows, by IIS or another web server): see what holds it with
  `netstat -ano | findstr :80` in PowerShell (`sudo lsof -i :80` on Linux and macOS), and stop that program.
- A build fails on the network or the disk: run the same command again; what was built is kept.

Running the engine on its own, your own plugins, the settings and the tests are in
[docs/guide.md](docs/guide.md).

## Contributing

- A change to a submodule is committed in the submodule first, then the new pin is committed here.
- Database changes are migration files: `platform/migrations/` for the `platform` database,
  `platform/project-template/` for what every new project database starts with, and each module's
  own migrations for its tables. Applied migrations never run again, so a change goes in a new file.
- Tests never use the running stack's database; see [Tests](docs/guide.md#tests).
- Read [CONTRIBUTING.md](CONTRIBUTING.md). Contributions are made under the contributor license
  agreements in this repository (`AISC ICLA (Individuals).txt`, `AISC CCLA (Entities).txt`) and
  licensed under [Apache 2.0](LICENSE.md).

## License

Apache License 2.0, see [LICENSE.md](LICENSE.md).
© 2024–2026 Université du Luxembourg and Luxembourg Institute of Science and Technology.
