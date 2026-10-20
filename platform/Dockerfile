FROM python:3.12-slim-bookworm
WORKDIR /app
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
