# Plugins of your own

Put a test plugin you wrote, or your own build of an existing one, in this folder to install it from your
project's catalogue (step 3, Choose tests and checklists) like any other test. It shows there as a **Local** entry.
Only this README is part of AISC: everything else here is ignored by git, so your plugins are never committed
with AISC.

## How it works

When an admin installs a Local test, the platform asks `plugin-publisher` to build the plugin from its folder here
and put it on the stack's package index (`devpi`); then the engine (`aisc-backend`, `aisc-eval-worker`) installs it
from there, as it does for a public test. [docs/architecture.md](../docs/architecture.md#4-running-tests) shows the
whole path, from install to run.

## Installing one

Start AISC as usual (`uv run scripts/aisc.py start` in the aisc folder). Then:

1. **Copy the plugin's project folder here**, the one with its `pyproject.toml`
   (`cp -r /path/to/my-plugin local_plugins/`). The folder:
   - names its package and version in `pyproject.toml` (`[project] name`, `version`) and depends on
     `aisc-plugin-interface`;
   - keeps its code in a module named after the package (`my_plugin/` or `src/my_plugin/` for `my-plugin`);
   - has a package name of its own: a plugin with the name of a public catalogue entry does not show as a
     plugin of its own (rename your build of an existing plugin, for example `aisc-plugin-langbite-mine`).
     Two folders that build the same package are refused: keep one.
2. **Use a private catalogue.** On the project page open the catalogue and choose **Private** (a public
   catalogue shows only the public entries). Your plugin is listed with Source = **Local**. An admin gives it its
   dimensions in its entry (**Dimensions**, REQ1 to REQ11): they put it under "For this project" and let
   step 4's Evidence map link it to objectives of those dimensions.
3. **Press Install** (it takes the admin role). The plugin publisher builds the plugin from this folder,
   checks it and puts it on the stack's package index, then the engine installs it from there.

## Changing one

A change reaches the stack with a **new version**: raise the `version` in `pyproject.toml`. A project that already
has the plugin shows it as **Installed** and keeps the version it installed (the catalogue offers no second
install there); a project that installs it after the change gets the new version, built from this folder at
that moment. A fresh stack (new volumes) starts with an empty package index; the next Install builds the plugin
again.

## What is built

The publisher builds a copy of the folder and never reads it as the build: the copy leaves out `.git`,
`__pycache__` and tool caches, the top-level `build/`, `dist/`, `venv/` and `.venv/`, and every `.env` file (keep
keys out of a plugin's folder all the same). A link anywhere in the folder is refused.

## Settings and files

| Setting | Meaning | Value in the stack |
|---|---|---|
| `PLUGIN_PATH` (`env.runtime`) | this folder, as the compose files mount it | `./local_plugins/` |
| `LOCAL_PLUGINS_DIR` (`plugin-publisher`) | where the publisher reads the folder, read-only | `/srv/private/local-plugins` |
| mount in `aisc-backend` and `aisc-eval-worker` | where the engine sees the folder (the plugin manager's default plugin folder) | `/app/plugins` |

The engine lists a plugin it finds in `/app/plugins` with a `+local` version, and that listing is what makes it a
Local entry. The dimensions an admin gives a Local test are kept in the project's database
(`catalogue.local_dimension`). The publisher's code for this folder is `infra/plugin-publisher/plugin_publisher/local.py`.
For writing a plugin, see the plugin developer guide in `shared/plugin-interface`.
