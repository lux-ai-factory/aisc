# The report composer: the Report of step 4, Collect evidence. shared/identity (aisc_identity) is not
# copied: docker compose mounts it at /app/shared/identity.
FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
COPY --from=ghcr.io/astral-sh/uv:0.9.9@sha256:f6e3549ed287fee0ddde2460a2a74a2d74366f84b04aaa34c1f19fec40da8652 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/req.txt \
 && uv pip install --system --no-cache -r /tmp/req.txt && rm /tmp/req.txt
COPY report_composer ./report_composer
COPY migrations ./migrations
ENV PYTHONPATH=/app:/app/shared/identity
RUN useradd --system --uid 10021 --no-create-home composer
USER composer
EXPOSE 8095
CMD ["uvicorn", "report_composer.app:app", "--host", "0.0.0.0", "--port", "8095", "--proxy-headers"]

