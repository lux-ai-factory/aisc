-- Endpoints belong to targets (targets plan v2, 2026-09-29): a connection is the endpoint of one
-- assessment target (template 0014), exactly one per target among the connections in use. NULL
-- is a connection nobody has assigned yet (every connection made before this). The target is set
-- once: pointing an endpoint at another target is a new connection, so earlier runs keep
-- resolving to what they called.
ALTER TABLE connection.endpoint ADD COLUMN IF NOT EXISTS target_key text NULL
    REFERENCES target.target (key) ON DELETE RESTRICT;
CREATE UNIQUE INDEX IF NOT EXISTS endpoint_one_per_target ON connection.endpoint (target_key)
    WHERE deleted_at IS NULL AND target_key IS NOT NULL;
