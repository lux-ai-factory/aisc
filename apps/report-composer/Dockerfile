# The report composer (report run 2026-09-23), step 7. shared/identity is mounted at
# /app/shared/identity by docker compose (aisc_identity).
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/req.txt \
 && uv pip install --system --no-cache -r /tmp/req.txt && rm /tmp/req.txt
COPY report_composer ./report_composer
COPY migrations ./migrations
ENV PYTHONPATH=/app:/app/shared/identity
EXPOSE 8095
CMD ["uvicorn", "report_composer.app:app", "--host", "0.0.0.0", "--port", "8095", "--proxy-headers"]

