-- A plugin run's pass to the internal connection routes: the worker asks for one naming the run's target
-- and connection references, the plugin gets it in place of the stack's connections token, and the routes
-- open with it only for those references (platform_service/run_passes.py). Only its hash is kept.
CREATE TABLE IF NOT EXISTS core.run_pass (
    pass_hash text PRIMARY KEY,
    refs jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS run_pass_expires_at ON core.run_pass (expires_at);
