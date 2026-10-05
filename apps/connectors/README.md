# Connectors

Admin-defined connections to the systems AISC assesses. Every technology (OpenAPI, Swagger 2,
cURL, Postman, SOAP, GraphQL, OpenAI-compatible, Ollama, Hugging Face) is imported into one
OpenAPI document; plugins call the unified OpenAPI view at `/gw/<connector>/openapi.json`.
Design: `docs/superpowers/specs/2026-09-24-connectors-design.md`.

Tests: `uv run pytest`. They start a throwaway `postgres:14-alpine` with `docker run --rm`
unless `CONNECTORS_TEST_DATABASE_URL` points at one (never the live database).
