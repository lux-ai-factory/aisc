-- The systems a project assesses over the network (Manage → Connections, connections plan 2026-09-29).
-- Owned by the platform, like schema llm: no module or reader role gets USAGE. The key is stored as
-- a Fernet token only, and only the internal resolve route decrypts it. A deleted connection keeps
-- its row (deleted_at): past evaluations still name it, and it no longer resolves.
CREATE SCHEMA IF NOT EXISTS connection;
REVOKE ALL ON SCHEMA connection FROM PUBLIC;
COMMENT ON SCHEMA connection IS 'The systems this project assesses over the network (Manage, Connections); keys stored as Fernet tokens only';

CREATE TABLE IF NOT EXISTS connection.endpoint (
    name              text PRIMARY KEY CHECK (name ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    label             text NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
    kind              text NOT NULL CHECK (kind IN ('openai', 'rest', 'a2a', 'oip')),
    base_url          text NOT NULL,
    method            text NOT NULL DEFAULT 'POST' CHECK (method IN ('GET', 'POST', 'PUT')),
    path              text NOT NULL DEFAULT '',
    headers           jsonb NOT NULL DEFAULT '{}',
    secret_header     text NULL,
    body_template     jsonb NULL,
    response_path     text NULL,
    refusal           jsonb NULL,
    model             text NULL,
    timeout_s         integer NOT NULL DEFAULT 60 CHECK (timeout_s BETWEEN 1 AND 600),
    protocol_version  text NULL CHECK (protocol_version IN ('1.0', '0.3')),
    secret_ciphertext text NULL,
    engine_component  uuid NULL,
    updated_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        text NULL,
    last_test_at      timestamptz NULL,
    last_test_ok      boolean NULL,
    last_test_detail  text NULL,
    deleted_at        timestamptz NULL
);

-- A key issued to one evaluation run to reach one connection through the platform's protocol
-- endpoints (AISC-native, OpenAI-compatible, A2A, Open Inference Protocol). Only its sha256 is kept,
-- with the connection's fingerprint at issue: the record of what that run could call.
CREATE TABLE IF NOT EXISTS connection.run_key (
    key_hash     text PRIMARY KEY CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    name         text NOT NULL REFERENCES connection.endpoint (name) ON DELETE CASCADE,
    fingerprint  text NOT NULL,
    issued_at    timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    uses         integer NOT NULL DEFAULT 0,
    last_used_at timestamptz NULL
);

REVOKE ALL ON ALL TABLES IN SCHEMA connection FROM PUBLIC;
