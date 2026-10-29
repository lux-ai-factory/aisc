# def_plugins

The default plugin folder of the engine run on its own (`docker-compose.engine-standalone.yml`, without the
platform or the gateway). That compose file mounts `${PLUGIN_PATH:-./def_plugins}` at `/app/plugins` in
`aisc-backend` and `aisc-eval-worker`, and the engine lists a plugin folder it finds there (one with a
`pyproject.toml`) as a local plugin. See [the engine on its own](../docs/guide.md#the-engine-on-its-own).

The AISC stack (`uv run scripts/aisc.py start`) does not use this folder. There, a test is fetched from GitHub,
built and put on the stack's package index when an admin installs it from the catalogue; your own plugins go in
[`local_plugins/`](../local_plugins/README.md). Plugin sources left here are not read by the stack and can be
deleted.

Only this README is part of AISC: the rest of the folder is ignored by git.
