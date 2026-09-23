FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
COPY platform_service ./platform_service
# core's migrations. In the image as well as mounted, so the service is
# complete on its own and does not depend on a bind mount to start.
COPY migrations ./migrations
COPY project-template ./project-template
EXPOSE 8000
CMD ["uvicorn", "platform_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
