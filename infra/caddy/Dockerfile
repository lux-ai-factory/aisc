# syntax=docker/dockerfile:1.19
# The gateway: Caddy with the development Caddyfile as its default, the same file under the name the Configurator's
# Caddyfile imports, the Configurator's Caddyfile (docker-compose.baked.configurator.yml runs Caddy on it), and the
# pages it serves. Used by the baked overlay (docker-compose.baked.yml), which supplies the `homepage` build context:
# the repository's homepage/ folder. The certificates are not here: they are mounted.
FROM caddy:2.10.2@sha256:c3d7ee5d2b11f9dc54f947f68a734c84e9c9666c92c88a7f30b9cba5da182adb
COPY --chmod=0444 Caddyfile.development /etc/caddy/Caddyfile
COPY --chmod=0444 Caddyfile.development /etc/caddy/Caddyfile.development
COPY --chmod=0444 Caddyfile.configurator /etc/caddy/Caddyfile.configurator
COPY --chmod=a=rX --from=homepage . /srv/homepage
