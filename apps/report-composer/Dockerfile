# syntax=docker/dockerfile:1.19
# The report composer: the Report of step 4, Collect evidence. The shared code (aisc_identity) goes into the image
# from the `shared` build context, at /app/shared/identity.
# Stand-in for the `shared` build context. The baked stack (docker-compose.baked.yml) passes the checkout's shared/
# folder under that name and its code goes into the image; the development stack passes none and mounts shared/identity
# over the stand-in packages instead, so this build works for both. Each stand-in raises ImportError,
# so an image built without the shared context fails loudly.
FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704 AS shared
RUN for p in aisc_identity aisc_redact aisc_service_client; do mkdir -p /identity/$p \
 && echo "raise ImportError('$p is a stand-in: build this image with docker-compose.baked.yml, which passes the aisc shared folder as the shared build context')" \
      > /identity/$p/__init__.py; done

FROM python:3.12.15-slim@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
COPY --from=ghcr.io/astral-sh/uv:0.9.9@sha256:f6e3549ed287fee0ddde2460a2a74a2d74366f84b04aaa34c1f19fec40da8652 /uv /uvx /bin/
WORKDIR /app
# the shared identity folder the development stack mounts (aisc_identity, the secret rule aisc_redact, the service
# client aisc_service_client), without local environments and caches, read-only
COPY --chmod=a=rX --exclude=.venv --exclude=*.egg-info --exclude=**/__pycache__ --exclude=.pytest_cache \
     --exclude=.ruff_cache --from=shared /identity /app/shared/identity
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

