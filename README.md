# AI Assessment Sandbox Configurator (AISC)

AISC is a platform for assessing an AI system against the EU AI Act and similar requirements. A
project walks through six steps: **1** qualification (describe the system and get its AI card),
**2** control objectives (rate the risks and choose the objectives that mitigate them), **3** install
the plugins and tools the assessment needs, **4** execute the tests and address the controls,
**5** analyse the results on the dashboard, **6** compose the report. Each step is a module, most of
them in a git submodule of their own; this repository ties them together and runs the whole stack
with Docker Compose, behind one sign-in.

**Details** (components, how it works, configuration, tests): [docs/guide.md](docs/guide.md).
Background documentation (architecture, mission, user guide):
[lux-ai-factory/rfc](https://github.com/lux-ai-factory/rfc).

## Prerequisites

- Linux with Docker Engine and the Docker Compose v2 plugin (`docker compose`).
- Free ports 80, 443, 8081, 8100 and 8188, and 5432, 5672, 6379, 9000 and 3322 on `127.0.0.1`.
- `git`, `openssl`, `python3` and `setfacl` (package `acl`).

## Install and run

1. **Clone with the submodules:**
   ```bash
   git clone --recursive --branch feat/unified-modules https://github.com/lux-ai-factory/aisc.git
   cd aisc
   ```
   Already cloned without them: `git submodule update --init --recursive`.

2. **Make the secrets, once** (none is committed; rerun after a pull, it keeps existing values):
   ```bash
   ./scripts/secrets.sh
   ```

3. **Start the stack** (the first start builds every image and takes several minutes):
   ```bash
   docker compose -p aisc --env-file env.runtime -f docker-compose.plugin_downloader.yml \
     -f docker-compose-infra.development.yml -f docker-compose.development.yml up -d --build
   ```

4. **Sign in** at http://localhost:8100 with a development account, `user` / `user` or
   `admin` / `admin` (localhost only), and create a project.

5. **Check it:** `./scripts/verify.sh --stack`.

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
