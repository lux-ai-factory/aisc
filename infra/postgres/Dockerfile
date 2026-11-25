# syntax=docker/dockerfile:1.19
# Postgres with the initialisation scripts, the roles setup and the host-based access rules the Configurator
# mounts today. Used by the baked overlay (docker-compose.baked.yml), which supplies the `init` and `scripts`
# build contexts: the repository's init/ and scripts/ folders.
FROM postgres:15.19-alpine@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81 AS postgres
COPY --chmod=a=rX --from=init platform-db.sql /docker-entrypoint-initdb.d/05-platform-db.sql
COPY --chmod=a=rX --from=init project-databases.sql /docker-entrypoint-initdb.d/06-project-databases.sql
COPY --chmod=a=rX --from=init keycloak.sql /docker-entrypoint-initdb.d/30-keycloak.sql
COPY --chmod=a=rX --from=init superset-db.sql /docker-entrypoint-initdb.d/50-superset-db.sql
COPY --chmod=a=rX --from=init report-roles.sql /docker-entrypoint-initdb.d/60-report-roles.sql
COPY --chmod=a=rX --from=init inspector-role.sql /docker-entrypoint-initdb.d/70-inspector-role.sql
COPY --chmod=a=rX --from=init chart-assistant-role.sql /docker-entrypoint-initdb.d/75-chart-assistant-role.sql
COPY --chmod=a=rX pg_hba.configurator.conf /etc/postgresql/pg_hba.conf

FROM postgres:15.19-alpine@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81 AS setup
COPY --chmod=a=rX --from=init owner-roles.sql project-database-setup.sql project-databases.sql report-roles.sql inspector-role.sql \
     chart-assistant-role.sql platform-role.sql qualification-role.sql control-objectives-role.sql \
     dashboard-role.sql controls-role.sql engine-role.sql keycloak-role.sql superset-role.sql /setup/
# a one-shot client of the database: it needs no root
USER postgres

FROM postgres:15.19-alpine@sha256:f7d23353e1b15400d22ebe31189f4d314b87a4c129cc400c8c2d8d4ca127bf81 AS report-grants
COPY --chmod=a=rX --from=init report-ro-grants.sql /setup/report-ro-grants.sql
COPY --chmod=a=rX --from=scripts report-grants.sh /setup/report-grants.sh
USER postgres
