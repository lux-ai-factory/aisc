# Plugins of your own

Put a test plugin you wrote, or your own build of an existing one, in this folder to install it from your
project's catalogue like any other test. Only this README is part of AISC: everything else here is ignored by
git, so your plugins are never committed with AISC.

## Installing one

1. **Copy the plugin's project folder here**, the one with its `pyproject.toml`
   (`cp -r /path/to/my-plugin local_plugins/`). The folder:
   - names its package and version in `pyproject.toml` (`[project] name`, `version`) and depends on
     `aisc-plugin-interface`;
   - keeps its code in a module named after the package (`my_plugin/` or `src/my_plugin/` for `my-plugin`);
   - has a package name of its own: a plugin with the name of a public catalogue entry does not show as a
     plugin of its own (rename your build of an existing plugin, for example `aisc-plugin-langbite-mine`).
2. **Use a private catalogue.** On the project page open the catalogue and choose **Private** (a public
   catalogue shows only the public entries). Your plugin is listed with Source = **Local**; give it its
   dimensions if you want it under "For this project".
3. **Press Install** (it takes the admin role). The plugin publisher builds the plugin from this folder,
   checks it and puts it on the stack's package index, then the engine installs it from there, as it does for
   a public test.

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

The engine and the eval worker also see this folder directly (`PLUGIN_PATH`, mounted at `/app/plugins`): the
engine lists a plugin here with a `+local` version, and that listing is what makes it a Local entry.
