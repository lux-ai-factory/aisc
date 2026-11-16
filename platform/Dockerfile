# The platform: projects, the ledger's writer, connections. It installs exactly what platform/uv.lock pins and
# carries the shared code (aisc_identity, the plugin-side connection client) from the `shared` build context
# that compose passes, so the running service reads no code from a mount.
FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/req.txt \
 && uv pip install --system --no-cache -r /tmp/req.txt && rm /tmp/req.txt
COPY --from=shared identity/aisc_identity /app/shared/identity/aisc_identity
COPY --from=shared plugin-interface/src /app/shared/plugin-interface/src
ENV PYTHONPATH=/app/shared/identity:/app/shared/plugin-interface/src
COPY platform_service ./platform_service
# core's migrations, in the image as well as mounted, so the service starts
# without depending on a bind mount.
COPY migrations ./migrations
COPY project-template ./project-template
# the ledger's person mapping, applied to its own database ledger_identity
COPY ledger-identity ./ledger-identity
RUN useradd --system --uid 10020 --no-create-home platform
USER platform
EXPOSE 8000
CMD ["uvicorn", "platform_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
