## def_plugins folder

`start` no longer uses this folder. Plugins are fetched from GitHub, built and published to the stack's
package index when an admin installs a test from the catalogue, so nothing is cloned here at start.
If an older install left plugin sources in it, you can delete them by hand.

The one exception is `docker-compose.engine-standalone.yml`, which still mounts this folder as a local
plugin folder for a standalone engine.
