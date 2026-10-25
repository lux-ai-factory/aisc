-- A run key issued under a run's pass ends with the pass: the platform deletes the pass's keys when the
-- worker revokes it, and refuses a key whose pass is gone. NULL: a key issued with the stack's
-- connections token, valid until it expires.
ALTER TABLE connection.run_key ADD COLUMN IF NOT EXISTS pass_hash text NULL
    CHECK (pass_hash IS NULL OR pass_hash ~ '^[0-9a-f]{64}$');
CREATE INDEX IF NOT EXISTS run_key_pass_hash ON connection.run_key (pass_hash) WHERE pass_hash IS NOT NULL;
