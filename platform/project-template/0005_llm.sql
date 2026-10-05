-- The per-project LLM keys and model choices.
-- Only the platform, the owner of this database, reads or writes them: no module role gets USAGE.
-- A key is stored as a Fernet token only; there is no plaintext, masked or partial form of it.
CREATE SCHEMA IF NOT EXISTS llm;
REVOKE ALL ON SCHEMA llm FROM PUBLIC;

CREATE TABLE IF NOT EXISTS llm.provider (
    provider   text PRIMARY KEY CHECK (provider ~ '^[a-z]{2,20}$'),
    ciphertext text NULL,
    base_url   text NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NULL
);

CREATE TABLE IF NOT EXISTS llm.system_choice (
    system     text PRIMARY KEY CHECK (system IN ('card_agent', 'risk_mapper')),
    provider   text NOT NULL REFERENCES llm.provider (provider) ON DELETE RESTRICT,
    model      text NOT NULL CHECK (length(model) BETWEEN 1 AND 200),
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NULL
);

REVOKE ALL ON ALL TABLES IN SCHEMA llm FROM PUBLIC;
