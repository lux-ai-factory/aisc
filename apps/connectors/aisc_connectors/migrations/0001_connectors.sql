-- Connectors (spec 2026-09-24). project_pid, ai_system_pid and component_pids are ENGINE pids,
-- referenced softly and checked through the engine API: no foreign key into schema engine (D2).
CREATE TABLE connector.connector (
    pid              uuid PRIMARY KEY,
    project_pid      uuid NOT NULL,
    ai_system_pid    uuid NOT NULL,
    name             text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    slug             text NOT NULL,
    kind             text NOT NULL,
    environment      text NOT NULL CHECK (environment IN ('sandbox', 'production')),
    document         jsonb NOT NULL DEFAULT '{}'::jsonb,
    import_warnings  jsonb NOT NULL DEFAULT '[]'::jsonb,
    auth             jsonb NOT NULL DEFAULT '{"scheme": "none"}'::jsonb,
    settings         jsonb NOT NULL DEFAULT '{}'::jsonb,
    chat             jsonb,
    is_target_access boolean NOT NULL DEFAULT false,
    created_by       text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_pid, slug)
);
CREATE UNIQUE INDEX one_target_access_per_project
    ON connector.connector (project_pid) WHERE is_target_access;

CREATE TABLE connector.secret (
    connector_pid uuid NOT NULL REFERENCES connector.connector (pid) ON DELETE CASCADE,
    name          text NOT NULL,
    ciphertext    text NOT NULL,
    masked        text NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (connector_pid, name)
);

CREATE TABLE connector.operation_policy (
    connector_pid          uuid NOT NULL REFERENCES connector.connector (pid) ON DELETE CASCADE,
    operation_id           text NOT NULL,
    allowed                boolean NOT NULL DEFAULT false,
    changes_data           boolean NOT NULL,
    changes_data_confirmed boolean NOT NULL DEFAULT false,
    patterns               jsonb NOT NULL DEFAULT '{}'::jsonb,
    component_pids         uuid[] NOT NULL DEFAULT '{}',
    PRIMARY KEY (connector_pid, operation_id)
);

CREATE TABLE connector.access_token (
    pid           uuid PRIMARY KEY,
    connector_pid uuid NOT NULL REFERENCES connector.connector (pid) ON DELETE CASCADE,
    token_hash    text NOT NULL UNIQUE,
    label         text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    revoked_at    timestamptz
);

CREATE TABLE connector.publication (
    connector_pid          uuid PRIMARY KEY REFERENCES connector.connector (pid) ON DELETE CASCADE,
    token_pid              uuid NOT NULL REFERENCES connector.access_token (pid),
    secret_key             text NOT NULL,
    secret_config_pid      uuid NOT NULL,
    resource_component_pid uuid NOT NULL,
    llm_component_pid      uuid,
    published_at           timestamptz NOT NULL DEFAULT now()
);

-- One row per gateway or test call. Bodies are never stored (D7).
CREATE TABLE connector.call_log (
    id            bigserial PRIMARY KEY,
    connector_pid uuid NOT NULL,
    operation_id  text,
    token_pid     uuid,
    via           text NOT NULL,
    outcome       text NOT NULL,
    target_status integer,
    latency_ms    integer NOT NULL,
    at            timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX call_log_by_connector ON connector.call_log (connector_pid, at DESC);
