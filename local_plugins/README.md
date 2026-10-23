# Locally developed plugins

`PLUGIN_PATH` points here, and the engine and the eval worker discover anything in
it as a source tree. It is deliberately empty.

The platform's own plugins are not kept in this checkout. When an admin installs a test
from the catalogue, the `plugin-publisher` service fetches the plugin's repo from GitHub,
builds it and **publishes it to the package index**, and the engine installs it from there,
exactly like any third-party plugin. That is what makes the catalogue the single place to
discover a test.

Drop a plugin package here only while you are developing it.
