# Locally developed plugins

`PLUGIN_PATH` points here, and the engine and the eval worker discover anything in
it as a source tree. It is deliberately empty.

The plugins that ship with the platform live in `def_plugins/` and are **published
to the package index** at bring-up by the `plugin-publisher` service. The engine
installs them from there, on demand, exactly like any third-party plugin, which is
what makes the catalogue the single place to discover a test.

Drop a plugin package here only while you are developing it.
