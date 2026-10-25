-- What an OpenAI-compatible connection carries besides text and a history: function calling (tools)
-- and log probabilities. Set by an admin, checked by the Test button; a plugin that needs tools is
-- refused before its run on a connection without them.
ALTER TABLE connection.endpoint ADD COLUMN IF NOT EXISTS supports_tools boolean NOT NULL DEFAULT false;
ALTER TABLE connection.endpoint ADD COLUMN IF NOT EXISTS supports_logprobs boolean NOT NULL DEFAULT false;
ALTER TABLE connection.endpoint ADD CONSTRAINT endpoint_capabilities_openai_only
    CHECK (kind = 'openai' OR NOT (supports_tools OR supports_logprobs)) NOT VALID;
