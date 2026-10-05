# The connectors service. shared/identity is mounted at /app/shared/identity by docker compose.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY aisc_connectors ./aisc_connectors
ENV PYTHONPATH=/app:/app/shared/identity PATH=/app/.venv/bin:$PATH
EXPOSE 8097
CMD ["uvicorn", "aisc_connectors.app:app", "--host", "0.0.0.0", "--port", "8097"]
