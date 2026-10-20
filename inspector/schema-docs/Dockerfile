# Schema diagrams for the launcher's admins: SchemaSpy (Java, Graphviz and the Postgres driver
# come with its image) plus a small Python server that runs it on demand (server.py).
FROM schemaspy/schemaspy:7.0.2

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /srv/schema-docs /srv/schema-docs-work && chown java /srv/schema-docs /srv/schema-docs-work
COPY server.py /app/server.py

USER java
EXPOSE 8080
ENTRYPOINT ["python3", "/app/server.py"]
