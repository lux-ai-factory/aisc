# syntax=docker/dockerfile:1.19
# Keycloak with the realm it imports at start and the sign-in theme. Used by the baked overlay
# (docker-compose.baked.yml), which supplies the `realm` build context: the repository's keycloak/ folder.
FROM quay.io/keycloak/keycloak:26.6.3@sha256:9b0330756022422149aa6502eb2def8cd47c6e1b000c7c65cdb13e7c0133e992
COPY --chmod=a=rX --from=realm aisc-realm.json /opt/keycloak/data/import/aisc-realm.json
COPY --chmod=a=rX --from=realm themes /opt/keycloak/themes
