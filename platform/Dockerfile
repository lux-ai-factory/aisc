FROM python:3.12-slim-bookworm
WORKDIR /app
# pg_restore for `python -m platform_service.isolate verify-dump` in the one-shot container
# (01-specs.md I12.14). Bookworm pinned: its client (15) restores a PG14 custom dump into PG14; the
# trixie client (17) emits SET transaction_timeout, which PG14 refuses.
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY platform_service ./platform_service
# core's migrations. In the image as well as mounted, so the service is
# complete on its own and does not depend on a bind mount to start.
COPY migrations ./migrations
COPY project-template ./project-template
EXPOSE 8000
CMD ["uvicorn", "platform_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
