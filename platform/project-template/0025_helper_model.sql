-- The per-project helper models: the judge, attacker, grader, embedder and generator an assessment
-- uses, which are not part of the AI system being assessed.
-- Only the platform, the owner of this database, reads or writes them: no module role gets USAGE.
-- A key is stored as a Fernet token only; there is no plaintext, masked or partial form of it.
-- A removed helper keeps its row (deleted_at) so the runs that used it stay explainable.
CREATE SCHEMA IF NOT EXISTS helper;
REVOKE ALL ON SCHEMA helper FROM PUBLIC;

CREATE TABLE IF NOT EXISTS helper.model (
    name         text PRIMARY KEY CHECK (name ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    label        text NOT NULL CHECK (length(label) BETWEEN 1 AND 120),
    endpoint_url text NOT NULL,
    ciphertext   text NULL,
    roles        text[] NOT NULL CHECK (
                     roles <@ ARRAY['judge', 'attacker', 'grader', 'embedder', 'generator']::text[]
                     AND cardinality(roles) >= 1),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    updated_by   text NULL,
    deleted_at   timestamptz NULL
);

REVOKE ALL ON ALL TABLES IN SCHEMA helper FROM PUBLIC;
