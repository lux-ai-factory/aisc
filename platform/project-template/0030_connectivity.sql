-- One connection model (Manage > Connectivity): every way the project reaches a model or a system is a row of
-- connection.endpoint, and what it is used for besides reaching the assessed system is a row of connection.use.
--
-- * kind 'provider': a model provider account or a self-hosted model server (column `provider`, a key of the
--   platform's llm_catalogue); its model is chosen in each use. Hosted providers keep base_url '' (their URL is
--   the catalogue's constant). A provider connection never reaches the assessed system.
-- * connection.use: 'agent' (a Configurator agent runs on it, with a model) or 'tool' (tests may use it in the
--   listed roles; `tool_name` is what helper:<pid>/<name> resolves).
-- * A connection that reaches the assessed system (target_key) has no live use, and a used connection gets no
--   target: the trigger keeps them apart, locking the endpoint row so two saves cannot both pass.
--
-- llm.provider, llm.system_choice and helper.model are moved here by connection.move_llm_and_helpers() and then
-- left as they are (no longer written); dropping them is a later step.

ALTER TABLE connection.endpoint ADD COLUMN IF NOT EXISTS provider text NULL CHECK (provider ~ '^[a-z]{2,20}$');
ALTER TABLE connection.endpoint DROP CONSTRAINT IF EXISTS endpoint_provider_kind;
ALTER TABLE connection.endpoint ADD CONSTRAINT endpoint_provider_kind CHECK ((kind = 'provider') = (provider IS NOT NULL));
ALTER TABLE connection.endpoint DROP CONSTRAINT IF EXISTS endpoint_provider_no_target;
ALTER TABLE connection.endpoint ADD CONSTRAINT endpoint_provider_no_target CHECK (kind <> 'provider' OR target_key IS NULL);

CREATE TABLE IF NOT EXISTS connection.use (
    id          bigserial PRIMARY KEY,
    connection  text NOT NULL REFERENCES connection.endpoint (name) ON DELETE RESTRICT,
    use         text NOT NULL CHECK (use IN ('agent', 'tool')),
    agent       text NULL CHECK (agent IN ('card_agent', 'risk_mapper')),
    roles       text[] NULL CHECK (
                    roles <@ ARRAY['judge', 'attacker', 'grader', 'embedder', 'generator']::text[]
                    AND cardinality(roles) >= 1),
    model       text NULL CHECK (length(model) BETWEEN 1 AND 200),
    label       text NULL CHECK (length(label) BETWEEN 1 AND 120),
    tool_name   text NULL CHECK (tool_name ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text NULL,
    deleted_at  timestamptz NULL,
    CONSTRAINT use_agent_fields CHECK ((use = 'agent') = (agent IS NOT NULL AND model IS NOT NULL)),
    CONSTRAINT use_tool_fields CHECK ((use = 'tool') = (roles IS NOT NULL AND tool_name IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS use_one_per_agent ON connection.use (agent) WHERE use = 'agent' AND deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS use_one_per_tool_name ON connection.use (tool_name) WHERE use = 'tool';
REVOKE ALL ON connection.use FROM PUBLIC;

CREATE OR REPLACE FUNCTION connection.keep_assessed_apart() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'use' THEN
        IF NEW.deleted_at IS NULL AND EXISTS (
                SELECT 1 FROM connection.endpoint e WHERE e.name = NEW.connection AND e.target_key IS NOT NULL
                FOR SHARE) THEN
            RAISE EXCEPTION 'connection % reaches the assessed system: it cannot be used as a test tool or by an agent',
                NEW.connection;
        END IF;
    ELSIF NEW.target_key IS NOT NULL AND EXISTS (
            SELECT 1 FROM connection.use u WHERE u.connection = NEW.name AND u.deleted_at IS NULL) THEN
        RAISE EXCEPTION 'connection % is used as a test tool or by an agent: it cannot reach the assessed system',
            NEW.name;
    END IF;
    RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS use_keeps_assessed_apart ON connection.use;
CREATE TRIGGER use_keeps_assessed_apart BEFORE INSERT OR UPDATE ON connection.use
    FOR EACH ROW EXECUTE FUNCTION connection.keep_assessed_apart();
DROP TRIGGER IF EXISTS endpoint_keeps_assessed_apart ON connection.endpoint;
CREATE TRIGGER endpoint_keeps_assessed_apart BEFORE INSERT OR UPDATE OF target_key ON connection.endpoint
    FOR EACH ROW EXECUTE FUNCTION connection.keep_assessed_apart();

-- The move of what a project kept before: provider keys and agent choices (llm), helper models (helper). Each
-- key moves as the Fernet token it is (same key list), never decrypted. Idempotent: what was moved is skipped.
CREATE OR REPLACE FUNCTION connection.move_llm_and_helpers() RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    h record;
    endpoint_name text;
BEGIN
    INSERT INTO connection.endpoint (name, label, kind, provider, base_url, secret_ciphertext, updated_at, updated_by)
    SELECT 'llm-' || p.provider, p.provider, 'provider', p.provider, coalesce(p.base_url, ''), p.ciphertext,
           p.updated_at, p.updated_by
      FROM llm.provider p
    ON CONFLICT (name) DO NOTHING;

    INSERT INTO connection.use (connection, use, agent, model, updated_at, updated_by)
    SELECT 'llm-' || c.provider, 'agent', c.system, c.model, c.updated_at, c.updated_by
      FROM llm.system_choice c
     WHERE NOT EXISTS (SELECT 1 FROM connection.use u WHERE u.use = 'agent' AND u.agent = c.system
                                                       AND u.deleted_at IS NULL);

    FOR h IN SELECT * FROM helper.model ORDER BY name LOOP
        CONTINUE WHEN EXISTS (SELECT 1 FROM connection.use u WHERE u.use = 'tool' AND u.tool_name = h.name);
        endpoint_name := h.name;
        IF EXISTS (SELECT 1 FROM connection.endpoint e WHERE e.name = endpoint_name) THEN
            endpoint_name := left(h.name, 56) || '-helper';
        END IF;
        INSERT INTO connection.endpoint (name, label, kind, provider, base_url, secret_ciphertext, updated_at,
                                         updated_by, deleted_at)
        VALUES (endpoint_name, h.label, 'provider', 'compatible', h.endpoint_url, h.ciphertext, h.updated_at,
                h.updated_by, h.deleted_at);
        INSERT INTO connection.use (connection, use, roles, label, tool_name, updated_at, updated_by, deleted_at)
        VALUES (endpoint_name, 'tool', h.roles, h.label, h.name, h.updated_at, h.updated_by, h.deleted_at);
    END LOOP;
END $$;

SELECT connection.move_llm_and_helpers();
