-- Which connection served a run: the worker names the evaluation plugin it runs when it asks for the run's
-- pass, and every resolve or run-key issuance under that pass is kept, with the connection's kind and its
-- fingerprint at that moment (platform_service/run_passes.py). Results read it back to say what a run
-- reached. Never the key or the run key. The uses outlive the pass, which ends with its run.
ALTER TABLE core.run_pass ADD COLUMN IF NOT EXISTS evaluation_plugin uuid;

CREATE TABLE IF NOT EXISTS core.run_pass_use (
    id bigserial PRIMARY KEY,
    pass_hash text NOT NULL,
    evaluation_plugin uuid NOT NULL,
    pid uuid NOT NULL,
    connection text NOT NULL,
    protocol text NOT NULL,
    fingerprint text NOT NULL,
    used_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS run_pass_use_evaluation_plugin ON core.run_pass_use (evaluation_plugin, pid, used_at);
