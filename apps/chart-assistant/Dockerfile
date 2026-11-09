# The chart assistant (spec: apps/chart-assistant, ~/aisc-working-notes/chart-assistant/spec.md).
FROM python:3.12.15-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/req.txt \
 && uv pip install --system --no-cache -r /tmp/req.txt && rm /tmp/req.txt
COPY chart_assistant ./chart_assistant
RUN useradd --uid 10010 --no-create-home assistant
USER assistant
EXPOSE 8096
CMD ["uvicorn", "chart_assistant.app:app", "--host", "0.0.0.0", "--port", "8096"]
