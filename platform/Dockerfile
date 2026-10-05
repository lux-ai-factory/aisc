FROM python:3.12-slim-bookworm
WORKDIR /app
# pg_restore for `python -m platform_service.isolate verify-dump` in the one-shot container.
# Bookworm is pinned: its client (15) restores a PG14 custom dump into PG14, while the trixie
# client (17) emits SET transaction_timeout, which PG14 refuses.
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY platform_service ./platform_service
# core's migrations, in the image as well as mounted, so the service starts
# without depending on a bind mount.
COPY migrations ./migrations
COPY project-template ./project-template
# the ledger's person mapping, applied to its own database ledger_identity
COPY ledger-identity ./ledger-identity
EXPOSE 8000
CMD ["uvicorn", "platform_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
